from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any

from pg_workload.common import (
    DEFAULT_SCRIPT_PATTERNS,
    IDENT_RE,
    JOB_TYPES,
    WorkloadError,
    as_string_list,
    csv_list,
    is_safe_relative_path,
    load_yaml,
    natural_key,
    parse_positive_int,
    resolve_relative_path,
)

API_VERSION = "pg_workload/v1"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TOP_LEVEL_FIELDS = {
    "api_version",
    "name",
    "schema",
    "description",
    "requires_write",
    "requires_preload_libraries",
    "prepare",
    "jobs",
}
PREPARE_FIELDS = {"steps"}
SQL_STEP_FIELDS = {"type", "path", "command", "repeat", "psql_args"}
GENERATOR_STEP_FIELDS = {"type", "path"}
JOB_FIELDS = {
    "name",
    "type",
    "interval",
    "log",
    "allow_failure",
    "no_vacuum",
    "recover_on_failure",
    "clients",
    "threads",
    "duration",
    "transactions",
    "command",
    "scripts",
    "scripts_glob",
    "auto_scripts_glob",
    "extra_args",
}
SCRIPT_FIELDS = {"path", "weight"}


def _unknown_fields(value: dict[str, Any], allowed: set[str], prefix: str, errors: list[str]) -> None:
    for field in sorted(set(value) - allowed):
        errors.append(f"{prefix}: unknown field {field}")


