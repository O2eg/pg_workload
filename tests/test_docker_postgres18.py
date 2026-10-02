import copy
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENABLE_ENV = "WORKLOAD_DOCKER_INTEGRATION"
TRUE_VALUES = {"1", "true", "yes", "y", "on"}

if os.environ.get(ENABLE_ENV, "").lower() not in TRUE_VALUES:
    raise unittest.SkipTest(f"set {ENABLE_ENV}=1 to run Docker PostgreSQL 18 integration tests")

try:
    import docker
    from docker.errors import DockerException
except ImportError as exc:  # pragma: no cover - depends on local test environment
    raise RuntimeError("Install test dependencies first: python3 -m pip install -e '.[test]'") from exc


POSTGRES_PASSWORD = "postgres"
WORKLOAD_DB = "smoke_workload_db"
WORKLOAD_USER = "smoke_workload_user"
WORKLOAD_PASSWORD = "smoke_workload_pw"
CONTAINER_WAIT_SECONDS = 90

# Per-profile post-run invariants. Each query must return the single value "ok" in the
# workload database after `install` + `run`; anything else fails the smoke test.
PROFILE_INVARIANTS = {
    "simple_stock": ("SELECT CASE WHEN count(*) > 0 THEN 'ok' ELSE 'no rows' END FROM simple_stock.stock_items;"),
    "simple_stock_spec_symbols": (
        "SELECT CASE WHEN count(*) >= 3 THEN 'ok' ELSE 'missing tables' END "
        "FROM pg_tables WHERE schemaname = 'simple_stock_spec_symbols';"
    ),
    "imdb": ("SELECT CASE WHEN count(*) > 0 THEN 'ok' ELSE 'no rows' END FROM imdb.title;"),
    "pagila": ("SELECT CASE WHEN count(*) > 0 THEN 'ok' ELSE 'no rows' END FROM pagila.customer;"),
    "many_objects": (
        "SELECT CASE WHEN count(*) > 0 THEN 'ok' ELSE 'no tables' END "
        "FROM pg_tables WHERE schemaname LIKE 'many_objects\\_%';"
    ),
    "emulate_errors": ("SELECT CASE WHEN count(*) > 0 THEN 'ok' ELSE 'no seed rows' END FROM emulate_errors.accounts;"),
    "pss_overflow": (
        "SELECT CASE WHEN count(*) >= 50 THEN 'ok' ELSE 'too few tables' END "
        "FROM pg_tables WHERE schemaname = 'pss_overflow';"
    ),
    "queue_skip_locked": (
        "SELECT CASE WHEN count(*) FILTER (WHERE attempts > 0) > 0 THEN 'ok' ELSE 'no claimed tasks' END "
        "FROM queue_skip_locked.tasks;"
    ),
    "jsonb_docs": ("SELECT CASE WHEN count(*) > 0 THEN 'ok' ELSE 'no rows' END FROM jsonb_docs.documents;"),
    "partition_aging": (
        "SELECT CASE WHEN (SELECT count(*) FROM pg_inherits i "
        "JOIN pg_class c ON c.oid = i.inhrelid "
        "JOIN pg_class p ON p.oid = i.inhparent "
        "JOIN pg_namespace n ON n.oid = p.relnamespace "
        "WHERE n.nspname = 'partition_aging' AND c.relkind = 'r') >= 33 "
        "AND (SELECT count(*) FROM partition_aging.events) > 2000 "
        "THEN 'ok' ELSE 'bad partitions or ingest did not add rows' END;"
    ),
    "bloat_vacuum": (
        "SELECT CASE WHEN vacuum_count >= 1 THEN 'ok' ELSE 'vacuum did not run' END "
        "FROM pg_stat_user_tables WHERE schemaname = 'bloat_vacuum' AND relname = 'accounts';"
    ),
}


def load_workload_module():
    import pg_workload

    return pg_workload


def safe_job_suffix(value):
    suffix = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return suffix[:80] or "script"


def chmod_readable(root):
    for dirpath, _, filenames in os.walk(root):
        os.chmod(dirpath, 0o755)
        for filename in filenames:
            os.chmod(Path(dirpath) / filename, 0o644)


def write_text(path, text):
    path.write_text(text, encoding="utf-8")


def write_yaml(path, data):
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)


