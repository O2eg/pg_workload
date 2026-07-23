from __future__ import annotations

import argparse
from typing import Any

from pg_workload.common import (
    DEFAULT_EXTENSIONS,
    WorkloadError,
    as_string_list,
    csv_list,
    eprint,
    quote_ident,
    quote_literal,
    safe_extension_name,
)
from pg_workload.config import RuntimeConfig
from pg_workload.pg_client import PgClient
from pg_workload.profiles import Profile
from pg_workload.resources import assert_resources_available


def prepare_database(client: PgClient, config: RuntimeConfig, args: argparse.Namespace) -> None:
    admin_password = config.admin_password
    attrs = "SUPERUSER" if args.workload_superuser else "NOSUPERUSER"
    role = config.workload_user

    if args.recreate:
        client.run_psql(
            config.admin_db,
            config.admin_user,
            admin_password,
            command=(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = {quote_literal(config.dbname)} AND pid <> pg_backend_pid();"
            ),
        )
        client.run_psql(
            config.admin_db,
            config.admin_user,
            admin_password,
            command=f"DROP DATABASE IF EXISTS {quote_ident(config.dbname)};",
        )

    role_exists = client.query_scalar(
        config.admin_db,
        config.admin_user,
        admin_password,
        f"SELECT 1 FROM pg_roles WHERE rolname = {quote_literal(role)};",
    )
    if not role_exists:
        if not config.workload_password:
            raise WorkloadError(
                "The workload role does not exist. Set WORKLOAD_PASSWORD before prepare-db; "
                "pg-workload has no built-in password."
            )
        client.run_psql(
            config.admin_db,
            config.admin_user,
            admin_password,
            command=(
                f"CREATE ROLE {quote_ident(role)} LOGIN {attrs} PASSWORD {quote_literal(config.workload_password)};"
            ),
        )
    else:
        if args.workload_superuser:
            client.run_psql(
                config.admin_db,
                config.admin_user,
                admin_password,
                command=f"ALTER ROLE {quote_ident(role)} SUPERUSER;",
            )
        if args.rotate_workload_password:
            if not config.workload_password:
                raise WorkloadError("--rotate-workload-password requires WORKLOAD_PASSWORD")
            client.run_psql(
                config.admin_db,
                config.admin_user,
                admin_password,
                command=(f"ALTER ROLE {quote_ident(role)} PASSWORD {quote_literal(config.workload_password)};"),
            )

    exists = client.query_scalar(
        config.admin_db,
        config.admin_user,
        admin_password,
        f"SELECT 1 FROM pg_database WHERE datname = {quote_literal(config.dbname)};",
    )
    if not exists:
        client.run_psql(
            config.admin_db,
            config.admin_user,
            admin_password,
            command=f"CREATE DATABASE {quote_ident(config.dbname)} OWNER {quote_ident(role)};",
        )

    extensions = csv_list(args.extensions) or list(DEFAULT_EXTENSIONS)
    for extension in extensions:
        client.run_psql(
            config.dbname,
            config.admin_user,
            admin_password,
            command=f"CREATE EXTENSION IF NOT EXISTS {safe_extension_name(extension)};",
        )

    preload_libraries = csv_list(args.preload_libraries) or ["auto_explain", "pg_stat_statements"]
    check_preload_libraries(client, config, admin_password, preload_libraries)


def check_preload_libraries(
    client: PgClient,
    config: RuntimeConfig,
    admin_password: str | None,
    required_libraries: list[str],
    *,
    dbname: str | None = None,
    user: str | None = None,
    fatal: bool = False,
) -> None:
    if not required_libraries:
        return
    if config.dry_run:
        print("Would check shared_preload_libraries for: " + ", ".join(required_libraries))
        return
    raw_value = client.query_scalar(
        dbname or config.admin_db,
        user or config.admin_user,
        admin_password,
        "SHOW shared_preload_libraries;",
    )
    loaded = {item.strip() for item in raw_value.split(",") if item.strip()}
    missing = [library for library in required_libraries if library not in loaded and f"{library}.so" not in loaded]
    if missing:
        message = (
            "shared_preload_libraries does not include: "
            + ", ".join(missing)
            + ". Configure this through PostgreSQL/Patroni before relying on related metrics."
        )
        if fatal:
            raise WorkloadError(message)
        eprint("WARNING: " + message)


