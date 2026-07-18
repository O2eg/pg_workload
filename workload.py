#!/usr/bin/env python3
"""Compatibility entry point; use ``pg-workload`` or ``python -m pg_workload``."""

from pg_workload import (
    API_VERSION,
    CpuSample,
    PgClient,
    Profile,
    ResourceGuard,
    RuntimeConfig,
    WorkloadError,
    assert_resources_available,
    build_parser,
    build_runtime_config,
    bundled_profiles_root,
    check_profile_requirements,
    effective_schedule,
    file_lock,
    initialize_project,
    install_profiles,
    job_recover_on_failure,
    load_profiles,
    load_state,
    prepare_database,
    save_yaml,
    update_job_state,
    validate_control_target,
    validate_profile,
)
from pg_workload.cli import main

__all__ = [
    "API_VERSION",
    "CpuSample",
    "PgClient",
    "Profile",
    "ResourceGuard",
    "RuntimeConfig",
    "WorkloadError",
    "assert_resources_available",
    "build_parser",
    "build_runtime_config",
    "bundled_profiles_root",
    "check_profile_requirements",
    "effective_schedule",
    "file_lock",
    "initialize_project",
    "install_profiles",
    "job_recover_on_failure",
    "load_profiles",
    "load_state",
    "main",
    "prepare_database",
    "save_yaml",
    "update_job_state",
    "validate_control_target",
    "validate_profile",
]


if __name__ == "__main__":
    raise SystemExit(main())