def shrink_profile_sql(profile_name, profile_dir):
    sql_dir = profile_dir / "sql"

    if profile_name == "many_objects":
        path = sql_dir / "prepare_schema_02.sql"
        text = path.read_text(encoding="utf-8")
        text = text.replace("partition_count INT := 20;", "partition_count INT := 2;")
        text = text.replace("subpartition_count INT := 20;", "subpartition_count INT := 2;")
        text = text.replace("last_schema_index + 5", "last_schema_index + 2")
        write_text(path, text)

    if profile_name == "pss_overflow":
        schema_path = sql_dir / "pss_overflow-schema.sql"
        workload_path = sql_dir / "01_workload.sql"
        schema_text = schema_path.read_text(encoding="utf-8")
        schema_text = schema_text.replace("FOR i IN 1..1000 LOOP", "FOR i IN 1..50 LOOP")
        write_text(schema_path, schema_text)
        workload_text = workload_path.read_text(encoding="utf-8")
        workload_text = workload_text.replace("random(1, 1000)", "random(1, 50)")
        write_text(workload_path, workload_text)

    if profile_name == "emulate_errors":
        for filename in ("01_workload.sql", "02_workload.sql"):
            path = sql_dir / filename
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            text = text.replace("<= 5", "<= 0")
            text = text.replace("< 3", "< 0")
            text = text.replace("SELECT pg_sleep(2);", "SELECT pg_sleep(0.01);")
            text = text.replace("select pg_sleep(1);", "select pg_sleep(0.01);")
            write_text(path, text)


def split_pgbench_jobs(workload_module, source_profile, profile_data):
    jobs = []
    for job in profile_data.get("jobs", []) or []:
        if job.get("type") != "pgbench":
            psql_job = copy.deepcopy(job)
            psql_job["interval"] = 60
            psql_job["log"] = f"{psql_job.get('name', 'psql')}.log"
            jobs.append(psql_job)
            continue

        scripts = source_profile.expand_scripts(job)
        for script in scripts:
            script_path = script["path"]
            job_name = f"{job.get('name')}_{safe_job_suffix(script_path)}"
            jobs.append(
                {
                    "name": job_name,
                    "type": "pgbench",
                    "interval": 60,
                    "log": f"{job_name}.log",
                    "allow_failure": job.get("allow_failure", False),
                    "no_vacuum": job.get("no_vacuum", True),
                    "clients": 1,
                    "threads": 1,
                    "duration": 1,
                    "scripts": [{"path": script_path}],
                }
            )
    profile_data["jobs"] = jobs
    return profile_data


def build_smoke_root(workload_module, destination):
    workload_module.initialize_project(destination)
    source_profiles = workload_module.load_profiles(destination)

    for profile_name, source_profile in source_profiles.items():
        profile_dir = source_profile.path

        profile_data = copy.deepcopy(source_profile.data)
        if profile_name == "many_objects":
            for step in profile_data.get("prepare", {}).get("steps", []) or []:
                if step.get("path") == "sql/prepare_schema_02.sql":
                    step["repeat"] = 1
        profile_data = split_pgbench_jobs(workload_module, source_profile, profile_data)
        write_yaml(profile_dir / "profile.yml", profile_data)

        shrink_profile_sql(profile_name, profile_dir)

    chmod_readable(destination)


def postgres_container_command():
    return [
        "postgres",
        "-c",
        "shared_preload_libraries=pg_stat_statements,auto_explain",
        "-c",
        "max_connections=80",
        "-c",
        "shared_buffers=64MB",
        "-c",
        "fsync=off",
        "-c",
        "synchronous_commit=off",
        "-c",
        "full_page_writes=off",
        "-c",
        "autovacuum=off",
        "-c",
        "log_min_messages=warning",
    ]


def write_docker_wrapper(path, container_name, binary, mount_root):
    script = f"""#!/bin/sh
mount_root={shlex.quote(str(mount_root))}
case "$PWD" in
  "$mount_root"*) workdir="$PWD" ;;
  *) workdir="/" ;;
esac
exec docker exec -i \\
  -e PGPASSWORD="${{PGPASSWORD:-}}" \\
  -e PGPASSFILE="${{PGPASSFILE:-}}" \\
  -e PGOPTIONS="${{PGOPTIONS:-}}" \\
  -e PGCONNECT_TIMEOUT="${{PGCONNECT_TIMEOUT:-5}}" \\
  -e PGHOST="${{PGHOST:-}}" \\
  -e PGPORT="${{PGPORT:-}}" \\
  -e PGDATABASE="${{PGDATABASE:-}}" \\
  -e PGUSER="${{PGUSER:-}}" \\
  -e PGAPPNAME="${{PGAPPNAME:-}}" \\
  --workdir "$workdir" \\
  {shlex.quote(container_name)} {shlex.quote(binary)} "$@"
"""
    path.write_text(script, encoding="utf-8")
    os.chmod(path, 0o755)


