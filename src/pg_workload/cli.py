from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

from pg_workload import __version__
from pg_workload.assets import initialize_project
from pg_workload.common import (
    DEFAULT_DAEMON_LOCK_FILE,
    DEFAULT_DB,
    DEFAULT_LOG_BACKUPS,
    DEFAULT_LOG_MAX_MB,
    DEFAULT_PG_MAJOR,
    DEFAULT_RESOURCE_CHECK_INTERVAL,
    DEFAULT_RESOURCE_CPU_MAX_PCT,
    DEFAULT_RESOURCE_CPU_WINDOW_SECONDS,
    DEFAULT_RESOURCE_DISK_MAX_USED_PCT,
    DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_MB,
    DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_PCT,
    DEFAULT_STATE_FILE,
    DEFAULT_USER,
    WorkloadError,
    csv_list,
    eprint,
    non_negative_int_arg,
    percent_arg,
    positive_float_arg,
    positive_int_arg,
    resolve_relative_path,
)
from pg_workload.config import build_runtime_config
from pg_workload.pg_client import PgClient
from pg_workload.profiles import (
    Profile,
    load_profiles,
    selected_profiles,
    validate_control_target,
    validate_profile,
)
from pg_workload.runner import install_profiles, prepare_database, run_job_once
from pg_workload.scheduler import run_scheduler
from pg_workload.state import load_state, update_job_state

DEFAULT_ROOT = "."