def _positive_int(value: Any, field_name: str, errors: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{field_name} must be an integer")
        return None
    try:
        return parse_positive_int(value, field_name)
    except WorkloadError as exc:
        errors.append(str(exc))
        return None


def _string_list(value: Any, field_name: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        errors.append(f"{field_name} must be a list of non-empty strings")
        return []
    return value


def _safe_profile_path(profile: Profile, value: Any, field_name: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field_name} must be a non-empty string")
        return None
    if not is_safe_relative_path(value, profile.path):
        errors.append(f"{field_name} must stay inside the profile: {value}")
        return None
    return value


class Profile:
    def __init__(self, path: Path, data: dict[str, Any]):
        self.path = path.resolve()
        self.data = data
        self.name = data.get("name") if isinstance(data.get("name"), str) else ""
        schema = data.get("schema")
        self.schema = schema if isinstance(schema, str) and schema else self.name

    @property
    def prepare_steps(self) -> list[dict[str, Any]]:
        prepare = self.data.get("prepare")
        if not isinstance(prepare, dict) or not isinstance(prepare.get("steps"), list):
            return []
        return list(prepare["steps"])

    @property
    def jobs(self) -> list[dict[str, Any]]:
        jobs = self.data.get("jobs")
        return list(jobs) if isinstance(jobs, list) else []

    def job_by_name(self, name: str) -> dict[str, Any]:
        for job in self.jobs:
            if isinstance(job, dict) and job.get("name") == name:
                return job
        raise WorkloadError(f"Profile {self.name} has no job named {name}")

    def expand_scripts(self, job: dict[str, Any]) -> list[dict[str, Any]]:
        scripts: list[dict[str, Any]] = []
        for script in job.get("scripts", []) or []:
            if isinstance(script, str):
                scripts.append({"path": script})
            elif isinstance(script, dict):
                scripts.append(dict(script))
            else:
                raise WorkloadError(f"Invalid script entry in {self.name}:{job.get('name')}")

        patterns = as_string_list(job.get("scripts_glob"), f"{self.name}:{job.get('name')}: scripts_glob")
        if not scripts and not patterns and job.get("type") == "pgbench":
            patterns = as_string_list(
                job.get("auto_scripts_glob"),
                f"{self.name}:{job.get('name')}: auto_scripts_glob",
            ) or list(DEFAULT_SCRIPT_PATTERNS)

        for pattern in patterns:
            if not is_safe_relative_path(pattern, self.path):
                raise WorkloadError(f"Unsafe script glob in {self.name}:{job.get('name')}: {pattern}")
            matches = sorted(
                glob.glob(str(self.path / pattern)),
                key=lambda item: natural_key(str(Path(item).relative_to(self.path))),
            )
            for match in matches:
                resolved = Path(match).resolve()
                if self.path not in resolved.parents:
                    raise WorkloadError(f"Script glob escapes profile {self.name}: {match}")
                scripts.append({"path": str(resolved.relative_to(self.path))})
        return scripts

    def log_path(self, job: dict[str, Any]) -> Path:
        log_name = job.get("log") or f"{job.get('name', 'job')}.log"
        return resolve_relative_path(self.path, f"log/{log_name}", f"{self.name}: log")


def load_profiles(root: Path, *, allow_empty: bool = False) -> dict[str, Profile]:
    root = root.resolve()
    data_path = root / "data"
    if data_path.is_symlink():
        raise WorkloadError(f"Profiles directory must not be a symlink: {data_path}")
    data_root = data_path.resolve()
    if root not in data_root.parents:
        raise WorkloadError(f"Profiles directory escapes project root: {data_path}")
    profiles: dict[str, Profile] = {}
    for manifest in sorted((root / "data").glob("*/profile.yml")):
        resolved = manifest.resolve()
        if data_root not in resolved.parents:
            raise WorkloadError(f"Profile manifest escapes data directory: {manifest}")
        profile = Profile(resolved.parent, load_yaml(resolved))
        key = profile.name or resolved.parent.name
        if key in profiles:
            raise WorkloadError(f"Duplicate profile name: {key}")
        profiles[key] = profile
    if not profiles and not allow_empty:
        raise WorkloadError(
            f"No workload profiles found under {root / 'data'}. Run 'pg-workload init --directory {root}'."
        )
    return profiles


def selected_profiles(all_profiles: dict[str, Profile], names: list[str] | None) -> list[Profile]:
    requested = csv_list(names)
    if not requested:
        return list(all_profiles.values())
    missing = [name for name in requested if name not in all_profiles]
    if missing:
        raise WorkloadError(f"Unknown profile(s): {', '.join(missing)}")
    return [all_profiles[name] for name in requested]


def validate_control_target(root: Path, profile_name: str, job_name: str | None, *, strict: bool) -> None:
    profiles = load_profiles(root, allow_empty=not strict)
    profile = profiles.get(profile_name)
    if not profile:
        if strict:
            raise WorkloadError(f"Unknown profile: {profile_name}")
        return
    if job_name:
        profile.job_by_name(job_name)


def _validate_prepare(profile: Profile, errors: list[str]) -> None:
    prepare = profile.data.get("prepare", {})
    if not isinstance(prepare, dict):
        errors.append(f"{profile.name}: prepare must be a mapping")
        return
    _unknown_fields(prepare, PREPARE_FIELDS, f"{profile.name}: prepare", errors)
    steps = prepare.get("steps", [])
    if not isinstance(steps, list):
        errors.append(f"{profile.name}: prepare.steps must be a list")
        return
    for index, step in enumerate(steps):
        prefix = f"{profile.name}: prepare.steps[{index}]"
        if not isinstance(step, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        step_type = step.get("type")
        if step_type == "sql":
            _unknown_fields(step, SQL_STEP_FIELDS, prefix, errors)
            has_path = "path" in step
            has_command = "command" in step
            if has_path == has_command:
                errors.append(f"{prefix} must contain exactly one of path or command")
            if has_path:
                path = _safe_profile_path(profile, step["path"], f"{prefix}.path", errors)
                if path and not (profile.path / path).is_file():
                    errors.append(f"{prefix}: missing SQL file {path}")
            if has_command and (not isinstance(step["command"], str) or not step["command"].strip()):
                errors.append(f"{prefix}.command must be a non-empty string")
            if "repeat" in step:
                _positive_int(step["repeat"], f"{prefix}.repeat", errors)
            if "psql_args" in step:
                _string_list(step["psql_args"], f"{prefix}.psql_args", errors)
        elif step_type == "generator":
            _unknown_fields(step, GENERATOR_STEP_FIELDS, prefix, errors)
            path = _safe_profile_path(profile, step.get("path"), f"{prefix}.path", errors)
            if path:
                if Path(path).suffix != ".py":
                    errors.append(f"{prefix}.path must reference a Python file")
                elif not (profile.path / path).is_file():
                    errors.append(f"{prefix}: missing generator file {path}")
        else:
            errors.append(f"{prefix}: unsupported step type {step_type}")


def _validate_job(profile: Profile, job: Any, index: int, seen: set[str], errors: list[str]) -> None:
    prefix = f"{profile.name}: jobs[{index}]"
    if not isinstance(job, dict):
        errors.append(f"{prefix} must be a mapping")
        return
    _unknown_fields(job, JOB_FIELDS, prefix, errors)
    name = job.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        errors.append(f"{prefix}.name must match {NAME_RE.pattern}")
        name = f"#{index}"
    elif name in seen:
        errors.append(f"{profile.name}: duplicate job name {name}")
    else:
        seen.add(name)
    job_prefix = f"{profile.name}:{name}"
    job_type = job.get("type")
    if job_type not in JOB_TYPES:
        errors.append(f"{job_prefix}: unsupported job type {job_type}")

    values: dict[str, int] = {}
    if "interval" not in job:
        errors.append(f"{job_prefix}: interval is required")
    for field in ("interval", "clients", "threads", "duration", "transactions"):
        if field in job:
            parsed = _positive_int(job[field], f"{job_prefix}: {field}", errors)
            if parsed is not None:
                values[field] = parsed
    if "clients" in values and "threads" in values and values["threads"] > values["clients"]:
        errors.append(f"{job_prefix}: threads must not exceed clients")
    for field in ("allow_failure", "no_vacuum", "recover_on_failure"):
        if field in job and not isinstance(job[field], bool):
            errors.append(f"{job_prefix}: {field} must be a boolean")
    if "log" in job:
        log_name = job["log"]
        if not isinstance(log_name, str) or not is_safe_relative_path(f"log/{log_name}", profile.path):
            errors.append(f"{job_prefix}: unsafe log path {log_name}")
    if "extra_args" in job:
        _string_list(job["extra_args"], f"{job_prefix}: extra_args", errors)

    if job_type == "psql":
        if not isinstance(job.get("command"), str) or not job["command"].strip():
            errors.append(f"{job_prefix}: psql job requires command")
        for field in ("clients", "threads", "duration", "transactions", "scripts", "scripts_glob"):
            if field in job:
                errors.append(f"{job_prefix}: {field} is only valid for pgbench jobs")
        return
    if job_type != "pgbench":
        return
    if ("duration" in job) == ("transactions" in job):
        errors.append(f"{job_prefix}: set exactly one of duration or transactions")
    if "command" in job:
        errors.append(f"{job_prefix}: command is only valid for psql jobs")
    if "scripts" in job and "scripts_glob" in job:
        errors.append(f"{job_prefix}: scripts and scripts_glob are mutually exclusive")
    scripts_value = job.get("scripts", [])
    if scripts_value is not None and not isinstance(scripts_value, list):
        errors.append(f"{job_prefix}: scripts must be a list")
    elif isinstance(scripts_value, list):
        for script_index, script in enumerate(scripts_value):
            script_prefix = f"{job_prefix}: scripts[{script_index}]"
            if isinstance(script, str):
                path = script
            elif isinstance(script, dict):
                _unknown_fields(script, SCRIPT_FIELDS, script_prefix, errors)
                path = script.get("path")
                if "weight" in script:
                    _positive_int(script["weight"], f"{script_prefix}.weight", errors)
            else:
                errors.append(f"{script_prefix} must be a path or mapping")
                continue
            _safe_profile_path(profile, path, f"{script_prefix}.path", errors)
    for field in ("scripts_glob", "auto_scripts_glob"):
        for pattern in _string_list(job.get(field), f"{job_prefix}: {field}", errors):
            _safe_profile_path(profile, pattern, f"{job_prefix}: {field}", errors)

    try:
        scripts = profile.expand_scripts(job)
    except WorkloadError as exc:
        errors.append(str(exc))
        return
    if not scripts:
        errors.append(f"{job_prefix}: pgbench job found no scripts")
    for script in scripts:
        path = script.get("path")
        safe_path = _safe_profile_path(profile, path, f"{job_prefix}: script path", errors)
        if safe_path and not (profile.path / safe_path).is_file():
            errors.append(f"{job_prefix}: missing script {safe_path}")


def validate_profile(profile: Profile) -> list[str]:
    errors: list[str] = []
    _unknown_fields(profile.data, TOP_LEVEL_FIELDS, str(profile.path), errors)
    if profile.data.get("api_version") != API_VERSION:
        errors.append(f"{profile.path}: api_version must be {API_VERSION}")
    if not profile.name or not NAME_RE.match(profile.name):
        errors.append(f"{profile.path}: name is required and must match {NAME_RE.pattern}")
    if "schema" in profile.data and (
        not isinstance(profile.data["schema"], str) or not IDENT_RE.match(profile.data["schema"])
    ):
        errors.append(f"{profile.name}: schema must be a PostgreSQL identifier")
    if "description" in profile.data and not isinstance(profile.data["description"], str):
        errors.append(f"{profile.name}: description must be a string")
    if "requires_write" in profile.data and not isinstance(profile.data["requires_write"], bool):
        errors.append(f"{profile.name}: requires_write must be a boolean")
    _string_list(
        profile.data.get("requires_preload_libraries"),
        f"{profile.name}: requires_preload_libraries",
        errors,
    )
    _validate_prepare(profile, errors)

    jobs = profile.data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        errors.append(f"{profile.name or profile.path}: jobs is required and must be a non-empty list")
        return errors
    seen: set[str] = set()
    for index, job in enumerate(jobs):
        _validate_job(profile, job, index, seen, errors)
    return errors
