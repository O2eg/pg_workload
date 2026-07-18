from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pg_workload.common import (
    DEFAULT_PGBENCH_CLIENTS,
    DEFAULT_PGBENCH_THREADS,
    WorkloadError,
    eprint,
    format_command,
    merge_pgoptions,
    redact_text,
)
from pg_workload.config import RuntimeConfig
from pg_workload.logging import close_logger, profile_job_logger
from pg_workload.resources import assert_resources_available

if TYPE_CHECKING:
    from pg_workload.profiles import Profile


class PgClient:
    def __init__(self, config: RuntimeConfig):
        self.config = config

    def secrets(self) -> list[str | None]:
        return [self.config.workload_password, self.config.admin_password]

    def env(self, password: str | None, *, include_workload_settings: bool = True) -> dict[str, str]:
        env = os.environ.copy()
        for name in ("PGPASSWORD", "WORKLOAD_PASSWORD", "WORKLOAD_ADMIN_PASSWORD"):
            env.pop(name, None)
        if password:
            env["PGPASSWORD"] = password
        if self.config.passfile:
            env["PGPASSFILE"] = str(self.config.passfile)
        env["PGCONNECT_TIMEOUT"] = str(self.config.connect_timeout)
        if self.config.sslmode:
            env["PGSSLMODE"] = self.config.sslmode
        if include_workload_settings and self.config.libpq_workload_settings:
            env["PGOPTIONS"] = merge_pgoptions(
                env.get("PGOPTIONS"),
                {
                    "workload.dbname": self.config.dbname,
                    "workload.username": self.config.workload_user,
                },
            )
        return env

    def psql_variable_args(self) -> list[str]:
        return [
            "-v",
            f"workload_dbname={self.config.dbname}",
            "-v",
            f"workload_user={self.config.workload_user}",
        ]

    def psql_base(self, dbname: str, user: str) -> list[str]:
        return [
            self.config.psql,
            "-h",
            self.config.host,
            "-p",
            str(self.config.port),
            "-U",
            user,
            "-d",
            dbname,
            "-v",
            "ON_ERROR_STOP=1",
        ] + self.psql_variable_args()

    def run(
        self,
        cmd: list[str],
        *,
        env: dict[str, str],
        cwd: Path | None = None,
        log_path: Path | None = None,
        allow_failure: bool = False,
        input_text: str | None = None,
    ) -> None:
        display_cmd = format_command(cmd, self.secrets())
        if self.config.verbose or self.config.dry_run:
            print("$", display_cmd)
        if self.config.dry_run:
            return
        assert_resources_available(self.config, f"starting command: {display_cmd}")

        if log_path:
            logger = profile_job_logger(
                log_path,
                max_bytes=self.config.log_max_bytes,
                backup_count=self.config.log_backups,
                rotate_on_start=self.config.log_rotate_on_start,
            )
            logger.info("$ %s", display_cmd)
            try:
                with subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.PIPE if input_text is not None else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                ) as proc:
                    if input_text is not None and proc.stdin is not None:
                        try:
                            proc.stdin.write(input_text)
                            proc.stdin.close()
                        except BrokenPipeError:
                            pass
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        logger.info("%s", redact_text(line.rstrip("\n"), self.secrets()))
                    proc.wait()
            finally:
                close_logger(logger)
        else:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                input=input_text,
                text=input_text is not None,
            )

        if proc.returncode != 0 and allow_failure:
            eprint(f"Allowed command failure with exit code {proc.returncode}: {display_cmd}")
            return
        if proc.returncode != 0:
            target = f" See log: {log_path}" if log_path else ""
            raise WorkloadError(f"Command failed with exit code {proc.returncode}.{target}")

    def query_scalar(self, dbname: str, user: str, password: str | None, sql: str) -> str:
        cmd = self.psql_base(dbname, user) + ["-Atq", "-c", sql]
        if self.config.verbose or self.config.dry_run:
            print("$", format_command(cmd, self.secrets()))
        if self.config.dry_run:
            return ""
        assert_resources_available(self.config, "starting psql metadata query")
        proc = subprocess.run(
            cmd,
            env=self.env(password),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            message = proc.stderr.strip() or f"psql failed: {sql}"
            raise WorkloadError(redact_text(message, self.secrets()))
        return proc.stdout.strip()

    def run_psql(
        self,
        dbname: str,
        user: str,
        password: str | None,
        *,
        command: str | None = None,
        file_path: Path | None = None,
        cwd: Path | None = None,
        extra_args: list[str] | None = None,
        log_path: Path | None = None,
        allow_failure: bool = False,
    ) -> None:
        cmd = self.psql_base(dbname, user)
        cmd.extend(extra_args or [])
        input_text = None
        if command:
            input_text = command.rstrip() + "\n"
        elif file_path:
            cmd.extend(["-f", str(file_path)])
        else:
            raise WorkloadError("Either command or file_path is required")
        self.run(
            cmd,
            env=self.env(password),
            cwd=cwd,
            log_path=log_path,
            allow_failure=allow_failure,
            input_text=input_text,
        )

    def run_pgbench(self, profile: Profile, job: dict[str, Any], log_path: Path) -> None:
        cmd = [self.config.pgbench]
        if job.get("no_vacuum", True):
            cmd.append("--no-vacuum")
        clients = (
            self.config.pgbench_clients
            if self.config.pgbench_clients is not None
            else job.get("clients", DEFAULT_PGBENCH_CLIENTS)
        )
        threads = (
            self.config.pgbench_threads
            if self.config.pgbench_threads is not None
            else job.get("threads", DEFAULT_PGBENCH_THREADS)
        )
        duration = self.config.pgbench_duration if self.config.pgbench_duration is not None else job.get("duration", 1)
        transactions = (
            self.config.pgbench_transactions
            if self.config.pgbench_transactions is not None
            else job.get("transactions")
        )
        cmd.extend(["-c", str(clients)])
        cmd.extend(["-j", str(threads)])
        if transactions is not None:
            cmd.extend(["-t", str(transactions)])
        else:
            cmd.extend(["-T", str(duration)])
        cmd.extend(str(value) for value in job.get("extra_args", []) or [])

        for script in profile.expand_scripts(job):
            file_part = str(profile.path / script["path"])
            if script.get("weight") is not None:
                file_part = f"{file_part}@{script['weight']}"
            cmd.extend(["-f", file_part])

        cmd.extend(
            [
                "-p",
                str(self.config.port),
                "-h",
                self.config.host,
                "-U",
                self.config.workload_user,
                self.config.dbname,
            ]
        )
        self.run(
            cmd,
            env=self.env(self.config.workload_password),
            cwd=profile.path,
            log_path=log_path,
            allow_failure=bool(job.get("allow_failure", False)),
        )

    def run_generator(self, file_path: Path, *, cwd: Path, scale: float) -> None:
        env = self.env(self.config.workload_password, include_workload_settings=False)
        env.update(
            {
                "PGHOST": self.config.host,
                "PGPORT": str(self.config.port),
                "PGDATABASE": self.config.dbname,
                "PGUSER": self.config.workload_user,
                "PGAPPNAME": "pg-workload-generator",
                "PG_WORKLOAD_PSQL": self.config.psql,
            }
        )
        self.run(
            [sys.executable, str(file_path), "--scale", str(scale)],
            env=env,
            cwd=cwd,
        )