def _add_profile_filter(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument(
        "--profile",
        "--workload",
        dest="profiles",
        action="append",
        required=required,
        help="Profile name; repeat the option or pass comma-separated names (--workload is deprecated)",
    )


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.set_defaults(
        workload_password=os.environ.get("WORKLOAD_PASSWORD"),
        admin_password=os.environ.get("WORKLOAD_ADMIN_PASSWORD", os.environ.get("PGPASSWORD")),
    )
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Initialized pg-workload project directory")
    parser.add_argument(
        "--target",
        choices=["local", "external", "patroni"],
        default="local",
        help="Connection discovery mode (default: local)",
    )
    parser.add_argument("--pg-major", default=DEFAULT_PG_MAJOR, help="PostgreSQL client major version")
    parser.add_argument("--bin-dir", help="Directory containing psql and pgbench")
    parser.add_argument("--host", help="PostgreSQL host or Unix socket directory")
    parser.add_argument("--port", type=positive_int_arg, help="PostgreSQL port (default: 5432)")
    parser.add_argument(
        "--database",
        "--dbname",
        dest="database",
        default=DEFAULT_DB,
        help="Workload database (--dbname is a compatibility alias)",
    )
    parser.add_argument("--workload-user", default=DEFAULT_USER, help="Role used to execute workload jobs")
    parser.add_argument(
        "--passfile",
        default=os.environ.get("PGPASSFILE"),
        help="libpq password file for existing database roles (also accepts PGPASSFILE)",
    )
    parser.add_argument("--admin-db", default="postgres", help="Database used for administrative commands")
    parser.add_argument("--admin-user", default="postgres", help="Role used for administrative commands")
    parser.add_argument(
        "--patroni-url",
        action="append",
        default=[],
        help="Patroni REST API base URL; repeat or pass comma-separated URLs",
    )
    parser.add_argument(
        "--patroni-role",
        choices=["master", "replicas", "sync", "async"],
        default="master",
        help="Patroni health endpoint used to select a member",
    )
    parser.add_argument("--connect-timeout", type=positive_int_arg, default=5, help="libpq timeout in seconds")
    parser.add_argument("--sslmode", help="libpq sslmode")
    parser.add_argument("--pgbench-clients", type=positive_int_arg, help="Override profile client count")
    parser.add_argument("--pgbench-threads", type=positive_int_arg, help="Override profile thread count")
    execution_limit = parser.add_mutually_exclusive_group()
    execution_limit.add_argument("--pgbench-duration", type=positive_int_arg, help="Override duration in seconds")
    execution_limit.add_argument(
        "--pgbench-transactions", type=positive_int_arg, help="Override transactions per client"
    )
    parser.add_argument(
        "--scale",
        type=positive_float_arg,
        default=1.0,
        help="Synthetic data volume coefficient used by profile generators (default: 1.0)",
    )
    libpq_settings_group = parser.add_mutually_exclusive_group()
    libpq_settings_group.add_argument(
        "--libpq-workload-settings",
        dest="libpq_workload_settings",
        action="store_true",
        default=True,
        help="Pass non-secret workload database/user metadata through PGOPTIONS (default)",
    )
    libpq_settings_group.add_argument(
        "--no-libpq-workload-settings",
        dest="libpq_workload_settings",
        action="store_false",
        help="Disable custom PGOPTIONS, for example behind PgBouncer",
    )
    parser.add_argument("--log-max-mb", type=positive_int_arg, default=DEFAULT_LOG_MAX_MB, help="Log rotate size")
    parser.add_argument("--log-backups", type=non_negative_int_arg, default=DEFAULT_LOG_BACKUPS, help="Log backups")
    parser.add_argument(
        "--log-rotate-on-start",
        dest="log_rotate_on_start",
        action="store_true",
        default=True,
        help="Rotate a job log when a new run starts (default)",
    )
    parser.add_argument(
        "--no-log-rotate-on-start",
        dest="log_rotate_on_start",
        action="store_false",
        help="Append to the current job log until size rotation",
    )
    resource_group = parser.add_mutually_exclusive_group()
    resource_group.add_argument(
        "--resource-monitor",
        dest="resource_monitor_enabled",
        action="store_true",
        default=True,
        help="Enable host resource guard (default)",
    )
    resource_group.add_argument(
        "--no-resource-monitor",
        dest="resource_monitor_enabled",
        action="store_false",
        help="Disable the host resource guard",
    )
    parser.add_argument(
        "--resource-disk-max-used-pct",
        type=percent_arg,
        default=DEFAULT_RESOURCE_DISK_MAX_USED_PCT,
        help="Maximum used space on writable mounts",
    )
    parser.add_argument(
        "--resource-mem-min-available-pct",
        type=percent_arg,
        default=DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_PCT,
        help="Minimum available memory percent",
    )
    parser.add_argument(
        "--resource-mem-min-available-mb",
        type=non_negative_int_arg,
        default=DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_MB,
        help="Minimum available memory in MiB",
    )
    parser.add_argument(
        "--resource-cpu-max-pct",
        type=percent_arg,
        default=DEFAULT_RESOURCE_CPU_MAX_PCT,
        help="Maximum average CPU utilization",
    )
    parser.add_argument(
        "--resource-cpu-window-seconds",
        type=positive_int_arg,
        default=DEFAULT_RESOURCE_CPU_WINDOW_SECONDS,
        help="CPU averaging window",
    )
    parser.add_argument(
        "--resource-check-interval",
        type=positive_int_arg,
        default=DEFAULT_RESOURCE_CHECK_INTERVAL,
        help="Resource check interval",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    parser.add_argument("--verbose", action="store_true", help="Print commands as they run")


def _add_prepare_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workload-superuser", action="store_true", help="Create/promote workload role as superuser")
    parser.add_argument(
        "--rotate-workload-password",
        action="store_true",
        help="Explicitly replace the password of an existing workload role",
    )
    parser.add_argument("--extensions", action="append", help="Extension name; repeat or use comma-separated names")
    parser.add_argument("--preload-libraries", action="append", help="Required shared_preload_libraries entries")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pg-workload", description="PostgreSQL workload generator")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init", help="Create or update a working project from packaged profiles")
    init_cmd.add_argument("--directory", default=DEFAULT_ROOT, help="Destination project directory")
    init_cmd.add_argument("--force", action="store_true", help="Update modified immutable profile/schema assets")

    profiles_cmd = subparsers.add_parser("profiles", help="List profiles in an initialized project")
    profiles_cmd.add_argument("--root", default=DEFAULT_ROOT, help="Initialized project directory")

    validate_cmd = subparsers.add_parser("validate", help="Validate profile manifests and local paths")
    validate_cmd.add_argument("--root", default=DEFAULT_ROOT, help="Initialized project directory")
    _add_profile_filter(validate_cmd)

    prepare_cmd = subparsers.add_parser("prepare-db", help="Create the workload database, role, and extensions")
    add_common_args(prepare_cmd)
    prepare_cmd.add_argument("--recreate", action="store_true", help="Drop and recreate the workload database")
    _add_prepare_args(prepare_cmd)

    install_cmd = subparsers.add_parser("install", help="Install selected profile schemas and data")
    add_common_args(install_cmd)
    _add_profile_filter(install_cmd, required=True)
    install_cmd.add_argument("--prepare-db", action="store_true", help="Run prepare-db before profile installation")
    install_cmd.add_argument("--recreate-db", action="store_true", help="Recreate database with --prepare-db")
    _add_prepare_args(install_cmd)

    run_cmd = subparsers.add_parser("run", help="Run selected profile jobs once")
    add_common_args(run_cmd)
    _add_profile_filter(run_cmd, required=True)
    run_cmd.add_argument("--job", action="append", help="Job name; repeat or use comma-separated names")

    scheduler_cmd = subparsers.add_parser("scheduler", help="Run the foreground desired-state scheduler")
    add_common_args(scheduler_cmd)
    _add_profile_filter(scheduler_cmd)
    scheduler_cmd.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="State path relative to root")
    scheduler_cmd.add_argument(
        "--daemon-lock-file", default=DEFAULT_DAEMON_LOCK_FILE, help="Scheduler lock path relative to root"
    )
    scheduler_cmd.add_argument("--reload-interval", type=positive_int_arg, default=5, help="State reload interval")
    scheduler_cmd.add_argument("--run-immediately", action="store_true", help="Run enabled jobs at scheduler start")
    scheduler_cmd.add_argument(
        "--recover-on-failure",
        dest="recover_on_failure",
        action="store_true",
        default=True,
        help="Reinstall a failed profile before its next run (default)",
    )
    scheduler_cmd.add_argument(
        "--no-recover-on-failure",
        dest="recover_on_failure",
        action="store_false",
        help="Disable automatic profile recovery",
    )
    scheduler_cmd.add_argument("--recover-interval", type=positive_int_arg, default=60, help="Recovery retry delay")
    scheduler_cmd.add_argument("--stop-timeout", type=positive_int_arg, default=10, help="Child stop timeout")

    for command, help_text in (("enable", "Enable profile or job"), ("disable", "Disable profile or job")):
        control = subparsers.add_parser(command, help=help_text)
        control.add_argument("profile", help="Profile name")
        control.add_argument("--job", help="Job name; omit to control the entire profile")
        if command == "enable":
            control.add_argument("--interval", type=positive_int_arg, help="Override schedule interval")
        control.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="State path relative to root")
        control.add_argument("--root", default=DEFAULT_ROOT, help="Initialized project directory")

    interval_cmd = subparsers.add_parser("set-interval", help="Set a scheduler interval override")
    interval_cmd.add_argument("profile", help="Profile name")
    interval_cmd.add_argument("job", help="Job name")
    interval_cmd.add_argument("seconds", type=positive_int_arg, help="Interval in seconds")
    interval_cmd.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="State path relative to root")
    interval_cmd.add_argument("--root", default=DEFAULT_ROOT, help="Initialized project directory")

    state_cmd = subparsers.add_parser("state", help="Print desired scheduler state")
    state_cmd.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="State path relative to root")
    state_cmd.add_argument("--root", default=DEFAULT_ROOT, help="Initialized project directory")
    return parser


