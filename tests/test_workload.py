import argparse
import contextlib
import dataclasses
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from pg_workload.cli import main
from pg_workload.common import load_yaml
from pg_workload.runner import query_server_version_num
from pg_workload.state import enable_profiles

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    import pg_workload

    return pg_workload


class WorkloadGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workload = load_module()

    def test_all_profile_manifests_are_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.workload.initialize_project(Path(tmpdir))
            profiles = self.workload.load_profiles(Path(tmpdir))
            self.assertGreaterEqual(len(profiles), 7)
            errors = []
            for profile in profiles.values():
                errors.extend(self.workload.validate_profile(profile))
            self.assertEqual(errors, [])
            imdb_generator = Path(tmpdir) / "data" / "imdb" / "generator.py"
            self.assertIn("g::bigint * 104729", imdb_generator.read_text(encoding="utf-8"))
            imdb = profiles["imdb"]
            imdb_scripts = [script["path"] for script in imdb.expand_scripts(imdb.job_by_name("analytical_selects"))]
            self.assertEqual(len(imdb_scripts), 38)
            self.assertEqual(
                imdb_scripts[:5],
                [
                    "sql/01_company_catalog.sql",
                    "sql/02_people_by_keyword.sql",
                    "sql/03_keyword_trends.sql",
                    "sql/04_genre_cast.sql",
                    "sql/05_join_stress.sql",
                ],
            )
            self.assertEqual(
                imdb_scripts[5:8],
                ["sql/select_1.sql", "sql/select_2.sql", "sql/select_3.sql"],
            )
            self.assertEqual(imdb_scripts[-1], "sql/select_33.sql")
            partition_generator = (Path(tmpdir) / "data" / "partition_aging" / "generator.py").read_text(
                encoding="utf-8"
            )
            self.assertIn("partition_day := current_date + day_offset", partition_generator)
            self.assertNotIn("date.today()", partition_generator)

    def test_default_pg_major_is_18(self):
        parser = self.workload.build_parser()
        args = parser.parse_args(["prepare-db", "--target=external", "--host=127.0.0.1", "--dry-run"])
        config = self.workload.build_runtime_config(args)
        self.assertEqual(config.pg_major, "18")
        self.assertEqual(str(config.bin_dir), "/usr/lib/postgresql/18/bin")

    def test_pg_version_and_user_follow_pg_diag_cli_naming(self):
        parser = self.workload.build_parser()
        args = parser.parse_args(
            [
                "prepare-db",
                "--target=external",
                "--host=127.0.0.1",
                "--pg-version=18",
                "--user=load_user",
                "--dry-run",
            ]
        )

        self.assertEqual("18", args.pg_major)
        self.assertEqual("load_user", args.workload_user)

    def test_machine_plumbing_is_hidden_from_human_help(self):
        help_text = self.workload.build_parser().format_help()

        self.assertNotIn("--machine", help_text)
        self.assertNotIn("--request-id", help_text)
        self.assertNotIn("--component-capabilities", help_text)
        self.assertIn("plan", help_text)
        self.assertIn("start", help_text)
        self.assertIn("status", help_text)
        stdout = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(stdout):
            main(["start", "--help"])
        self.assertNotIn("--enable-selected", stdout.getvalue())

    def test_machine_capabilities_use_versioned_envelope(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(
                [
                    "--machine",
                    "--request-id=workload-capabilities",
                    "--component-capabilities",
                ]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, result)
        self.assertEqual("pg_workload", payload["component"])
        self.assertEqual("workload-capabilities", payload["request_id"])
        self.assertEqual("succeeded", payload["status"])
        self.assertEqual("pg_play/capabilities/v1", payload["result"]["capability_schema_version"])
        self.assertEqual(
            "--component-capabilities",
            payload["result"]["machine_interface"]["capabilities_option"],
        )

    def test_execution_plan_is_stable_and_changes_with_profile_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.workload.initialize_project(root)

            def plan_hash(*, disk_max_used_pct: int = 90) -> str:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = main(
                        [
                            "--machine",
                            "plan",
                            "--root",
                            str(root),
                            "--target=external",
                            "--host=127.0.0.1",
                            "--operation=run",
                            "--profile=pagila",
                            f"--resource-disk-max-used-pct={disk_max_used_pct}",
                        ]
                    )
                self.assertEqual(0, result)
                return json.loads(stdout.getvalue())["result"]["plan_hash"]

            first = plan_hash()
            self.assertEqual(first, plan_hash())
            self.assertNotEqual(first, plan_hash(disk_max_used_pct=95))
            profile = root / "data" / "pagila" / "profile.yml"
            profile.write_text(
                profile.read_text(encoding="utf-8") + "\n# local experiment\n",
                encoding="utf-8",
            )
            self.assertNotEqual(first, plan_hash())

    def test_detached_scheduler_has_owned_start_status_stop_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.workload.initialize_project(root)
            stdout = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout):
                    planned_result = main(
                        [
                            "--machine",
                            "plan",
                            "--root",
                            str(root),
                            "--target=external",
                            "--host=127.0.0.1",
                            "--operation=scheduler",
                            "--profile=pagila",
                            "--enable-selected",
                            "--run-immediately",
                            "--dry-run",
                        ]
                    )
                self.assertEqual(0, planned_result)
                plan_hash = json.loads(stdout.getvalue())["result"]["plan_hash"]
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = main(
                        [
                            "--machine",
                            "start",
                            "--root",
                            str(root),
                            "--target=external",
                            "--host=127.0.0.1",
                            "--profile=pagila",
                            "--enable-selected",
                            "--run-immediately",
                            "--plan-hash",
                            plan_hash,
                            "--dry-run",
                        ]
                    )
                started = json.loads(stdout.getvalue())
                self.assertEqual(0, result)
                self.assertTrue(started["result"]["owned"])
                self.assertTrue(started["result"]["running"])
                self.assertTrue(
                    self.workload.load_state(root / "state" / "workloads.yml")["profiles"]["pagila"]["enabled"]
                )
            finally:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    stopped_result = main(["--machine", "stop", "--root", str(root), "--timeout=5"])
                self.assertEqual(0, stopped_result)
                stopped = json.loads(stdout.getvalue())["result"]
                self.assertFalse(stopped["running"])
                self.assertIsNone(stopped["stale_pid"])

    def test_package_and_cli_versions_match_project_metadata(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package = sys.modules["pg_workload"]

        self.assertEqual(package.__version__, metadata["project"]["version"])

    def test_resource_monitor_defaults_to_enabled(self):
        parser = self.workload.build_parser()
        args = parser.parse_args(["run", "--target=external", "--host=127.0.0.1", "--workload=pagila"])
        config = self.workload.build_runtime_config(args)

        self.assertTrue(config.resource_monitor_enabled)
        self.assertEqual(config.resource_disk_max_used_pct, 90)
        self.assertEqual(config.resource_mem_min_available_pct, 10)
        self.assertEqual(config.resource_mem_min_available_mb, 2048)
        self.assertEqual(config.resource_cpu_max_pct, 90)
        self.assertEqual(config.resource_cpu_window_seconds, 60)
        self.assertEqual(config.resource_check_interval, 5)

    def test_resource_guard_reports_memory_preflight_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.runtime_config_for_logs(
                tmpdir,
                resource_monitor_enabled=True,
                resource_mem_min_available_pct=100,
                resource_mem_min_available_mb=0,
                resource_disk_max_used_pct=100,
                resource_cpu_max_pct=100,
            )

            with self.assertRaisesRegex(self.workload.WorkloadError, "memory available"):
                self.workload.assert_resources_available(config, "starting test")

    def test_resource_guard_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.runtime_config_for_logs(
                tmpdir,
                resource_monitor_enabled=False,
                resource_mem_min_available_pct=100,
                resource_mem_min_available_mb=0,
                resource_disk_max_used_pct=0,
                resource_cpu_max_pct=0,
            )

            self.workload.assert_resources_available(config, "starting test")

    def test_resource_guard_uses_loadavg_until_cpu_window_is_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.runtime_config_for_logs(
                tmpdir,
                resource_monitor_enabled=True,
                resource_mem_min_available_pct=0,
                resource_mem_min_available_mb=0,
                resource_disk_max_used_pct=100,
                resource_cpu_max_pct=10,
                resource_cpu_window_seconds=60,
            )
            guard = self.workload.ResourceGuard(config)
            samples = [
                self.workload.CpuSample(timestamp=100.0, total=1000, idle=900),
                self.workload.CpuSample(timestamp=101.0, total=1100, idle=990),
            ]
            resources_module = sys.modules["pg_workload.resources"]

            with (
                mock.patch.object(resources_module, "read_cpu_sample", side_effect=samples),
                mock.patch.object(resources_module.os, "getloadavg", return_value=(1.0, 1.0, 1.0)),
                mock.patch.object(resources_module.os, "cpu_count", return_value=1),
            ):
                guard.issues(use_loadavg_fallback=True)
                issues = guard.issues(use_loadavg_fallback=True)

            self.assertTrue(any(issue.kind == "cpu" for issue in issues))

    def test_install_checks_resources_before_running_generator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "generated_profile",
                    "prepare": {"steps": [{"type": "generator", "path": "generator.py"}]},
                    "jobs": [{"name": "main", "type": "psql", "interval": 60, "command": "SELECT 1"}],
                },
            )
            config = self.runtime_config_for_logs(
                tmpdir,
                resource_monitor_enabled=True,
                resource_mem_min_available_pct=100,
                resource_mem_min_available_mb=0,
                resource_disk_max_used_pct=100,
                resource_cpu_max_pct=100,
            )
            client = self.workload.PgClient(config)

            with self.assertRaisesRegex(self.workload.WorkloadError, "installing profile generated_profile"):
                self.workload.install_profiles(client, config, [profile])

    def test_patroni_requires_url(self):
        parser = self.workload.build_parser()
        args = parser.parse_args(["prepare-db", "--target=patroni", "--dry-run"])
        with self.assertRaises(self.workload.WorkloadError):
            self.workload.build_runtime_config(args)

    def test_pgbench_scripts_are_auto_discovered_in_natural_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.workload.initialize_project(Path(tmpdir))
            profiles = self.workload.load_profiles(Path(tmpdir))
            pagila_scripts = [
                script["path"] for script in profiles["pagila"].expand_scripts(profiles["pagila"].job_by_name("main"))
            ]
            imdb_scripts = [
                script["path"]
                for script in profiles["imdb"].expand_scripts(profiles["imdb"].job_by_name("analytical_selects"))
            ]

            self.assertEqual(
                pagila_scripts,
                [
                    "sql/01_select.sql",
                    "sql/02_insert.sql",
                    "sql/03_update.sql",
                    "sql/04_delete.sql",
                ],
            )
            self.assertEqual(
                imdb_scripts[:2],
                ["sql/01_company_catalog.sql", "sql/02_people_by_keyword.sql"],
            )
            self.assertEqual(
                imdb_scripts[5:8],
                ["sql/select_1.sql", "sql/select_2.sql", "sql/select_3.sql"],
            )
            self.assertEqual(imdb_scripts[14], "sql/select_10.sql")

    def test_imdb_profile_restores_full_schema_and_index_coverage(self):
        profile_root = self.workload.bundled_profiles_root() / "imdb"
        schema = (profile_root / "sql" / "imdb-schema.sql").read_text(encoding="utf-8")
        indexes = (profile_root / "sql" / "imdb-fkindexes.sql").read_text(encoding="utf-8")
        expected_tables = {
            "aka_name",
            "aka_title",
            "cast_info",
            "char_name",
            "comp_cast_type",
            "company_name",
            "company_type",
            "complete_cast",
            "info_type",
            "keyword",
            "kind_type",
            "link_type",
            "movie_companies",
            "movie_info",
            "movie_info_idx",
            "movie_keyword",
            "movie_link",
            "name",
            "person_info",
            "role_type",
            "title",
        }

        created_tables = set(re.findall(r"CREATE TABLE ([a-z_]+)", schema))
        self.assertEqual(created_tables, expected_tables)
        for table in expected_tables:
            self.assertIn(f"analyze {table};", indexes.lower())

        scripts = list((profile_root / "sql").glob("[0-9][0-9]_*.sql"))
        scripts.extend((profile_root / "sql").glob("select_*.sql"))
        select_variants = sum(
            len(re.findall(r"^SELECT ", path.read_text(encoding="utf-8"), flags=re.MULTILINE)) for path in scripts
        )
        self.assertEqual(select_variants, 113)

    def test_pgbench_job_transactions_override_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sql").mkdir()
            (root / "sql" / "01_workload.sql").write_text("SELECT 1;\n", encoding="utf-8")
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "tx_profile",
                    "jobs": [
                        {
                            "name": "main",
                            "type": "pgbench",
                            "clients": 2,
                            "threads": 1,
                            "duration": 9,
                            "transactions": 5,
                        }
                    ],
                },
            )
            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir, dry_run=True, verbose=True))
            captured = io.StringIO()

            with contextlib.redirect_stdout(captured):
                client.run_pgbench(profile, profile.job_by_name("main"), root / "log" / "main.log")

            output = captured.getvalue()
            self.assertIn("-c 2", output)
            self.assertIn("-j 1", output)
            self.assertIn("-t 5", output)
            self.assertNotIn("-T 9", output)

    def test_pgbench_cli_duration_overrides_profile_transactions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sql").mkdir()
            (root / "sql" / "01_workload.sql").write_text("SELECT 1;\n", encoding="utf-8")
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "tx_profile",
                    "jobs": [
                        {
                            "name": "main",
                            "type": "pgbench",
                            "clients": 2,
                            "threads": 1,
                            "transactions": 5,
                        }
                    ],
                },
            )
            config = self.runtime_config_for_logs(tmpdir, dry_run=True, verbose=True)
            config.pgbench_duration = 7
            client = self.workload.PgClient(config)
            captured = io.StringIO()

            with contextlib.redirect_stdout(captured):
                client.run_pgbench(profile, profile.job_by_name("main"), root / "log" / "main.log")

            output = captured.getvalue()
            self.assertIn("-T 7", output)
            self.assertNotIn("-t 5", output)

    def test_pgbench_cli_transactions_override_profile_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sql").mkdir()
            (root / "sql" / "01_workload.sql").write_text("SELECT 1;\n", encoding="utf-8")
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "dur_profile",
                    "jobs": [
                        {
                            "name": "main",
                            "type": "pgbench",
                            "clients": 2,
                            "threads": 1,
                            "duration": 9,
                        }
                    ],
                },
            )
            config = self.runtime_config_for_logs(tmpdir, dry_run=True, verbose=True)
            config.pgbench_transactions = 4
            client = self.workload.PgClient(config)
            captured = io.StringIO()

            with contextlib.redirect_stdout(captured):
                client.run_pgbench(profile, profile.job_by_name("main"), root / "log" / "main.log")

            output = captured.getvalue()
            self.assertIn("-t 4", output)
            self.assertNotIn("-T 9", output)

    def test_pgbench_job_defaults_to_two_clients_and_two_threads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sql").mkdir()
            (root / "sql" / "01_workload.sql").write_text("SELECT 1;\n", encoding="utf-8")
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "default_profile",
                    "jobs": [
                        {
                            "name": "main",
                            "type": "pgbench",
                            "duration": 1,
                        }
                    ],
                },
            )
            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir, dry_run=True, verbose=True))
            captured = io.StringIO()

            with contextlib.redirect_stdout(captured):
                client.run_pgbench(profile, profile.job_by_name("main"), root / "log" / "main.log")

            output = captured.getvalue()
            self.assertIn("-c 2", output)
            self.assertIn("-j 2", output)

    def runtime_config_for_logs(
        self,
        root,
        *,
        max_bytes=1024 * 1024,
        rotate_on_start=True,
        dry_run=False,
        verbose=False,
        resource_monitor_enabled=False,
        resource_disk_max_used_pct=100,
        resource_mem_min_available_pct=0,
        resource_mem_min_available_mb=0,
        resource_cpu_max_pct=100,
        resource_cpu_window_seconds=60,
        resource_check_interval=5,
    ):
        return self.workload.RuntimeConfig(
            root=Path(root),
            target="external",
            pg_major="18",
            bin_dir=None,
            host="127.0.0.1",
            port=5432,
            dbname="workload_db",
            workload_user="workload_user",
            workload_password="test-only-workload-secret",
            passfile=None,
            admin_db="postgres",
            admin_user="postgres",
            admin_password=None,
            patroni_urls=[],
            patroni_role="master",
            connect_timeout=5,
            sslmode=None,
            pgbench_clients=None,
            pgbench_threads=None,
            pgbench_duration=None,
            pgbench_transactions=None,
            scale=1.0,
            libpq_workload_settings=True,
            log_max_bytes=max_bytes,
            log_backups=3,
            log_rotate_on_start=rotate_on_start,
            dry_run=dry_run,
            verbose=verbose,
            resource_monitor_enabled=resource_monitor_enabled,
            resource_disk_max_used_pct=resource_disk_max_used_pct,
            resource_mem_min_available_pct=resource_mem_min_available_pct,
            resource_mem_min_available_mb=resource_mem_min_available_mb,
            resource_cpu_max_pct=resource_cpu_max_pct,
            resource_cpu_window_seconds=resource_cpu_window_seconds,
            resource_check_interval=resource_check_interval,
        )

    def test_profile_job_log_rotates_on_new_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "data" / "pss_overflow" / "log" / "job.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text("old run\n", encoding="utf-8")

            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir))
            client.run(
                [sys.executable, "-c", "print('new run')"],
                env=os.environ.copy(),
                log_path=log_path,
            )

            self.assertIn("new run", log_path.read_text(encoding="utf-8"))
            rotated_log = log_path.with_name(log_path.name + ".1")
            self.assertTrue(rotated_log.exists())
            self.assertIn("old run", rotated_log.read_text(encoding="utf-8"))

    def test_profile_job_log_rotates_when_size_limit_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "data" / "pss_overflow" / "log" / "job.log"
            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir, max_bytes=512, rotate_on_start=False))
            client.run(
                [sys.executable, "-c", "for _ in range(30): print('x' * 80)"],
                env=os.environ.copy(),
                log_path=log_path,
            )

            self.assertTrue(log_path.exists())
            rotated_logs = sorted(log_path.parent.glob("job.log.*"))
            self.assertTrue(rotated_logs)

    def test_logged_commands_and_output_redact_passwords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "data" / "pss_overflow" / "log" / "job.log"
            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir))
            secret = client.config.workload_password

            client.run(
                [sys.executable, "-c", f"print({secret!r})"],
                env=os.environ.copy(),
                log_path=log_path,
            )

            log_text = log_path.read_text(encoding="utf-8")
            self.assertNotIn(secret, log_text)
            self.assertIn("***", log_text)

    def test_psql_command_input_does_not_expose_sql_or_workload_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir, dry_run=True, verbose=True))
            secret = client.config.workload_password
            captured = io.StringIO()

            with contextlib.redirect_stdout(captured):
                client.run_psql(
                    "postgres",
                    "postgres",
                    None,
                    command=f"ALTER ROLE x PASSWORD '{secret}';",
                )

            output = captured.getvalue()
            self.assertNotIn(secret, output)
            self.assertNotIn("ALTER ROLE", output)
            self.assertNotIn("workload_password", " ".join(client.psql_variable_args()))

    def test_libpq_workload_settings_can_be_disabled_for_pgbouncer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = dataclasses.replace(
                self.runtime_config_for_logs(tmpdir),
                libpq_workload_settings=False,
            )
            client = self.workload.PgClient(config)

            env = client.env(config.workload_password)

            self.assertNotIn("PGOPTIONS", env)

    def test_allow_failure_suppresses_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir))
            with self.assertRaises(self.workload.WorkloadError):
                client.run([sys.executable, "-c", "raise SystemExit(3)"], env=os.environ.copy())
            with contextlib.redirect_stderr(io.StringIO()):
                client.run(
                    [sys.executable, "-c", "raise SystemExit(3)"],
                    env=os.environ.copy(),
                    allow_failure=True,
                )

    def test_machine_mode_routes_child_stdout_away_from_protocol_stdout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = dataclasses.replace(
                self.runtime_config_for_logs(tmpdir),
                machine_output=True,
            )
            client = self.workload.PgClient(config)
            completed = subprocess.CompletedProcess(["child"], 0)

            with mock.patch("pg_workload.pg_client.subprocess.run", return_value=completed) as run:
                client.run(["child"], env=os.environ.copy())

            self.assertIs(run.call_args.kwargs["stdout"], sys.stderr)

    def test_validate_rejects_invalid_profile_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = self.workload.Profile(
                Path(tmpdir),
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "bad_profile",
                    "jobs": [
                        {
                            "name": "bad_job",
                            "type": "unknown",
                            "interval": 0,
                            "log": "../outside.log",
                            "recover_on_failure": "false",
                        }
                    ],
                },
            )

            errors = self.workload.validate_profile(profile)
            self.assertTrue(any("unsupported job type" in error for error in errors))
            self.assertTrue(any("interval must be greater than zero" in error for error in errors))
            self.assertTrue(any("unsafe log path" in error for error in errors))
            self.assertTrue(any("recover_on_failure must be a boolean" in error for error in errors))

    def test_validate_requires_version_name_jobs_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = self.workload.Profile(
                Path(tmpdir),
                {"api_version": "wrong/v1", "unexpected": True},
            )

            errors = self.workload.validate_profile(profile)

            self.assertTrue(any("unknown field unexpected" in error for error in errors))
            self.assertTrue(any("api_version must be pg_workload/v1" in error for error in errors))
            self.assertTrue(any("name is required" in error for error in errors))
            self.assertTrue(any("jobs is required" in error for error in errors))

    def test_validate_rejects_mutually_exclusive_pgbench_limits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sql").mkdir()
            (root / "sql" / "01.sql").write_text("SELECT 1;\n", encoding="utf-8")
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "bad_limits",
                    "jobs": [
                        {
                            "name": "main",
                            "type": "pgbench",
                            "interval": 1,
                            "duration": 1,
                            "transactions": 1,
                            "scripts": ["sql/01.sql"],
                        }
                    ],
                },
            )

            errors = self.workload.validate_profile(profile)

            self.assertTrue(any("exactly one of duration or transactions" in error for error in errors))

    def test_empty_project_is_not_a_valid_profile_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(self.workload.WorkloadError, "No workload profiles"):
                self.workload.load_profiles(Path(tmpdir))

    def test_init_is_idempotent_and_protects_modified_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = self.workload.initialize_project(root)
            second = self.workload.initialize_project(root)
            self.assertGreater(first["assets"]["created"], 0)
            self.assertGreater(second["assets"]["unchanged"], 0)
            self.assertTrue((root / "schema" / "pg_workload-v1.schema.json").is_file())
            manifest = root / "data" / "simple_stock" / "profile.yml"
            manifest.write_text(manifest.read_text(encoding="utf-8") + "# local edit\n", encoding="utf-8")
            with self.assertRaisesRegex(self.workload.WorkloadError, "differs"):
                self.workload.initialize_project(root)
            self.workload.initialize_project(root, force=True)

    def test_validate_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "profile"
            outside = Path(tmpdir) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "01.sql").write_text("SELECT 1;\n", encoding="utf-8")
            (root / "sql").symlink_to(outside, target_is_directory=True)
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "escape",
                    "jobs": [
                        {
                            "name": "main",
                            "type": "pgbench",
                            "interval": 1,
                            "transactions": 1,
                            "scripts": ["sql/01.sql"],
                        }
                    ],
                },
            )

            errors = self.workload.validate_profile(profile)

            self.assertTrue(any("must stay inside the profile" in error for error in errors))

    def test_validate_rejects_log_directory_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "profile"
            outside = Path(tmpdir) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "log").symlink_to(outside, target_is_directory=True)
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "escape_log",
                    "jobs": [
                        {
                            "name": "main",
                            "type": "psql",
                            "interval": 1,
                            "command": "SELECT 1",
                            "log": "main.log",
                        }
                    ],
                },
            )

            errors = self.workload.validate_profile(profile)

            self.assertTrue(any("unsafe log path" in error for error in errors))

    def test_init_and_profile_loading_reject_data_directory_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            outside = Path(tmpdir) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "data").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(self.workload.WorkloadError, "symlink"):
                self.workload.initialize_project(root)
            with self.assertRaisesRegex(self.workload.WorkloadError, "symlink"):
                self.workload.load_profiles(root)

    def test_cli_rejects_state_path_outside_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                result = main(["state", "--root", tmpdir, "--state-file", "../outside.yml"])

            self.assertEqual(result, 1)
            self.assertIn("must stay inside", stderr.getvalue())

    def test_pgoptions_never_contains_workload_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir))
            env = client.env(client.config.workload_password)

            self.assertNotIn(client.config.workload_password, env.get("PGOPTIONS", ""))

    def test_child_environment_does_not_inherit_named_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self.workload.PgClient(self.runtime_config_for_logs(tmpdir))
            with mock.patch.dict(
                os.environ,
                {
                    "WORKLOAD_PASSWORD": "inherited-workload-secret",
                    "WORKLOAD_ADMIN_PASSWORD": "inherited-admin-secret",
                },
            ):
                env = client.env(client.config.workload_password)

            self.assertNotIn("WORKLOAD_PASSWORD", env)
            self.assertNotIn("WORKLOAD_ADMIN_PASSWORD", env)
            self.assertEqual(env["PGPASSWORD"], client.config.workload_password)
            self.assertIn("workload.dbname", env["PGOPTIONS"])

    def test_existing_role_password_is_unchanged_without_rotation_flag(self):
        class FakeClient:
            def __init__(self):
                self.commands = []

            def query_scalar(self, dbname, user, password, sql):
                if "pg_roles" in sql or "pg_database" in sql:
                    return "1"
                return "auto_explain,pg_stat_statements"

            def run_psql(self, dbname, user, password, *, command, **kwargs):
                self.commands.append(command)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.runtime_config_for_logs(tmpdir)
            args = argparse.Namespace(
                recreate=False,
                workload_superuser=False,
                rotate_workload_password=False,
                extensions=["pg_stat_statements"],
                preload_libraries=["auto_explain,pg_stat_statements"],
            )
            client = FakeClient()

            self.workload.prepare_database(client, config, args)

            self.assertFalse(any("ALTER ROLE" in command for command in client.commands))
            self.assertFalse(any(config.workload_password in command for command in client.commands))

    def test_prepare_database_installs_default_diagnostic_extensions(self):
        class FakeClient:
            def __init__(self):
                self.commands = []

            def query_scalar(self, dbname, user, password, sql):
                if "pg_roles" in sql or "pg_database" in sql:
                    return "1"
                if "pg_available_extensions" in sql:
                    return "1"
                return "auto_explain,pg_stat_statements"

            def run_psql(self, dbname, user, password, *, command, **kwargs):
                self.commands.append(command)

        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeClient()
            self.workload.prepare_database(
                client,
                self.runtime_config_for_logs(tmpdir),
                argparse.Namespace(
                    recreate=False,
                    workload_superuser=False,
                    rotate_workload_password=False,
                    extensions=None,
                    preload_libraries=None,
                ),
            )

            self.assertIn('CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";', client.commands)
            self.assertIn('CREATE EXTENSION IF NOT EXISTS "pg_buffercache";', client.commands)
            self.assertIn('CREATE EXTENSION IF NOT EXISTS "pg_stat_kcache";', client.commands)
            self.assertIn('CREATE EXTENSION IF NOT EXISTS "pg_wait_sampling";', client.commands)

    def test_job_recover_on_failure_defaults_to_true(self):
        self.assertTrue(self.workload.job_recover_on_failure({}))
        self.assertTrue(self.workload.job_recover_on_failure({"recover_on_failure": True}))
        self.assertFalse(self.workload.job_recover_on_failure({"recover_on_failure": False}))

    def test_legacy_archive_contract_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "legacy",
                    "prepare": {"data": [{"type": "tar", "archive": "data.tar.gz"}]},
                    "jobs": [{"name": "main", "type": "psql", "interval": 60, "command": "SELECT 1"}],
                },
            )

            errors = self.workload.validate_profile(profile)

            self.assertTrue(any("unknown field data" in error for error in errors))

    def test_generator_step_requires_existing_python_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sql").mkdir()
            (root / "sql" / "01_workload.sql").write_text("SELECT 1;\n", encoding="utf-8")
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "missing_generator",
                    "prepare": {"steps": [{"type": "generator", "path": "generator.py"}]},
                    "jobs": [
                        {
                            "name": "main",
                            "type": "pgbench",
                            "interval": 60,
                            "transactions": 1,
                        }
                    ],
                },
            )

            errors = self.workload.validate_profile(profile)

            self.assertTrue(any("missing generator file" in error for error in errors))

    def test_install_runs_ordered_steps_and_passes_scale_to_generator(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def run_psql(self, dbname, user, password, *, command=None, file_path=None, **kwargs):
                self.calls.append(("sql", command or file_path.name))

            def run_generator(self, file_path, *, cwd, scale):
                self.calls.append(("generator", file_path.name, scale))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sql").mkdir()
            (root / "sql" / "schema.sql").write_text("SELECT 1;\n", encoding="utf-8")
            (root / "sql" / "indexes.sql").write_text("SELECT 2;\n", encoding="utf-8")
            (root / "generator.py").write_text("print('generator')\n", encoding="utf-8")
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "ordered",
                    "prepare": {
                        "steps": [
                            {"type": "sql", "path": "sql/schema.sql"},
                            {"type": "generator", "path": "generator.py"},
                            {"type": "sql", "path": "sql/indexes.sql"},
                        ]
                    },
                    "jobs": [{"name": "main", "type": "psql", "interval": 60, "command": "SELECT 1"}],
                },
            )
            config = dataclasses.replace(self.runtime_config_for_logs(tmpdir), scale=0.25)
            client = FakeClient()

            errors = self.workload.validate_profile(profile)
            self.assertEqual(errors, [])
            self.workload.install_profiles(client, config, [profile])
            self.assertEqual(
                client.calls,
                [("sql", "schema.sql"), ("generator", "generator.py", 0.25), ("sql", "indexes.sql")],
            )

    def test_install_scales_repeatable_sql_steps_without_reaching_zero(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def run_psql(self, dbname, user, password, *, file_path=None, **kwargs):
                self.calls.append(file_path.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "schema.sql").write_text("SELECT 1;\n", encoding="utf-8")
            profile = self.workload.Profile(
                root,
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "scaled-repeat",
                    "prepare": {
                        "steps": [
                            {
                                "type": "sql",
                                "path": "schema.sql",
                                "repeat": 25,
                                "scale_repeat": True,
                            }
                        ]
                    },
                    "jobs": [{"name": "main", "type": "psql", "interval": 60, "command": "SELECT 1"}],
                },
            )
            client = FakeClient()

            self.workload.install_profiles(
                client,
                dataclasses.replace(self.runtime_config_for_logs(tmpdir), scale=0.05),
                [profile],
            )

            self.assertEqual(client.calls, ["schema.sql"])

    def test_bundled_profiles_contain_no_data_archives_or_csv(self):
        forbidden_suffixes = (".csv", ".csv.gz", ".tar", ".tar.gz", ".zip")
        forbidden = [
            path
            for path in self.workload.bundled_profiles_root().rglob("*")
            if path.is_file() and (path.name.endswith(forbidden_suffixes) or "insert-data" in path.name)
        ]

        self.assertEqual(forbidden, [])

    def test_many_objects_indexes_are_compatible_with_postgresql_10(self):
        sql = (self.workload.bundled_profiles_root() / "many_objects" / "sql" / "prepare_schema_02.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("server_version_num')::integer >= 110000", sql)
        self.assertIn("server_version_num')::integer < 110000", sql)
        self.assertIn("\\gexec", sql)

    def test_pagila_schema_avoids_postgresql_12_only_table_access_setting(self):
        sql = (self.workload.bundled_profiles_root() / "pagila" / "sql" / "pagila-schema.sql").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("default_table_access_method", sql)
        self.assertNotIn("EXECUTE FUNCTION", sql)
        self.assertIn("EXECUTE PROCEDURE", sql)

    def test_profile_preload_requirement_is_fatal(self):
        class FakeClient:
            def query_scalar(self, dbname, user, password, sql):
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.runtime_config_for_logs(tmpdir)
            profile = self.workload.Profile(
                Path(tmpdir),
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "pss_overflow",
                    "requires_preload_libraries": ["pg_stat_statements"],
                },
            )

            with self.assertRaisesRegex(self.workload.WorkloadError, "pg_stat_statements"):
                self.workload.check_profile_requirements(FakeClient(), config, profile)

    def create_minimal_profile(self, root, name, *, jobs=None):
        profile_dir = Path(root) / "data" / name
        sql_dir = profile_dir / "sql"
        sql_dir.mkdir(parents=True)
        (sql_dir / "01_workload.sql").write_text("SELECT 1;\n", encoding="utf-8")
        profile_jobs = jobs or [
            {
                "name": "main",
                "type": "pgbench",
                "interval": 60,
                "log": "main.log",
            }
        ]
        for job in profile_jobs:
            if job.get("type") == "pgbench" and "duration" not in job and "transactions" not in job:
                job["transactions"] = 1
        data = {
            "api_version": self.workload.API_VERSION,
            "name": name,
            "jobs": profile_jobs,
        }
        self.workload.save_yaml(profile_dir / "profile.yml", data)

    def test_desired_state_scheduler_flow_supports_dynamic_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            state_path = root / "state" / "workloads.yml"
            self.create_minimal_profile(
                root,
                "alpha",
                jobs=[
                    {"name": "read", "type": "pgbench", "interval": 60, "log": "read.log"},
                    {"name": "write", "type": "pgbench", "interval": 60, "log": "write.log"},
                ],
            )

            profiles = self.workload.load_profiles(root)
            self.assertEqual(self.workload.effective_schedule(profiles, None, {"profiles": {}}), [])

            self.workload.update_job_state(state_path, "alpha", job_name="read", enabled=True, interval=7)
            state = self.workload.load_state(state_path)
            schedule = self.workload.effective_schedule(profiles, None, state)
            self.assertEqual(
                [(profile.name, job["name"], interval) for profile, job, interval in schedule], [("alpha", "read", 7)]
            )

            self.create_minimal_profile(root, "beta")
            self.workload.update_job_state(state_path, "beta", job_name="main", enabled=True, interval=11)
            profiles = self.workload.load_profiles(root)
            schedule = self.workload.effective_schedule(profiles, None, self.workload.load_state(state_path))
            self.assertEqual(
                [(profile.name, job["name"], interval) for profile, job, interval in schedule],
                [("alpha", "read", 7), ("beta", "main", 11)],
            )

            self.workload.update_job_state(state_path, "alpha", job_name="read", enabled=False)
            schedule = self.workload.effective_schedule(profiles, None, self.workload.load_state(state_path))
            self.assertEqual(
                [(profile.name, job["name"], interval) for profile, job, interval in schedule], [("beta", "main", 11)]
            )

            scoped = self.workload.effective_schedule(profiles, ["alpha"], self.workload.load_state(state_path))
            self.assertEqual(scoped, [])

    def test_profile_level_enable_schedules_all_jobs_and_job_disable_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            state_path = root / "state" / "workloads.yml"
            self.create_minimal_profile(
                root,
                "alpha",
                jobs=[
                    {"name": "read", "type": "pgbench", "interval": 60, "log": "read.log"},
                    {"name": "write", "type": "pgbench", "interval": 60, "log": "write.log"},
                ],
            )
            profiles = self.workload.load_profiles(root)

            self.workload.update_job_state(state_path, "alpha", enabled=True, interval=13)
            schedule = self.workload.effective_schedule(profiles, None, self.workload.load_state(state_path))
            self.assertEqual(
                [(profile.name, job["name"], interval) for profile, job, interval in schedule],
                [("alpha", "read", 13), ("alpha", "write", 13)],
            )

            self.workload.update_job_state(state_path, "alpha", job_name="write", enabled=False)
            schedule = self.workload.effective_schedule(profiles, None, self.workload.load_state(state_path))
            self.assertEqual(
                [(profile.name, job["name"], interval) for profile, job, interval in schedule],
                [("alpha", "read", 13)],
            )

    def test_enable_profiles_can_apply_one_reviewed_interval_to_every_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            state_path = root / "state" / "workloads.yml"
            self.create_minimal_profile(
                root,
                "alpha",
                jobs=[
                    {"name": "read", "type": "pgbench", "interval": 60, "log": "read.log"},
                    {"name": "write", "type": "pgbench", "interval": 600, "log": "write.log"},
                ],
            )

            enable_profiles(
                state_path,
                ["alpha"],
                interval_seconds=5,
            )
            schedule = self.workload.effective_schedule(
                self.workload.load_profiles(root),
                None,
                self.workload.load_state(state_path),
            )

            self.assertEqual(
                [(profile.name, job["name"], interval) for profile, job, interval in schedule],
                [("alpha", "read", 5), ("alpha", "write", 5)],
            )

    def test_effective_schedule_skips_invalid_state_interval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            self.create_minimal_profile(root, "alpha")
            profiles = self.workload.load_profiles(root)
            state = {"profiles": {"alpha": {"jobs": {"main": {"enabled": True, "interval": 0}}}}}

            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                schedule = self.workload.effective_schedule(profiles, None, state)

            self.assertEqual(schedule, [])
            self.assertIn("interval must be greater than zero", stderr.getvalue())

    def test_control_target_validation_rejects_unknown_enable_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            self.create_minimal_profile(root, "alpha")

            with self.assertRaisesRegex(self.workload.WorkloadError, "Unknown profile"):
                self.workload.validate_control_target(root, "missing", None, strict=True)
            with self.assertRaisesRegex(self.workload.WorkloadError, "has no job"):
                self.workload.validate_control_target(root, "alpha", "missing", strict=True)

            self.workload.validate_control_target(root, "missing", None, strict=False)

    def test_cli_rejects_non_positive_scheduler_interval(self):
        parser = self.workload.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["scheduler", "--reload-interval=0"])
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["start", "--job-interval-seconds=0"])

    def test_cli_rejects_non_finite_scale(self):
        parser = self.workload.build_parser()
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["install", "--profile", "simple_stock", "--scale", value])

    def test_scheduler_singleton_lock_rejects_second_holder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "state" / "scheduler.lock"
            with self.workload.file_lock(lock_path, nonblocking=True):
                with self.assertRaisesRegex(self.workload.WorkloadError, "Lock is already held"):
                    with self.workload.file_lock(lock_path, nonblocking=True):
                        pass

    def test_running_scheduler_stops_disabled_job_process(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            bin_dir = root / "bin"
            bin_dir.mkdir()
            marker = root / "job.started"
            pgbench = bin_dir / "pgbench"
            pgbench.write_text(
                '#!/bin/sh\ntouch "$SLOW_MARKER"\nsleep 30\n',
                encoding="utf-8",
            )
            pgbench.chmod(0o755)
            self.create_minimal_profile(root, "slow")
            state_path = root / "state" / "workloads.yml"
            self.workload.update_job_state(state_path, "slow", job_name="main", enabled=True, interval=1)

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["SLOW_MARKER"] = str(marker)
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "pg_workload",
                    "scheduler",
                    "--root",
                    str(root),
                    "--target=external",
                    "--host=127.0.0.1",
                    "--port=5432",
                    "--bin-dir",
                    str(bin_dir),
                    "--reload-interval=0.1",
                    "--run-immediately",
                    "--no-recover-on-failure",
                    "--stop-timeout=1",
                    "--no-resource-monitor",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.time() + 10
                while time.time() < deadline and not marker.exists():
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                self.assertTrue(marker.exists(), "scheduler did not start the fake pgbench job")

                self.workload.update_job_state(state_path, "slow", job_name="main", enabled=False)
                time.sleep(0.5)
            finally:
                proc.terminate()
            stdout, stderr = proc.communicate(timeout=10)

            self.assertIn("Started job slow:main", stdout)
            self.assertIn("Terminating job slow:main: job disabled", stderr)

    def test_running_scheduler_picks_up_new_profile_from_state_without_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "pg_workload",
                    "scheduler",
                    "--root",
                    str(root),
                    "--target=external",
                    "--host=127.0.0.1",
                    "--port=5432",
                    "--dry-run",
                    "--reload-interval=0.1",
                    "--run-immediately",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                time.sleep(0.2)
                self.create_minimal_profile(root, "dynamic_profile")
                self.workload.update_job_state(
                    root / "state" / "workloads.yml",
                    "dynamic_profile",
                    job_name="main",
                    enabled=True,
                    interval=60,
                )
                time.sleep(0.5)
            finally:
                proc.terminate()
            stdout, stderr = proc.communicate(timeout=10)

            self.assertIn("Scheduler started.", stdout)
            self.assertIn("Running dynamic_profile:main", stdout)
            self.assertIn("pgbench", stdout)
            self.assertIn("Received signal", stderr)

    def test_scheduler_skips_recovery_when_job_disables_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            bin_dir = root / "bin"
            bin_dir.mkdir()
            job_marker = root / "job.started"
            recovery_marker = root / "recovery.started"

            pgbench = bin_dir / "pgbench"
            pgbench.write_text(
                '#!/bin/sh\ntouch "$JOB_MARKER"\nexit 2\n',
                encoding="utf-8",
            )
            pgbench.chmod(0o755)

            psql = bin_dir / "psql"
            psql.write_text(
                '#!/bin/sh\ntouch "$RECOVERY_MARKER"\nexit 0\n',
                encoding="utf-8",
            )
            psql.chmod(0o755)

            self.create_minimal_profile(
                root,
                "expected_failure",
                jobs=[
                    {
                        "name": "main",
                        "type": "pgbench",
                        "interval": 1,
                        "log": "main.log",
                        "recover_on_failure": False,
                    }
                ],
            )
            state_path = root / "state" / "workloads.yml"
            self.workload.update_job_state(
                state_path,
                "expected_failure",
                job_name="main",
                enabled=True,
                interval=1,
            )

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["JOB_MARKER"] = str(job_marker)
            env["RECOVERY_MARKER"] = str(recovery_marker)
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "pg_workload",
                    "scheduler",
                    "--root",
                    str(root),
                    "--target=external",
                    "--host=127.0.0.1",
                    "--port=5432",
                    "--bin-dir",
                    str(bin_dir),
                    "--reload-interval=0.1",
                    "--run-immediately",
                    "--recover-interval=1",
                    "--stop-timeout=1",
                    "--no-resource-monitor",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.time() + 10
                while time.time() < deadline and not job_marker.exists():
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                self.assertTrue(job_marker.exists(), "scheduler did not start the fake pgbench job")
                time.sleep(0.5)
            finally:
                proc.terminate()
            stdout, stderr = proc.communicate(timeout=10)

            self.assertIn("Started job expected_failure:main", stdout)
            self.assertIn("Job failed expected_failure:main", stderr)
            self.assertIn("Recovery skipped for expected_failure:main: recover_on_failure=false", stderr)
            self.assertFalse(recovery_marker.exists(), "scheduler unexpectedly started recovery")


class MinPgVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workload = load_module()

    def _profile(self, tmpdir, min_pg_version):
        return self.workload.Profile(
            Path(tmpdir),
            {
                "api_version": self.workload.API_VERSION,
                "name": "versioned",
                "min_pg_version": min_pg_version,
                "jobs": [
                    {
                        "name": "main",
                        "type": "psql",
                        "interval": 60,
                        "command": "SELECT 1;",
                    }
                ],
            },
        )

    def test_validate_rejects_invalid_min_pg_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for invalid in ("12", 9, True, 12.5):
                profile = self._profile(tmpdir, invalid)
                errors = self.workload.validate_profile(profile)
                self.assertTrue(
                    any("min_pg_version" in error for error in errors),
                    f"min_pg_version={invalid!r} was not rejected",
                )

    def test_validate_accepts_min_pg_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = self._profile(tmpdir, 12)
            self.assertEqual(self.workload.validate_profile(profile), [])

    def test_check_min_pg_version_raises_for_old_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = self._profile(tmpdir, 12)
            with self.assertRaisesRegex(self.workload.WorkloadError, "requires PostgreSQL >= 12"):
                self.workload.check_min_pg_version(profile, 100000)
            self.workload.check_min_pg_version(profile, 120000)
            self.workload.check_min_pg_version(profile, 180000)

    def test_check_min_pg_version_is_optional(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = self.workload.Profile(
                Path(tmpdir),
                {
                    "api_version": self.workload.API_VERSION,
                    "name": "unversioned",
                    "jobs": [{"name": "main", "type": "psql", "interval": 60, "command": "SELECT 1;"}],
                },
            )
            self.workload.check_min_pg_version(profile, 90600)

    def test_query_server_version_num_parses_and_rejects_garbage(self):
        class FakeClient:
            def __init__(self, value):
                self.value = value

            def query_scalar(self, dbname, user, password, sql):
                return self.value

        config = types.SimpleNamespace(dbname="d", workload_user="u", workload_password=None)
        self.assertEqual(query_server_version_num(FakeClient("180004"), config), 180004)
        with self.assertRaisesRegex(self.workload.WorkloadError, "Cannot parse server_version_num"):
            query_server_version_num(FakeClient("not-a-version"), config)

    def test_jsonb_docs_declares_min_pg_version_12(self):
        manifest = self.workload.bundled_profiles_root() / "jsonb_docs" / "profile.yml"
        profile = self.workload.Profile(manifest.parent, load_yaml(manifest))
        self.assertEqual(profile.data.get("min_pg_version"), 12)
        self.assertEqual(self.workload.validate_profile(profile), [])


class BundledProfileReadmeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workload = load_module()

    def test_every_bundled_profile_ships_a_readme(self):
        root = self.workload.bundled_profiles_root()
        manifests = sorted(root.glob("*/profile.yml"))
        self.assertTrue(manifests)
        for manifest in manifests:
            readme = manifest.parent / "README.md"
            self.assertTrue(readme.is_file(), f"missing README.md for bundled profile {manifest.parent.name}")
            content = readme.read_text(encoding="utf-8")
            for section in ("## Jobs", "## What to watch in pg_diag", "## Recommended scale and observation window"):
                self.assertIn(section, content, f"{manifest.parent.name}/README.md misses section {section!r}")


if __name__ == "__main__":
    unittest.main()
