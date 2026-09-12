"""Deterministic planning and machine-contract helpers for pg_play."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pg_workload import __version__
from pg_workload.common import DEFAULT_EXTENSIONS, DEFAULT_OPTIONAL_EXTENSIONS, csv_list, resolve_relative_path
from pg_workload.profiles import Profile
from pg_workload.state import load_state, state_with_profiles_enabled

CONTRACT_VERSION = "pg_play/component/v1"
CAPABILITY_SCHEMA_VERSION = "pg_play/capabilities/v1"
MACHINE_INTERFACE = {
    "machine_flag": "--machine",
    "request_id_option": "--request-id",
    "capabilities_option": "--component-capabilities",
}
COMPONENT = "pg_workload"

EXIT_CODES = {
    "success": 0,
    "validation_error": 2,
    "precondition_failed": 3,
    "unsupported": 4,
    "partial": 5,
    "execution_error": 6,
    "cancelled": 7,
    "ownership_error": 8,
}


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def profile_descriptor(profile: Profile) -> dict[str, Any]:
    files = []
    for path in sorted(profile.path.rglob("*")):
        if not path.is_file() or "log" in path.relative_to(profile.path).parts:
            continue
        files.append(
            {
                "path": str(path.relative_to(profile.path)),
                "hash": _file_hash(path),
            }
        )
    descriptor = {
        "name": profile.name,
        "description": str(profile.data.get("description", "")),
        "api_version": profile.data.get("api_version"),
        "schema": profile.schema,
        "requires_write": profile.data.get("requires_write", True),
        "min_pg_version": profile.data.get("min_pg_version"),
        "requires_preload_libraries": sorted(
            str(value) for value in profile.data.get("requires_preload_libraries", []) or []
        ),
        "jobs": [
            {
                "name": str(job.get("name")),
                "type": job.get("type"),
                "interval": job.get("interval", 60),
                "allow_failure": job.get("allow_failure", False),
            }
            for job in profile.jobs
        ],
        "files": files,
    }
    descriptor["profile_hash"] = canonical_hash(descriptor)
    return descriptor


def execution_plan(args: Any, profiles: list[Profile], operation: str) -> dict[str, Any]:
    requested_jobs = sorted(set(csv_list(getattr(args, "job", None))))
    selected = []
    for profile in sorted(profiles, key=lambda value: value.name):
        descriptor = profile_descriptor(profile)
        if requested_jobs:
            jobs = []
            for job_name in requested_jobs:
                job = profile.job_by_name(job_name)
                jobs.append(str(job["name"]))
        else:
            jobs = [str(job.get("name")) for job in profile.jobs]
        descriptor["selected_jobs"] = jobs
        selected.append(descriptor)

    root = Path(args.root).resolve()
    target = getattr(args, "target", "local")
    host = getattr(args, "host", None)
    if host is None and target == "local":
        host = "/var/run/postgresql"
    elif host is None and target == "external":
        host = "127.0.0.1"
    plan = {
        "schema_version": "pg_workload/plan-v1",
        "operation": operation,
        "root": str(root),
        "target": target,
        "postgresql": {
            "major": str(getattr(args, "pg_major", "18")),
            "bin_dir": (
                str(Path(args.bin_dir).resolve())
                if getattr(args, "bin_dir", None)
                else f"/usr/lib/postgresql/{getattr(args, 'pg_major', '18')}/bin"
            ),
            "host": host,
            "port": int(getattr(args, "port", None) or 5432),
            "database": getattr(args, "database", None),
            "workload_user": getattr(args, "workload_user", None),
            "admin_database": getattr(args, "admin_db", None),
            "admin_user": getattr(args, "admin_user", None),
            "sslmode": getattr(args, "sslmode", None),
            "passfile": (str(Path(args.passfile).expanduser().resolve()) if getattr(args, "passfile", None) else None),
            "patroni_urls": csv_list(getattr(args, "patroni_url", None)),
            "patroni_role": getattr(args, "patroni_role", None),
            "connect_timeout": getattr(args, "connect_timeout", 5),
        },
        "database_changes": {
            "recreate": getattr(args, "recreate", False),
            "prepare_db": getattr(args, "prepare_db", False),
            "recreate_db": getattr(args, "recreate_db", False),
            "workload_superuser": getattr(args, "workload_superuser", False),
            "rotate_workload_password": getattr(args, "rotate_workload_password", False),
            "extensions": sorted(set(csv_list(getattr(args, "extensions", None)) or DEFAULT_EXTENSIONS)),
            "optional_extensions": (
                [] if csv_list(getattr(args, "extensions", None)) else sorted(DEFAULT_OPTIONAL_EXTENSIONS)
            ),
            "preload_libraries": sorted(set(csv_list(getattr(args, "preload_libraries", None)))),
        },
        "execution": {
            "scale": getattr(args, "scale", 1.0),
            "pgbench_clients": getattr(args, "pgbench_clients", None),
            "pgbench_threads": getattr(args, "pgbench_threads", None),
            "pgbench_duration": getattr(args, "pgbench_duration", None),
            "pgbench_transactions": getattr(args, "pgbench_transactions", None),
            "dry_run": getattr(args, "dry_run", False),
            "resource_guard": {
                "enabled": getattr(args, "resource_monitor_enabled", True),
                "disk_max_used_pct": getattr(args, "resource_disk_max_used_pct", 90),
                "mem_min_available_pct": getattr(args, "resource_mem_min_available_pct", 10),
                "mem_min_available_mb": getattr(args, "resource_mem_min_available_mb", 2048),
                "cpu_max_pct": getattr(args, "resource_cpu_max_pct", 90),
                "cpu_window_seconds": getattr(args, "resource_cpu_window_seconds", 60),
                "check_interval": getattr(args, "resource_check_interval", 5),
            },
        },
        "profiles": selected,
    }
    if operation == "scheduler":
        state_path = resolve_relative_path(
            root,
            getattr(args, "state_file", "state/workloads.yml"),
            "state file",
        )
        lock_path = resolve_relative_path(
            root,
            getattr(args, "daemon_lock_file", "state/scheduler.lock"),
            "scheduler lock file",
        )
        current_state = load_state(state_path)
        desired_state = (
            state_with_profiles_enabled(
                current_state,
                [profile.name for profile in profiles],
                interval_seconds=getattr(args, "job_interval_seconds", None),
            )
            if getattr(args, "enable_selected", False)
            else current_state
        )
        plan["scheduler"] = {
            "state_file": str(state_path),
            "current_state_hash": canonical_hash(current_state),
            "desired_state_hash": canonical_hash(desired_state),
            "enable_selected": getattr(args, "enable_selected", False),
            "daemon_lock_file": str(lock_path),
            "reload_interval": getattr(args, "reload_interval", 5),
            "run_immediately": getattr(args, "run_immediately", False),
            "job_interval_seconds": getattr(args, "job_interval_seconds", None),
            "recover_on_failure": getattr(args, "recover_on_failure", True),
            "recover_interval": getattr(args, "recover_interval", 60),
            "stop_timeout": getattr(args, "stop_timeout", 10),
        }
    plan["plan_hash"] = canonical_hash(plan)
    return plan


def capabilities() -> dict[str, Any]:
    return {
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
        "machine_interface": MACHINE_INTERFACE,
        "contract_version": CONTRACT_VERSION,
        "component": COMPONENT,
        "component_version": __version__,
        "commands": {
            "capabilities": {"mutates_target": False, "machine_output": True, "accepts_plan_hash": False},
            "profiles": {"mutates_target": False, "machine_output": True, "accepts_plan_hash": False},
            "validate": {"mutates_target": False, "machine_output": True, "accepts_plan_hash": False},
            "plan": {"mutates_target": False, "machine_output": True, "accepts_plan_hash": False},
            "prepare-db": {"mutates_target": True, "machine_output": True, "accepts_plan_hash": True},
            "install": {"mutates_target": True, "machine_output": True, "accepts_plan_hash": True},
            "run": {"mutates_target": True, "machine_output": True, "accepts_plan_hash": True},
            "start": {"mutates_target": True, "machine_output": True, "accepts_plan_hash": True},
            "status": {"mutates_target": False, "machine_output": True, "accepts_plan_hash": False},
            "stop": {
                "mutates_target": True,
                "machine_output": True,
                "accepts_plan_hash": False,
                "ownership_checked": True,
            },
        },
        "profile_schema_versions": ["pg_workload/v1"],
        "plan_schema_versions": ["pg_workload/plan-v1"],
        "states": [
            "planned",
            "running",
            "succeeded",
            "partial",
            "failed",
            "cancelled",
            "skipped",
            "blocked",
        ],
        "exit_codes": EXIT_CODES,
        "secret_policy": {
            "password_sources": ["environment", "passfile"],
            "secrets_in_process_arguments": False,
            "machine_output_contains_secrets": False,
        },
    }


def envelope(
    command: str,
    status: str,
    *,
    request_id: str | None,
    result: Any = None,
    artifacts: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "component": COMPONENT,
        "component_version": __version__,
        "command": command,
        "request_id": request_id,
        "status": status,
        "result": result,
        "artifacts": artifacts or [],
        "warnings": warnings or [],
        "error": error,
    }
