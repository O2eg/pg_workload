from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from pg_workload.common import WorkloadError, csv_list, eprint, file_lock, load_yaml, parse_positive_int, save_yaml
from pg_workload.profiles import Profile


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"profiles": {}}
    return load_yaml(path)


def state_with_profiles_enabled(
    state: dict[str, Any],
    profile_names: list[str],
    *,
    interval_seconds: int | None = None,
) -> dict[str, Any]:
    if interval_seconds is not None:
        interval_seconds = parse_positive_int(interval_seconds, "profile interval")
    desired = copy.deepcopy(state)
    profiles = desired.setdefault("profiles", {})
    for profile_name in sorted(set(profile_names)):
        profile_state = profiles.setdefault(profile_name, {})
        if not isinstance(profile_state, dict):
            raise WorkloadError(f"Invalid state for profile: {profile_name}")
        profile_state["enabled"] = True
        if interval_seconds is not None:
            profile_state["interval"] = interval_seconds
        profile_state.setdefault("jobs", {})
    return desired


def enable_profiles(
    state_path: Path,
    profile_names: list[str],
    *,
    interval_seconds: int | None = None,
) -> None:
    lock_path = state_path.with_name(state_path.name + ".lock")
    with file_lock(lock_path):
        desired = state_with_profiles_enabled(
            load_state(state_path),
            profile_names,
            interval_seconds=interval_seconds,
        )
        save_yaml(state_path, desired)


def update_job_state(
    state_path: Path,
    profile_name: str,
    *,
    enabled: bool | None = None,
    job_name: str | None = None,
    interval: int | None = None,
) -> None:
    if interval is not None:
        interval = parse_positive_int(interval, "interval")
    lock_path = state_path.with_name(state_path.name + ".lock")
    with file_lock(lock_path):
        state = load_state(state_path)
        profiles = state.setdefault("profiles", {})
        profile_state = profiles.setdefault(profile_name, {})
        if enabled is not None and not job_name:
            profile_state["enabled"] = enabled
        jobs = profile_state.setdefault("jobs", {})
        if job_name:
            job_state = jobs.setdefault(job_name, {})
            if enabled is not None:
                job_state["enabled"] = enabled
                if enabled and profile_state.get("enabled") is False:
                    del profile_state["enabled"]
            if interval is not None:
                job_state["interval"] = interval
        elif interval is not None:
            profile_state["interval"] = interval
        save_yaml(state_path, state)


def effective_schedule(
    profiles: dict[str, Profile],
    requested: list[str] | None,
    state: dict[str, Any],
) -> list[tuple[Profile, dict[str, Any], int]]:
    state_profiles = state.get("profiles", {}) or {}
    allowed = set(csv_list(requested))
    schedule: list[tuple[Profile, dict[str, Any], int]] = []

    for profile_name in sorted(state_profiles):
        if allowed and profile_name not in allowed:
            continue
        profile = profiles.get(profile_name)
        if not profile:
            eprint(f"WARNING: state references unknown profile: {profile_name}")
            continue
        profile_state = state_profiles.get(profile_name, {}) or {}
        if not isinstance(profile_state, dict):
            eprint(f"WARNING: invalid state for profile: {profile_name}")
            continue
        profile_enabled = profile_state.get("enabled") is True
        if profile_state.get("enabled") is False:
            continue
        job_states = profile_state.get("jobs", {}) or {}
        if not isinstance(job_states, dict):
            eprint(f"WARNING: invalid jobs state for profile: {profile_name}")
            job_states = {}
        for job in profile.jobs:
            job_name = str(job.get("name"))
            job_state = job_states.get(job_name, {}) or {}
            if not isinstance(job_state, dict):
                eprint(f"WARNING: invalid job state for {profile_name}:{job_name}")
                continue
            if profile_enabled:
                enabled = job_state.get("enabled", True) is not False
            else:
                enabled = job_state.get("enabled") is True
            if not enabled:
                continue
            if "interval" in job_state:
                raw_interval = job_state["interval"]
            elif "interval" in profile_state:
                raw_interval = profile_state["interval"]
            else:
                raw_interval = job.get("interval", 60)
            try:
                interval = parse_positive_int(
                    raw_interval,
                    f"{profile_name}:{job_name}: interval",
                )
            except WorkloadError as exc:
                eprint(f"WARNING: {exc}")
                continue
            schedule.append((profile, job, interval))
    return schedule