class DockerPostgres18SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workload = load_workload_module()
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="workload-pg18-smoke-")
        cls.smoke_root = Path(cls.temp_dir.name)
        build_smoke_root(cls.workload, cls.smoke_root)
        cls.bin_dir = cls.smoke_root / ".bin"
        cls.bin_dir.mkdir()
        cls.pgdata_parent_dir = cls.smoke_root / "postgresql-data"
        cls.pgwal_dir = cls.smoke_root / "postgresql-wal"

        image = os.environ.get("WORKLOAD_DOCKER_IMAGE", "postgres:18")
        cls.container_name = f"workload-pg18-smoke-{uuid.uuid4().hex[:12]}"

        try:
            cls.docker_client = docker.from_env()
            cls.docker_client.ping()
            cls.docker_client.images.pull(image)
            cls.pgdata_parent_dir.mkdir()
            cls.pgwal_dir.mkdir()
            volumes = {
                str(cls.smoke_root): {"bind": str(cls.smoke_root), "mode": "rw"},
                str(cls.pgdata_parent_dir): {"bind": "/var/lib/postgresql", "mode": "rw"},
                str(cls.pgwal_dir): {"bind": "/var/lib/postgresql-wal", "mode": "rw"},
            }
            cls.container = cls.docker_client.containers.run(
                image,
                name=cls.container_name,
                detach=True,
                remove=False,
                environment={
                    "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
                    "POSTGRES_INITDB_WALDIR": "/var/lib/postgresql-wal",
                },
                volumes=volumes,
                command=postgres_container_command(),
            )
            cls.wait_for_postgres()
        except DockerException as exc:
            cls.cleanup_container()
            raise RuntimeError(f"Docker PostgreSQL smoke test setup failed: {exc}") from exc
        except Exception:
            cls.cleanup_container()
            cls.reset_mount_permissions()
            if hasattr(cls, "temp_dir"):
                cls.temp_dir.cleanup()
            if hasattr(cls, "docker_client"):
                cls.docker_client.close()
            raise

        write_docker_wrapper(cls.bin_dir / "psql", cls.container_name, "psql", cls.smoke_root)
        write_docker_wrapper(cls.bin_dir / "pgbench", cls.container_name, "pgbench", cls.smoke_root)

    @classmethod
    def tearDownClass(cls):
        cls.cleanup_container()
        cls.reset_mount_permissions()
        if hasattr(cls, "temp_dir"):
            cls.temp_dir.cleanup()
        if hasattr(cls, "docker_client"):
            cls.docker_client.close()

    @classmethod
    def cleanup_container(cls):
        container = getattr(cls, "container", None)
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass

    @classmethod
    def reset_mount_permissions(cls):
        docker_client = getattr(cls, "docker_client", None)
        if docker_client is None:
            return
        mount_paths = [
            path
            for path in (
                getattr(cls, "pgdata_parent_dir", None),
                getattr(cls, "pgwal_dir", None),
            )
            if path is not None and path.exists()
        ]
        if not mount_paths:
            return
        volumes = {str(path): {"bind": f"/mnt/{index}", "mode": "rw"} for index, path in enumerate(mount_paths)}
        targets = " ".join(shlex.quote(f"/mnt/{index}") for index in range(len(mount_paths)))
        image = os.environ.get("WORKLOAD_DOCKER_IMAGE", "postgres:18")
        try:
            docker_client.containers.run(
                image,
                command=["sh", "-c", f"chown -R {os.getuid()}:{os.getgid()} {targets}"],
                user="0",
                remove=True,
                volumes=volumes,
            )
        except DockerException:
            pass

    @classmethod
    def wait_for_postgres(cls):
        deadline = time.time() + CONTAINER_WAIT_SECONDS
        last_output = ""
        while time.time() < deadline:
            cls.container.reload()
            if cls.container.status == "exited":
                logs = cls.container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
                raise RuntimeError(f"PostgreSQL container exited early:\n{logs}")
            exit_code, output = cls.container.exec_run(["pg_isready", "-U", "postgres"])
            last_output = output.decode("utf-8", errors="replace")
            if exit_code == 0:
                return
            time.sleep(1)
        logs = cls.container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        raise RuntimeError(f"PostgreSQL did not become ready: {last_output}\n{logs}")

    def run_workload(self, args, timeout=300):
        cmd = [sys.executable, "-m", "pg_workload", *args]
        env = self.workload_env()
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            self.fail(
                "Command failed with exit code "
                f"{proc.returncode}: {shlex.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        return proc

    def workload_env(self):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["WORKLOAD_ADMIN_PASSWORD"] = POSTGRES_PASSWORD
        env["WORKLOAD_PASSWORD"] = WORKLOAD_PASSWORD
        return env

    def exec_admin_sql(self, dbname, sql):
        exit_code, output = self.container.exec_run(
            ["psql", "-U", "postgres", "-d", dbname, "-v", "ON_ERROR_STOP=1", "-Atq", "-c", sql],
            environment={"PGPASSWORD": POSTGRES_PASSWORD},
        )
        return exit_code, output.decode("utf-8", errors="replace")

    def wait_for_sql_result(self, dbname, sql, expected, timeout=45):
        deadline = time.time() + timeout
        last_output = ""
        while time.time() < deadline:
            exit_code, output = self.exec_admin_sql(dbname, sql)
            last_output = output.strip()
            if exit_code == 0 and last_output == expected:
                return
            time.sleep(1)
        self.fail(f"Timed out waiting for SQL result {expected!r}; last output: {last_output!r}")

    def assert_imdb_scripts_hit_generated_rows(self, *, root=None, dbname=WORKLOAD_DB):
        sql_dir = (root or self.smoke_root) / "data" / "imdb" / "sql"
        scripts = sorted(sql_dir.glob("[0-9][0-9]_*.sql")) + sorted(
            sql_dir.glob("select_*.sql"), key=lambda path: int(path.stem.split("_")[1])
        )
        self.assertEqual(len(scripts), 38)
        env = self.workload_env()
        env["PGPASSWORD"] = WORKLOAD_PASSWORD
        null_marker = "__PG_WORKLOAD_NULL__"

        for path in scripts:
            proc = subprocess.run(
                [
                    str(self.bin_dir / "psql"),
                    "-X",
                    "-q",
                    "-A",
                    "-t",
                    "-P",
                    f"null={null_marker}",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    "5432",
                    "-U",
                    WORKLOAD_USER,
                    "-d",
                    dbname,
                    "-f",
                    str(path),
                ],
                cwd=self.smoke_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, f"{path.name}: {proc.stderr}")
            self.assertNotIn(
                null_marker,
                proc.stdout,
                f"{path.name} did not match the generated anchor rows:\n{proc.stdout}",
            )

    def target_args(self, *, root=None, dbname=WORKLOAD_DB):
        return [
            "--root",
            str(root or self.smoke_root),
            "--target",
            "external",
            "--host",
            "127.0.0.1",
            "--port",
            "5432",
            "--admin-user",
            "postgres",
            "--database",
            dbname,
            "--user",
            WORKLOAD_USER,
            "--bin-dir",
            str(self.bin_dir),
            "--connect-timeout",
            "5",
            "--scale",
            "0.001",
            "--resource-disk-max-used-pct",
            os.environ.get("WORKLOAD_TEST_DISK_MAX_USED_PCT", "99"),
        ]

    def test_movie_profiles_batched_loading_and_repeated_runs(self):
        root = self.smoke_root / "movie_profiles"
        self.workload.initialize_project(root)
        chmod_readable(root)
        dbname = "movie_profiles_db"
        target = self.target_args(root=root, dbname=dbname)
        self.run_workload(["prepare-db", *target, "--recreate"])
        self.run_workload(["install", *target, "--profile", "pagila,imdb"], timeout=600)

        def query(sql):
            code, output = self.exec_admin_sql(dbname, sql)
            self.assertEqual(code, 0, output)
            return output.strip()

        def fingerprint():
            return query("""
                CREATE TEMP TABLE fingerprints (name text, hash text);
                DO $$ DECLARE t record; BEGIN
                    FOR t IN SELECT schemaname, tablename FROM pg_tables
                        WHERE schemaname IN ('pagila', 'imdb') LOOP
                        EXECUTE format(
                            'INSERT INTO fingerprints SELECT %L, md5(string_agg(value, '''' ORDER BY value)) '
                            'FROM (SELECT (to_jsonb(r) - ''last_update'')::text AS value FROM ONLY %I.%I r) s',
                            t.schemaname || '.' || t.tablename, t.schemaname, t.tablename);
                    END LOOP;
                END $$;
                SELECT name, hash FROM fingerprints ORDER BY name;
            """)

        before = fingerprint()
        env = self.workload_env()
        env.update(
            {
                "PGHOST": "127.0.0.1",
                "PGPORT": "5432",
                "PGDATABASE": dbname,
                "PGUSER": WORKLOAD_USER,
                "PGPASSWORD": WORKLOAD_PASSWORD,
                "PG_WORKLOAD_PSQL": str(self.bin_dir / "psql"),
            }
        )
        for profile in ("pagila", "imdb"):
            proc = subprocess.run(
                [
                    sys.executable,
                    str(root / "data" / profile / "generator.py"),
                    "--scale",
                    "0.001",
                    "--batch-rows",
                    "137",
                ],
                env=env,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=600,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(before, fingerprint(), "batch size changed generated values")
        self.assertEqual(query("SELECT count(*) FROM pg_index WHERE NOT indisvalid;"), "0")
        self.assertEqual(query("SELECT count(*) FROM pg_constraint WHERE NOT convalidated;"), "0")
        self.assertEqual(
            query("""
            SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('pagila','imdb') AND c.relkind='r' AND c.relpersistence<>'p';
        """),
            "0",
        )
        self.assertEqual(
            query("""
            SELECT avg(people)>2.9 FROM (
                SELECT count(DISTINCT person_id) AS people FROM imdb.cast_info
                WHERE movie_id>22 GROUP BY movie_id
            ) s;
        """),
            "t",
        )
        self.assertEqual(
            query("""
            SELECT count(DISTINCT info) FROM imdb.movie_info
            WHERE movie_id>22 AND info_type_id=4;
        """),
            "4",
        )
        self.assertEqual(
            query("""
            SELECT count(DISTINCT info) FROM imdb.movie_info
            WHERE movie_id>22 AND info_type_id=7;
        """),
            "4",
        )
        self.assertEqual(
            query("""
            SELECT EXISTS (SELECT 1 FROM imdb.movie_info mi JOIN imdb.cast_info ci
                ON ci.movie_id=mi.movie_id WHERE mi.movie_id>22 AND mi.info_type_id=6 AND ci.nr_order<=3);
        """),
            "t",
        )
        self.assert_imdb_scripts_hit_generated_rows(root=root, dbname=dbname)

        def pgbench(script, *, clients=2, transactions=5, protocol="simple"):
            proc = subprocess.run(
                [
                    str(self.bin_dir / "pgbench"),
                    "-n",
                    "-c",
                    str(clients),
                    "-j",
                    "2" if clients > 1 else "1",
                    "-t",
                    str(transactions),
                    "-M",
                    protocol,
                    "-f",
                    str(script),
                ],
                env=env,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("Run was aborted", proc.stderr)

        sql_dir = root / "data" / "pagila" / "sql"
        # Exercise the normally rare branches with concurrent clients, including sequence gaps.
        insert = (sql_dir / "02_insert.sql").read_text(encoding="utf-8")
        forced = sql_dir / "forced_insert.sql"
        forced.write_text(re.sub(r"(\\set chance_\w+) random\(1, 1000?\)", r"\1 1", insert), encoding="utf-8")
        query("SELECT setval('pagila.staff_staff_id_seq', 10000);")
        for protocol in ("simple", "prepared"):
            pgbench(forced, clients=16, transactions=15, protocol=protocol)
            for filename in ("01_select.sql", "02_insert.sql", "03_update.sql", "04_delete.sql"):
                pgbench(sql_dir / filename, protocol=protocol)
            self.run_workload(["run", *target, "--profile", "pagila", "--pgbench-transactions", "10"])

        query("UPDATE pagila.payment SET amount=999.99;")
        pgbench(sql_dir / "03_update.sql")
        self.assertNotEqual(query("SET search_path=pagila; SELECT get_customer_balance(1, '2022-07-20');"), "")
        query("TRUNCATE pagila.payment, pagila.rental;")
        pgbench(sql_dir / "04_delete.sql", clients=1, transactions=1)
        pgbench(sql_dir / "03_update.sql", clients=1, transactions=1)
        pgbench(sql_dir / "02_insert.sql", clients=1, transactions=1)
        self.assertEqual(query("SELECT count(*) FROM pagila.rental;"), "1")
        pgbench(sql_dir / "04_delete.sql", clients=1, transactions=1)
        self.assertEqual(query("SELECT count(*) FROM pagila.rental;"), "0")

    def test_postgres18_container_runs_all_smoke_profiles(self):
        profiles = self.workload.load_profiles(self.smoke_root)
        profile_names = sorted(profiles)
        workload_arg = ",".join(profile_names)

        self.assertGreaterEqual(len(profile_names), 11)
        self.run_workload(["validate", "--root", str(self.smoke_root)], timeout=30)
        self.run_workload(
            [
                "prepare-db",
                *self.target_args(),
                "--recreate",
            ],
            timeout=120,
        )
        self.run_workload(["install", *self.target_args(), "--profile", workload_arg], timeout=600)
        self.assert_imdb_scripts_hit_generated_rows()
        self.run_workload(
            [
                "run",
                *self.target_args(),
                "--profile",
                workload_arg,
                "--pgbench-transactions",
                "1",
                "--pgbench-clients",
                "1",
                "--pgbench-threads",
                "1",
            ],
            timeout=600,
        )

        for profile_name in profile_names:
            invariant_sql = PROFILE_INVARIANTS.get(profile_name)
            if invariant_sql is None:
                self.fail(f"No post-run invariant defined for bundled profile {profile_name}")
            exit_code, output = self.exec_admin_sql(WORKLOAD_DB, invariant_sql)
            self.assertEqual(
                (exit_code, output.strip()),
                (0, "ok"),
                f"Invariant failed for profile {profile_name}",
            )

    def test_scheduler_recovers_deleted_target_database(self):
        state_file = "state/recovery-smoke.yml"
        self.run_workload(
            [
                "prepare-db",
                *self.target_args(),
                "--recreate",
            ],
            timeout=120,
        )
        self.run_workload(["install", *self.target_args(), "--profile", "simple_stock"], timeout=120)
        self.run_workload(
            [
                "enable",
                "simple_stock",
                "--interval",
                "1",
                "--root",
                str(self.smoke_root),
                "--state-file",
                state_file,
            ],
            timeout=30,
        )

        cmd = [
            sys.executable,
            "-m",
            "pg_workload",
            "scheduler",
            *self.target_args(),
            "--profile",
            "simple_stock",
            "--state-file",
            state_file,
            "--reload-interval",
            "1",
            "--recover-interval",
            "1",
            "--stop-timeout",
            "2",
            "--run-immediately",
            "--pgbench-transactions",
            "1",
            "--pgbench-clients",
            "1",
            "--pgbench-threads",
            "1",
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=self.workload_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(3)
            terminate_sql = (
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{WORKLOAD_DB}' AND pid <> pg_backend_pid();"
            )
            exit_code, output = self.exec_admin_sql("postgres", terminate_sql)
            self.assertEqual(exit_code, 0, output)
            exit_code, output = self.exec_admin_sql("postgres", f"DROP DATABASE IF EXISTS {WORKLOAD_DB};")
            self.assertEqual(exit_code, 0, output)

            self.wait_for_sql_result(
                "postgres",
                f"SELECT 1 FROM pg_database WHERE datname = '{WORKLOAD_DB}';",
                "1",
                timeout=60,
            )
            self.wait_for_sql_result(
                WORKLOAD_DB,
                "SELECT CASE WHEN to_regclass('simple_stock.stock_items') IS NULL THEN 'missing' ELSE 'ok' END;",
                "ok",
                timeout=60,
            )
            time.sleep(2)
        finally:
            proc.terminate()
        stdout, stderr = proc.communicate(timeout=20)

        self.assertIn("Recovery finished simple_stock exit=0", stdout)
        self.assertIn("Job failed simple_stock:main", stderr)


if __name__ == "__main__":
    unittest.main()
