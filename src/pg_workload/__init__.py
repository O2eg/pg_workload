"""PostgreSQL workload generation and scheduling tools."""

__version__ = "0.6.1"

from pg_workload.assets import bundled_profiles_root, initialize_project
from pg_workload.cli import build_parser
from pg_workload.common import WorkloadError, file_lock, save_yaml
from pg_workload.config import RuntimeConfig, build_runtime_config
from pg_workload.pg_client import PgClient
from pg_workload.profiles import (
    API_VERSION,
    Profile,
    load_profiles,
    validate_control_target,
    validate_profile,
)
from pg_workload.resources import CpuSample, ResourceGuard, assert_resources_available
from pg_workload.runner import check_min_pg_version, check_profile_requirements, install_profiles, prepare_database
from pg_workload.scheduler import job_recover_on_failure
from pg_workload.state import effective_schedule, load_state, update_job_state

__all__ = [
    "API_VERSION",
    "CpuSample",
    "PgClient",
    "Profile",
    "ResourceGuard",
    "RuntimeConfig",
    "WorkloadError",
    "__version__",
    "assert_resources_available",
    "build_parser",
    "build_runtime_config",
    "bundled_profiles_root",
    "check_min_pg_version",
    "check_profile_requirements",
    "effective_schedule",
    "file_lock",
    "initialize_project",
    "install_profiles",
    "job_recover_on_failure",
    "load_profiles",
    "load_state",
    "prepare_database",
    "save_yaml",
    "update_job_state",
    "validate_control_target",
    "validate_profile",
]