def check_profile_requirements(client: PgClient, config: RuntimeConfig, profile: Profile) -> None:
    required_preload_libraries = as_string_list(
        profile.data.get("requires_preload_libraries"),
        f"{profile.name}: requires_preload_libraries",
    )
    if required_preload_libraries:
        check_preload_libraries(
            client,
            config,
            config.admin_password,
            required_preload_libraries,
            dbname=config.admin_db,
            user=config.admin_user,
            fatal=True,
        )


def check_min_pg_version(profile: Profile, server_version_num: int) -> None:
    """Reject a profile whose min_pg_version exceeds the target server version."""
    min_pg_version = profile.data.get("min_pg_version")
    if min_pg_version is None:
        return
    required = int(min_pg_version) * 10000
    if server_version_num < required:
        raise WorkloadError(
            f"Profile {profile.name} requires PostgreSQL >= {int(min_pg_version)} (min_pg_version), "
            f"but the target server reports server_version_num={server_version_num}"
        )


def query_server_version_num(client: PgClient, config: RuntimeConfig) -> int:
    raw_version = client.query_scalar(
        config.dbname,
        config.workload_user,
        config.workload_password,
        "SHOW server_version_num;",
    )
    try:
        return int(raw_version)
    except ValueError as exc:
        raise WorkloadError(f"Cannot parse server_version_num reported by the target: {raw_version!r}") from exc


def install_profiles(client: PgClient, config: RuntimeConfig, profiles: list[Profile]) -> None:
    server_version_num: int | None = None
    for profile in profiles:
        assert_resources_available(config, f"installing profile {profile.name}")
        print(f"Installing profile: {profile.name}")
        check_profile_requirements(client, config, profile)
        if profile.data.get("min_pg_version") is not None and not config.dry_run:
            if server_version_num is None:
                server_version_num = query_server_version_num(client, config)
            check_min_pg_version(profile, server_version_num)
        for step in profile.prepare_steps:
            step_type = step["type"]
            if step_type == "generator":
                assert_resources_available(config, f"generating data for profile {profile.name}")
                print(f"  Python generator {step['path']} (scale={config.scale})")
                client.run_generator(
                    profile.path / step["path"],
                    cwd=profile.path,
                    scale=config.scale,
                )
                continue
            if step_type != "sql":
                raise WorkloadError(f"Unsupported prepare step in {profile.name}: {step_type}")
            repeat = int(step.get("repeat", 1))
            if step.get("scale_repeat"):
                repeat = max(1, round(repeat * config.scale))
            extra_args = list(step.get("psql_args", []) or [])
            for index in range(repeat):
                label = f" ({index + 1}/{repeat})" if repeat > 1 else ""
                if "path" in step:
                    print(f"  SQL file {step['path']}{label}")
                    client.run_psql(
                        config.dbname,
                        config.workload_user,
                        config.workload_password,
                        file_path=profile.path / step["path"],
                        cwd=profile.path,
                        extra_args=extra_args,
                    )
                elif "command" in step:
                    print(f"  SQL command{label}: {step['command']}")
                    client.run_psql(
                        config.dbname,
                        config.workload_user,
                        config.workload_password,
                        command=step["command"],
                        cwd=profile.path,
                        extra_args=extra_args,
                    )
                else:
                    raise WorkloadError(f"Invalid SQL prepare step in {profile.name}: {step}")


def run_job_once(client: PgClient, config: RuntimeConfig, profile: Profile, job: dict[str, Any]) -> None:
    job_type = job.get("type")
    assert_resources_available(config, f"starting job {profile.name}:{job.get('name')}")
    print(f"Running {profile.name}:{job.get('name')}", flush=True)
    if job_type == "pgbench":
        client.run_pgbench(profile, job, profile.log_path(job))
    elif job_type == "psql":
        command = job.get("command")
        if not command:
            raise WorkloadError(f"psql job has no command: {profile.name}:{job.get('name')}")
        client.run_psql(
            config.dbname,
            config.workload_user,
            config.workload_password,
            command=command,
            cwd=profile.path,
            log_path=profile.log_path(job),
            allow_failure=bool(job.get("allow_failure", False)),
        )
    else:
        raise WorkloadError(f"Unsupported job type: {profile.name}:{job.get('name')} -> {job_type}")
