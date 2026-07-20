from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
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
from pg_workload.control import (
    WorkloadOwnershipError,
    scheduler_status,
    start_scheduler,
    stop_scheduler,
)
from pg_workload.orchestration import (
    EXIT_CODES,
    capabilities,
    envelope,
    execution_plan,
    profile_descriptor,
)
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
from pg_workload.state import enable_profiles, load_state, update_job_state

DEFAULT_ROOT = "."
DEFAULT_SCHEDULER_LOG_FILE = "state/scheduler.log"


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


def _add_plan_guard(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--plan-hash",
        help="execute only if the current deterministic plan still matches this hash",
    )


def _add_scheduler_args(parser: argparse.ArgumentParser) -> None:
    _add_profile_filter(parser)
    parser.add_argument(
        "--enable-selected",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="State path relative to root")
    parser.add_argument(
        "--daemon-lock-file",
        default=DEFAULT_DAEMON_LOCK_FILE,
        help="Scheduler lock path relative to root",
    )
    parser.add_argument("--reload-interval", type=positive_int_arg, default=5, help="State reload interval")
    parser.add_argument("--run-immediately", action="store_true", help="Run enabled jobs at scheduler start")
    parser.add_argument(
        "--recover-on-failure",
        dest="recover_on_failure",
        action="store_true",
        default=True,
        help="Reinstall a failed profile before its next run (default)",
    )
    parser.add_argument(
        "--no-recover-on-failure",
        dest="recover_on_failure",
        action="store_false",
        help="Disable automatic profile recovery",
    )
    parser.add_argument("--recover-interval", type=positive_int_arg, default=60, help="Recovery retry delay")
    parser.add_argument("--stop-timeout", type=positive_int_arg, default=10, help="Child stop timeout")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pg-workload",
        description="Emulate PostgreSQL backend activity for diagnostic observation",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--machine",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--request-id",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--component-capabilities",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command")

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
    _add_plan_guard(prepare_cmd)
    prepare_cmd.add_argument("--recreate", action="store_true", help="Drop and recreate the workload database")
    _add_prepare_args(prepare_cmd)

    install_cmd = subparsers.add_parser("install", help="Install selected profile schemas and data")
    add_common_args(install_cmd)
    _add_plan_guard(install_cmd)
    _add_profile_filter(install_cmd, required=True)
    install_cmd.add_argument("--prepare-db", action="store_true", help="Run prepare-db before profile installation")
    install_cmd.add_argument("--recreate-db", action="store_true", help="Recreate database with --prepare-db")
    _add_prepare_args(install_cmd)

    run_cmd = subparsers.add_parser("run", help="Run selected profile jobs once")
    add_common_args(run_cmd)
    _add_plan_guard(run_cmd)
    _add_profile_filter(run_cmd, required=True)
    run_cmd.add_argument("--job", action="append", help="Job name; repeat or use comma-separated names")

    scheduler_cmd = subparsers.add_parser("scheduler", help="Run the foreground desired-state scheduler")
    add_common_args(scheduler_cmd)
    _add_scheduler_args(scheduler_cmd)
    _add_plan_guard(scheduler_cmd)

    start_cmd = subparsers.add_parser("start", help="Start the desired-state scheduler in the background")
    add_common_args(start_cmd)
    _add_scheduler_args(start_cmd)
    _add_plan_guard(start_cmd)
    start_cmd.add_argument(
        "--scheduler-log-file",
        default=DEFAULT_SCHEDULER_LOG_FILE,
        help="Scheduler stdout/stderr path relative to root",
    )
    start_cmd.add_argument(
        "--start-timeout",
        type=positive_float_arg,
        default=5.0,
        help="Seconds to wait for scheduler lock acquisition",
    )

    status_cmd = subparsers.add_parser("status", help="Show scheduler and desired workload state")
    status_cmd.add_argument("--root", default=DEFAULT_ROOT, help="Initialized project directory")
    status_cmd.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="State path relative to root")
    status_cmd.add_argument(
        "--daemon-lock-file", default=DEFAULT_DAEMON_LOCK_FILE, help="Scheduler lock path relative to root"
    )
    status_cmd.add_argument("--scheduler-log-file", default=DEFAULT_SCHEDULER_LOG_FILE)

    stop_cmd = subparsers.add_parser("stop", help="Stop the owned background scheduler")
    stop_cmd.add_argument("--root", default=DEFAULT_ROOT, help="Initialized project directory")
    stop_cmd.add_argument("--daemon-lock-file", default=DEFAULT_DAEMON_LOCK_FILE)
    stop_cmd.add_argument("--scheduler-log-file", default=DEFAULT_SCHEDULER_LOG_FILE)
    stop_cmd.add_argument("--timeout", type=positive_float_arg, default=10.0)

    plan_cmd = subparsers.add_parser("plan", help="Build a deterministic execution plan without connecting")
    add_common_args(plan_cmd)
    plan_cmd.add_argument(
        "--operation",
        choices=("prepare-db", "install", "run", "scheduler"),
        default="run",
    )
    _add_profile_filter(plan_cmd)
    plan_cmd.add_argument("--job", action="append", help="Job name for operation=run")
    plan_cmd.add_argument("--recreate", action="store_true")
    plan_cmd.add_argument("--prepare-db", action="store_true")
    plan_cmd.add_argument("--recreate-db", action="store_true")
    _add_prepare_args(plan_cmd)
    plan_cmd.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    plan_cmd.add_argument("--daemon-lock-file", default=DEFAULT_DAEMON_LOCK_FILE)
    plan_cmd.add_argument("--reload-interval", type=positive_int_arg, default=5)
    plan_cmd.add_argument("--run-immediately", action="store_true")
    plan_cmd.add_argument(
        "--enable-selected",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    plan_cmd.add_argument(
        "--recover-on-failure",
        dest="recover_on_failure",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    plan_cmd.add_argument("--recover-interval", type=positive_int_arg, default=60)
    plan_cmd.add_argument("--stop-timeout", type=positive_int_arg, default=10)

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


def _plan_for_args(args: argparse.Namespace, operation: str) -> dict[str, object]:
    if operation == "prepare-db":
        profiles = []
    elif operation == "scheduler":
        root = Path(args.root).resolve()
        profiles = selected_profiles(load_profiles(root, allow_empty=True), args.profiles)
        errors = [error for profile in profiles for error in validate_profile(profile)]
        if errors:
            raise WorkloadError("Invalid workload profiles:\n" + "\n".join(errors))
    else:
        profiles = _validated_selection(Path(args.root).resolve(), args.profiles)
    return execution_plan(args, profiles, operation)


def _verify_plan_hash(args: argparse.Namespace, operation: str) -> dict[str, object]:
    plan = _plan_for_args(args, operation)
    expected = getattr(args, "plan_hash", None)
    if expected and expected != plan["plan_hash"]:
        raise WorkloadError(f"Stale plan: expected {expected}, current plan is {plan['plan_hash']}")
    return plan


def _scheduler_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    root = Path(args.root).resolve()
    lock_path = resolve_relative_path(root, args.daemon_lock_file, "scheduler lock file")
    log_path = resolve_relative_path(root, args.scheduler_log_file, "scheduler log file")
    return root, lock_path, log_path


def _status(args: argparse.Namespace) -> dict[str, object]:
    root, lock_path, log_path = _scheduler_paths(args)
    state_path = resolve_relative_path(root, args.state_file, "state file")
    profiles = load_profiles(root, allow_empty=True)
    return {
        "schema_version": "pg_workload/status-v1",
        "scheduler": scheduler_status(root, lock_path, log_path),
        "desired_state": load_state(state_path),
        "profiles": [profile_descriptor(profile) for profile in profiles.values()],
    }


def _emit_machine(
    args: argparse.Namespace,
    status: str,
    *,
    result: object = None,
    artifacts: list[dict[str, object]] | None = None,
    warnings: list[str] | None = None,
    error: dict[str, object] | None = None,
) -> None:
    print(
        json.dumps(
            envelope(
                args.command,
                status,
                request_id=args.request_id,
                result=result,
                artifacts=artifacts,
                warnings=warnings,
                error=error,
            ),
            indent=2,
            sort_keys=True,
        )
    )


def _run(args: argparse.Namespace) -> int:
    if args.component_capabilities:
        result = capabilities()
        if args.machine:
            original_command = args.command
            args.command = "capabilities"
            try:
                _emit_machine(args, "succeeded", result=result)
            finally:
                args.command = original_command
        else:
            print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), end="")
        return 0
    if args.command == "init":
        result = initialize_project(Path(args.directory), force=args.force)
        if args.machine:
            _emit_machine(
                args,
                "succeeded",
                result=result,
                artifacts=[
                    {
                        "kind": "WorkloadProject",
                        "schema_version": "pg_workload/v1",
                        "path": str(Path(args.directory).resolve()),
                    }
                ],
            )
        else:
            assets = result["assets"]
            print(
                f"Initialized {result['root']} "
                f"(created={assets['created']}, updated={assets['updated']}, "
                f"unchanged={assets['unchanged']})"
            )
        return 0
    if args.command == "profiles":
        profiles = load_profiles(Path(args.root))
        if args.machine:
            _emit_machine(
                args,
                "succeeded",
                result={
                    "root": str(Path(args.root).resolve()),
                    "profiles": [profile_descriptor(profile) for profile in profiles.values()],
                },
            )
        else:
            for profile in profiles.values():
                print(f"{profile.name}\t{profile.data.get('description', '')}")
        return 0
    if args.command == "validate":
        profiles = selected_profiles(load_profiles(Path(args.root)), args.profiles)
        errors = [error for profile in profiles for error in validate_profile(profile)]
        if args.machine:
            _emit_machine(
                args,
                "failed" if errors else "succeeded",
                result={
                    "valid": not errors,
                    "errors": errors,
                    "profiles": [profile_descriptor(profile) for profile in profiles],
                },
                error=({"code": "validation_error", "message": "profile validation failed"} if errors else None),
            )
            return EXIT_CODES["validation_error"] if errors else 0
        if errors:
            for error in errors:
                eprint(error)
            return 1
        print("OK")
        return 0
    if args.command == "plan":
        result = _plan_for_args(args, args.operation)
        if args.machine:
            _emit_machine(args, "planned", result=result)
        else:
            print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), end="")
        return 0
    if args.command == "status":
        result = _status(args)
        if args.machine:
            _emit_machine(args, "succeeded", result=result)
        else:
            print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), end="")
        return 0
    if args.command == "stop":
        root, lock_path, log_path = _scheduler_paths(args)
        result = stop_scheduler(root, lock_path, log_path, args.timeout)
        if args.machine:
            _emit_machine(args, "succeeded", result=result)
        else:
            print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), end="")
        return 0
    if args.command in {"enable", "disable", "set-interval", "state"}:
        root = Path(args.root).resolve()
        state_path = resolve_relative_path(root, args.state_file, "state file")
        if args.command == "enable":
            validate_control_target(root, args.profile, args.job, strict=True)
            update_job_state(
                state_path,
                args.profile,
                enabled=True,
                job_name=args.job,
                interval=args.interval,
            )
            message = f"Enabled {args.profile}{':' + args.job if args.job else ''}"
        elif args.command == "disable":
            validate_control_target(root, args.profile, args.job, strict=False)
            update_job_state(state_path, args.profile, enabled=False, job_name=args.job)
            message = f"Disabled {args.profile}{':' + args.job if args.job else ''}"
        elif args.command == "set-interval":
            validate_control_target(root, args.profile, args.job, strict=True)
            update_job_state(
                state_path,
                args.profile,
                job_name=args.job,
                interval=args.seconds,
            )
            message = f"Set interval {args.profile}:{args.job} = {args.seconds}s"
        else:
            result = load_state(state_path)
            if args.machine:
                _emit_machine(args, "succeeded", result=result)
            else:
                print(yaml.safe_dump(result, allow_unicode=True, sort_keys=True), end="")
            return 0
        if args.machine:
            _emit_machine(
                args,
                "succeeded",
                result={"message": message, "desired_state": load_state(state_path)},
            )
        else:
            print(message)
        return 0

    operation = "scheduler" if args.command in {"scheduler", "start"} else args.command
    plan = _verify_plan_hash(args, operation)
    if operation == "scheduler" and args.enable_selected:
        root = Path(args.root).resolve()
        profiles = selected_profiles(load_profiles(root, allow_empty=True), args.profiles)
        state_path = resolve_relative_path(root, args.state_file, "state file")
        enable_profiles(state_path, [profile.name for profile in profiles])
    config = build_runtime_config(args)
    if args.command == "start":
        root, lock_path, log_path = _scheduler_paths(args)
        result = start_scheduler(config, args, lock_path, log_path)
        result["plan_hash"] = plan["plan_hash"]
        if args.machine:
            _emit_machine(args, "running", result=result)
        else:
            print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), end="")
        return 0

    client = PgClient(config)
    output_context = contextlib.redirect_stdout(sys.stderr) if args.machine else contextlib.nullcontext()
    with output_context:
        if args.command == "prepare-db":
            prepare_database(client, config, args)
        elif args.command == "install":
            profiles = _validated_selection(config.root, args.profiles)
            if args.prepare_db:
                args.recreate = args.recreate_db
                prepare_database(client, config, args)
            install_profiles(client, config, profiles)
        elif args.command == "run":
            profiles = _validated_selection(config.root, args.profiles)
            for profile in profiles:
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
    if args.machine:
        _emit_machine(
            args,
            "succeeded",
            result={"plan_hash": plan["plan_hash"], "operation": operation},
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None and not args.component_capabilities:
        parser.error("a command is required")
    try:
        return _run(args)
    except WorkloadOwnershipError as exc:
        if args.machine:
            _emit_machine(
                args,
                "failed",
                error={"code": "ownership_error", "message": str(exc)},
            )
            return EXIT_CODES["ownership_error"]
        eprint(f"ERROR: {exc}")
        return 1
    except WorkloadError as exc:
        if args.machine:
            code = "precondition_failed" if str(exc).startswith("Stale plan:") else "execution_error"
            status = "blocked" if code == "precondition_failed" else "failed"
            _emit_machine(args, status, error={"code": code, "message": str(exc)})
            return EXIT_CODES[code]
        eprint(f"ERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        if args.machine:
            _emit_machine(
                args,
                "cancelled",
                error={"code": "cancelled", "message": "interrupted"},
            )
            return EXIT_CODES["cancelled"]
        eprint("ERROR: interrupted")
        return 130
