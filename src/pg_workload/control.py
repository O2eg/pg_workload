"""Owned foreground-scheduler lifecycle used by humans and pg_play."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pg_workload.common import WorkloadError, file_lock
from pg_workload.config import RuntimeConfig
from pg_workload.scheduler import child_env, common_child_args


class WorkloadOwnershipError(WorkloadError):
    """A PID file does not identify a scheduler owned by this project."""


def _pid(lock_path: Path) -> int | None:
    try:
        value = int(lock_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return None
    return value if value > 0 else None


def _cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]


def _owned(pid: int, root: Path) -> bool:
    command = _cmdline(pid)
    return (
        bool(command)
        and "-m" in command
        and "pg_workload" in command
        and "scheduler" in command
        and str(root.resolve()) in command
    )


def scheduler_status(root: Path, lock_path: Path, log_path: Path) -> dict[str, Any]:
    pid = _pid(lock_path)
    running = pid is not None and _owned(pid, root)
    return {
        "state": "running" if running else "stopped",
        "running": running,
        "pid": pid if running else None,
        "stale_pid": pid if pid is not None and not running else None,
        "owned": running,
        "root": str(root.resolve()),
        "lock_file": str(lock_path),
        "log_file": str(log_path),
    }


def _clear_stale_pid(lock_path: Path, expected_pid: int) -> None:
    with file_lock(lock_path, nonblocking=True) as handle:
        handle.seek(0)
        current = handle.read().strip()
        if current == str(expected_pid) and not _cmdline(expected_pid):
            handle.seek(0)
            handle.truncate()
            handle.flush()


def _scheduler_command(config: RuntimeConfig, args: Any) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pg_workload",
        "scheduler",
        *common_child_args(config),
        "--state-file",
        args.state_file,
        "--daemon-lock-file",
        args.daemon_lock_file,
        "--reload-interval",
        str(args.reload_interval),
        "--recover-interval",
        str(args.recover_interval),
        "--stop-timeout",
        str(args.stop_timeout),
    ]
    for profile in args.profiles or []:
        command.extend(["--profile", profile])
    if args.run_immediately:
        command.append("--run-immediately")
    if not args.recover_on_failure:
        command.append("--no-recover-on-failure")
    return command


def start_scheduler(
    config: RuntimeConfig,
    args: Any,
    lock_path: Path,
    log_path: Path,
) -> dict[str, Any]:
    current = scheduler_status(config.root, lock_path, log_path)
    if current["running"]:
        raise WorkloadError(f"Scheduler is already running with pid {current['pid']}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            _scheduler_command(config, args),
            cwd=config.root,
            env=child_env(config),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + args.start_timeout
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise WorkloadError(f"Scheduler exited before readiness with code {return_code}; see {log_path}")
        status = scheduler_status(config.root, lock_path, log_path)
        if status["running"] and status["pid"] == process.pid:
            return status
        if status["running"] and status["pid"] != process.pid:
            process.terminate()
            raise WorkloadError(f"Another scheduler acquired the lock with pid {status['pid']}")
        time.sleep(0.05)
    process.terminate()
    raise WorkloadError(f"Scheduler did not become ready within {args.start_timeout}s")


def stop_scheduler(
    root: Path,
    lock_path: Path,
    log_path: Path,
    timeout: float,
) -> dict[str, Any]:
    pid = _pid(lock_path)
    if pid is None:
        return scheduler_status(root, lock_path, log_path)
    if not _owned(pid, root):
        if _cmdline(pid):
            raise WorkloadOwnershipError(f"Refusing to signal pid {pid}: it is not a pg-workload scheduler for {root}")
        _clear_stale_pid(lock_path, pid)
        return scheduler_status(root, lock_path, log_path)
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _cmdline(pid):
            _clear_stale_pid(lock_path, pid)
            return scheduler_status(root, lock_path, log_path)
        time.sleep(0.05)
    raise WorkloadError(f"Scheduler pid {pid} did not stop within {timeout}s")