def _validated_selection(root: Path, names: list[str] | None) -> list[Profile]:
    profiles = selected_profiles(load_profiles(root), names)
    errors = [error for profile in profiles for error in validate_profile(profile)]
    if errors:
        raise WorkloadError("Invalid workload profiles:\n" + "\n".join(errors))
    return profiles


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_project(Path(args.directory), force=args.force)
            assets = result["assets"]
            print(
                f"Initialized {result['root']} "
                f"(created={assets['created']}, updated={assets['updated']}, unchanged={assets['unchanged']})"
            )
            return 0
        if args.command == "profiles":
            for profile in load_profiles(Path(args.root)).values():
                print(f"{profile.name}\t{profile.data.get('description', '')}")
            return 0
        if args.command == "validate":
            errors = [
                error
                for profile in selected_profiles(load_profiles(Path(args.root)), args.profiles)
                for error in validate_profile(profile)
            ]
            if errors:
                for error in errors:
                    eprint(error)
                return 1
            print("OK")
            return 0
        if args.command in {"enable", "disable", "set-interval", "state"}:
            root = Path(args.root).resolve()
            state_path = resolve_relative_path(root, args.state_file, "state file")
            if args.command == "enable":
                validate_control_target(root, args.profile, args.job, strict=True)
                update_job_state(state_path, args.profile, enabled=True, job_name=args.job, interval=args.interval)
                print(f"Enabled {args.profile}{':' + args.job if args.job else ''}")
            elif args.command == "disable":
                validate_control_target(root, args.profile, args.job, strict=False)
                update_job_state(state_path, args.profile, enabled=False, job_name=args.job)
                print(f"Disabled {args.profile}{':' + args.job if args.job else ''}")
            elif args.command == "set-interval":
                validate_control_target(root, args.profile, args.job, strict=True)
                update_job_state(state_path, args.profile, job_name=args.job, interval=args.seconds)
                print(f"Set interval {args.profile}:{args.job} = {args.seconds}s")
            else:
                print(yaml.safe_dump(load_state(state_path), allow_unicode=True, sort_keys=True), end="")
            return 0

        config = build_runtime_config(args)
        client = PgClient(config)
        if args.command == "prepare-db":
            prepare_database(client, config, args)
        elif args.command == "install":
            profiles = _validated_selection(config.root, args.profiles)
            if args.prepare_db:
                args.recreate = args.recreate_db
                prepare_database(client, config, args)
            install_profiles(client, config, profiles)
        elif args.command == "run":
            for profile in _validated_selection(config.root, args.profiles):
                jobs = [profile.job_by_name(name) for name in csv_list(args.job)] if args.job else profile.jobs
                for job in jobs:
                    run_job_once(client, config, profile, job)
        elif args.command == "scheduler":
            run_scheduler(
                client,
                config.root,
                args.profiles,
                resolve_relative_path(config.root, args.state_file, "state file"),
                args.reload_interval,
                args.run_immediately,
                resolve_relative_path(config.root, args.daemon_lock_file, "scheduler lock file"),
                args.recover_on_failure,
                args.recover_interval,
                args.stop_timeout,
            )
        else:  # pragma: no cover - argparse requires a known subcommand
            raise WorkloadError(f"Unhandled command: {args.command}")
        return 0
    except WorkloadError as exc:
        eprint(f"ERROR: {exc}")
        return 1
