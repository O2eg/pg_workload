from __future__ import annotations

import dataclasses
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pg_workload.common import WorkloadError, eprint, file_lock, format_command, parse_positive_int
from pg_workload.config import RuntimeConfig
from pg_workload.pg_client import PgClient
from pg_workload.profiles import Profile, load_profiles, validate_profile
from pg_workload.resources import ResourceGuard, format_resource_issues
from pg_workload.state import effective_schedule, load_state


def job_recover_on_failure(job: dict[str, Any]) -> bool:
    return job.get("recover_on_failure", True) is not False


@dataclasses.dataclass
class RunningProcess:
    kind: str
    label: str
    process: subprocess.Popen[Any]
    started_at: float
    profile_name: str
    job_name: str | None = None
    recover_on_failure: bool = True
    stopping_since: float | None = None


def child_env(config: RuntimeConfig) -> dict[str, str]:
    env = os.environ.copy()
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = os.pathsep.join(
            str(Path(entry).resolve()) if entry else entry for entry in env["PYTHONPATH"].split(os.pathsep)
        )
    if config.workload_password:
        env["WORKLOAD_PASSWORD"] = config.workload_password
    if config.admin_password:
        env["WORKLOAD_ADMIN_PASSWORD"] = config.admin_password
    return env


def common_child_args(config: RuntimeConfig) -> list[str]:
    args = [
        "--root",
        str(config.root),
        "--target",
        config.target,
        "--pg-major",
        config.pg_major,
        "--port",
        str(config.port),
        "--database",
        config.dbname,
        "--workload-user",
        config.workload_user,
        "--admin-db",
        config.admin_db,
        "--admin-user",
        config.admin_user,
        "--connect-timeout",
        str(config.connect_timeout),
        "--log-max-mb",
        str(max(1, config.log_max_bytes // (1024 * 1024))),
        "--log-backups",
        str(config.log_backups),
        "--resource-disk-max-used-pct",
        str(config.resource_disk_max_used_pct),
        "--resource-mem-min-available-pct",
        str(config.resource_mem_min_available_pct),
        "--resource-mem-min-available-mb",
        str(config.resource_mem_min_available_mb),
        "--resource-cpu-max-pct",
        str(config.resource_cpu_max_pct),
        "--resource-cpu-window-seconds",
        str(config.resource_cpu_window_seconds),
        "--resource-check-interval",
        str(config.resource_check_interval),
        "--scale",
        str(config.scale),
    ]
    if config.bin_dir:
        args.extend(["--bin-dir", str(config.bin_dir)])
    if config.passfile:
        args.extend(["--passfile", str(config.passfile)])
    if config.host:
        args.extend(["--host", config.host])
    for url in config.patroni_urls:
        args.extend(["--patroni-url", url])
    if config.patroni_role:
        args.extend(["--patroni-role", config.patroni_role])
    if config.sslmode:
        args.extend(["--sslmode", config.sslmode])
    if config.pgbench_clients is not None:
        args.extend(["--pgbench-clients", str(config.pgbench_clients)])
    if config.pgbench_threads is not None:
        args.extend(["--pgbench-threads", str(config.pgbench_threads)])
    if config.pgbench_duration is not None:
        args.extend(["--pgbench-duration", str(config.pgbench_duration)])
    if config.pgbench_transactions is not None:
        args.extend(["--pgbench-transactions", str(config.pgbench_transactions)])
    if not config.libpq_workload_settings:
        args.append("--no-libpq-workload-settings")
    if not config.log_rotate_on_start:
        args.append("--no-log-rotate-on-start")
    if not config.resource_monitor_enabled:
        args.append("--no-resource-monitor")
    if config.dry_run:
        args.append("--dry-run")
    if config.verbose:
        args.append("--verbose")
    return args


def child_command(config: RuntimeConfig, command: str, extra_args: list[str]) -> list[str]:
    return [sys.executable, "-m", "pg_workload", command, *common_child_args(config), *extra_args]


def job_child_command(config: RuntimeConfig, profile_name: str, job_name: str) -> list[str]:
    return child_command(config, "run", ["--profile", profile_name, "--job", job_name])


def recovery_child_command(config: RuntimeConfig, profile_name: str) -> list[str]:
    return child_command(config, "install", ["--profile", profile_name, "--prepare-db"])


def start_child_process(
    config: RuntimeConfig,
    kind: str,
    label: str,
    cmd: list[str],
    profile_name: str,
    job_name: str | None = None,
    recover_on_failure: bool = True,
) -> RunningProcess:
    print(f"Starting {kind} {label}", flush=True)
    if config.verbose or config.dry_run:
        print("$", format_command(cmd, [config.workload_password, config.admin_password]), flush=True)
    process = subprocess.Popen(
        cmd,
        cwd=config.root,
        env=child_env(config),
        start_new_session=True,
    )
    print(f"Started {kind} {label} pid={process.pid}", flush=True)
    return RunningProcess(
        kind=kind,
        label=label,
        process=process,
        started_at=time.time(),
        profile_name=profile_name,
        job_name=job_name,
        recover_on_failure=recover_on_failure,
    )


def signal_process_group(process: subprocess.Popen[Any], signum: int) -> None:
    try:
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signum)
        else:  # pragma: no cover - Windows fallback
            if signum == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
    except ProcessLookupError:
        pass


def stop_running_process(running: RunningProcess, now: float, stop_timeout: int, reason: str) -> None:
    if running.process.poll() is not None:
        return
    if running.stopping_since is None:
        eprint(f"Terminating {running.kind} {running.label}: {reason}")
        signal_process_group(running.process, signal.SIGTERM)
        running.stopping_since = now
        return
    if now - running.stopping_since >= stop_timeout:
        eprint(f"Killing {running.kind} {running.label}: stop timeout exceeded")
        signal_process_group(running.process, signal.SIGKILL)


def stop_all_processes(processes: list[RunningProcess], stop_timeout: int, reason: str) -> None:
    deadline = time.time() + stop_timeout
    for running in processes:
        stop_running_process(running, time.time(), stop_timeout, reason)
    while any(running.process.poll() is None for running in processes) and time.time() < deadline:
        time.sleep(0.2)
    for running in processes:
        if running.process.poll() is None:
            signal_process_group(running.process, signal.SIGKILL)


def run_scheduler(
    client: PgClient,
    root: Path,
    requested: list[str] | None,
    state_path: Path,
    reload_interval: int,
    run_immediately: bool,
    daemon_lock_path: Path,
    recover_on_failure: bool,
    recover_interval: int,
    stop_timeout: int,
) -> None:
    reload_interval = parse_positive_int(reload_interval, "reload interval")
    recover_interval = parse_positive_int(recover_interval, "recover interval")
    stop_timeout = parse_positive_int(stop_timeout, "stop timeout")
    resource_check_interval = parse_positive_int(client.config.resource_check_interval, "resource check interval")
    stop = False

    def handle_stop(signum: int, _frame: object) -> None:
        nonlocal stop
        eprint(f"Received signal {signum}, stopping scheduler")
        stop = True

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    with file_lock(daemon_lock_path, nonblocking=True) as lock_handle:
        lock_handle.seek(0)
        lock_handle.truncate()
        lock_handle.write(str(os.getpid()))
        lock_handle.flush()

        next_runs: dict[tuple[str, str], float] = {}
        known_intervals: dict[tuple[str, str], int] = {}
        running_jobs: dict[tuple[str, str], RunningProcess] = {}
        running_recoveries: dict[str, RunningProcess] = {}
        recovery_due: dict[str, float] = {}
        failure_counts: dict[tuple[str, str], int] = {}
        last_reload = 0.0
        last_resource_check = 0.0
        resource_block_reason: str | None = None
        resource_guard = ResourceGuard(client.config)
        schedule: list[tuple[Profile, dict[str, Any], int]] = []

        print(f"Scheduler started. State file: {state_path}. Lock file: {daemon_lock_path}")
        try:
            while not stop:
                now = time.time()

                if (
                    client.config.resource_monitor_enabled
                    and not client.config.dry_run
                    and now - last_resource_check >= resource_check_interval
                ):
                    last_resource_check = now
                    resource_reason = format_resource_issues(resource_guard.issues(use_loadavg_fallback=True))
                    if resource_reason:
                        if resource_block_reason is None:
                            eprint(
                                "Resource guard triggered: "
                                f"{resource_reason}; stopping running workload tasks and blocking new starts"
                            )
                        resource_block_reason = resource_reason
                        for running in [*running_jobs.values(), *running_recoveries.values()]:
                            stop_running_process(
                                running,
                                now,
                                stop_timeout,
                                f"resource guard: {resource_reason}",
                            )
                    elif resource_block_reason:
                        eprint("Resource guard recovered; resuming workload starts")
                        resource_block_reason = None

                for key, running in list(running_jobs.items()):
                    returncode = running.process.poll()
                    if returncode is None:
                        if running.stopping_since:
                            stop_running_process(running, now, stop_timeout, "disabled or stopping")
                        continue
                    del running_jobs[key]
                    interval = known_intervals.get(key, 60)
                    if running.stopping_since is not None:
                        eprint(f"Stopped job {running.label} with exit code {returncode}")
                    elif returncode == 0:
                        failure_counts[key] = 0
                        print(f"Job finished {running.label} exit=0", flush=True)
                    else:
                        failures = failure_counts.get(key, 0) + 1
                        failure_counts[key] = failures
                        eprint(f"Job failed {running.label} exit={returncode} failures={failures}")
                        if recover_on_failure and running.recover_on_failure:
                            recovery_due[running.profile_name] = now
                        elif recover_on_failure:
                            eprint(f"Recovery skipped for {running.label}: recover_on_failure=false")
                    if key in known_intervals:
                        next_runs[key] = time.time() + interval

                for profile_name, running in list(running_recoveries.items()):
                    returncode = running.process.poll()
                    if returncode is None:
                        if running.stopping_since:
                            stop_running_process(running, now, stop_timeout, "scheduler stopping")
                        continue
                    del running_recoveries[profile_name]
                    if running.stopping_since is not None:
                        eprint(f"Stopped recovery {running.label} with exit code {returncode}")
                    elif returncode == 0:
                        print(f"Recovery finished {profile_name} exit=0", flush=True)
                        recovery_due.pop(profile_name, None)
                        for key in list(next_runs):
                            if key[0] == profile_name:
                                next_runs[key] = time.time()
                    else:
                        eprint(f"Recovery failed {profile_name} exit={returncode}; retry in {recover_interval}s")
                        recovery_due[profile_name] = time.time() + recover_interval

                if now - last_reload >= reload_interval:
                    try:
                        profiles = load_profiles(root)
                        validation_errors = [
                            error for profile in profiles.values() for error in validate_profile(profile)
                        ]
                        if validation_errors:
                            raise WorkloadError("Invalid workload profiles:\n" + "\n".join(validation_errors))
                        state = load_state(state_path)
                        schedule = effective_schedule(profiles, requested, state)
                        active_keys = {(profile.name, str(job.get("name"))) for profile, job, _ in schedule}

                        for profile, job, interval in schedule:
                            key = (profile.name, str(job.get("name")))
                            if key not in next_runs:
                                next_runs[key] = now if run_immediately else now + interval
                            elif known_intervals.get(key) != interval:
                                next_runs[key] = now + interval

                        for key in list(next_runs):
                            if key not in active_keys:
                                del next_runs[key]
                                known_intervals.pop(key, None)
                                failure_counts.pop(key, None)
                                running = running_jobs.get(key)
                                if running:
                                    stop_running_process(running, now, stop_timeout, "job disabled")

                        active_profiles = {profile.name for profile, _, _ in schedule}
                        for profile_name, running in list(running_recoveries.items()):
                            if profile_name not in active_profiles:
                                stop_running_process(running, now, stop_timeout, "profile disabled")
                                recovery_due.pop(profile_name, None)

                        known_intervals = {
                            (profile.name, str(job.get("name"))): interval for profile, job, interval in schedule
                        }
                        last_reload = now
                    except Exception as exc:
                        eprint(f"Scheduler reload failed: {exc}")
                        last_reload = now

                scheduled_profiles = {profile.name for profile, _, _ in schedule}
                for profile_name, due_at in list(recovery_due.items()):
                    if profile_name not in scheduled_profiles or profile_name in running_recoveries:
                        continue
                    if now < due_at:
                        continue
                    if resource_block_reason:
                        continue
                    resource_reason = format_resource_issues(resource_guard.issues(use_loadavg_fallback=True))
                    if resource_reason:
                        resource_block_reason = resource_reason
                        eprint(f"Resource guard blocked starting recovery {profile_name}: {resource_reason}")
                        for running in [*running_jobs.values(), *running_recoveries.values()]:
                            stop_running_process(
                                running,
                                now,
                                stop_timeout,
                                f"resource guard: {resource_reason}",
                            )
                        continue
                    try:
                        running_recoveries[profile_name] = start_child_process(
                            client.config,
                            "recovery",
                            profile_name,
                            recovery_child_command(client.config, profile_name),
                            profile_name,
                        )
                    except OSError as exc:
                        eprint(f"Failed to start recovery {profile_name}: {exc}")
                        recovery_due[profile_name] = time.time() + recover_interval

                for profile, job, interval in schedule:
                    key = (profile.name, str(job.get("name")))
                    if profile.name in running_recoveries or key in running_jobs:
                        continue
                    if now < next_runs.get(key, now + interval):
                        continue
                    if resource_block_reason:
                        continue
                    label = f"{profile.name}:{job.get('name')}"
                    resource_reason = format_resource_issues(resource_guard.issues(use_loadavg_fallback=True))
                    if resource_reason:
                        resource_block_reason = resource_reason
                        eprint(f"Resource guard blocked starting job {label}: {resource_reason}")
                        for running in [*running_jobs.values(), *running_recoveries.values()]:
                            stop_running_process(
                                running,
                                now,
                                stop_timeout,
                                f"resource guard: {resource_reason}",
                            )
                        continue
                    try:
                        running_jobs[key] = start_child_process(
                            client.config,
                            "job",
                            label,
                            job_child_command(client.config, profile.name, str(job.get("name"))),
                            profile.name,
                            str(job.get("name")),
                            job_recover_on_failure(job),
                        )
                    except OSError as exc:
                        eprint(f"Failed to start job {label}: {exc}")
                        next_runs[key] = time.time() + interval

                time.sleep(0.5)
        finally:
            stop_all_processes(
                [*running_jobs.values(), *running_recoveries.values()],
                stop_timeout,
                "scheduler exit",
            )
