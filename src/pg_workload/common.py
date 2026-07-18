from __future__ import annotations

import argparse
import contextlib
import math
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Linux fallback
    fcntl = None

try:
    import yaml
except ImportError as exc:  # pragma: no cover - startup guard
    raise SystemExit("PyYAML is required. Install it with: python3 -m pip install PyYAML") from exc


DEFAULT_PG_MAJOR = "18"
DEFAULT_DB = "workload_db"
DEFAULT_USER = "workload_user"
DEFAULT_STATE_FILE = "state/workloads.yml"
DEFAULT_DAEMON_LOCK_FILE = "state/scheduler.lock"
DEFAULT_LOG_MAX_MB = 100
DEFAULT_LOG_BACKUPS = 10
DEFAULT_PGBENCH_CLIENTS = 2
DEFAULT_PGBENCH_THREADS = 2
DEFAULT_SCRIPT_PATTERNS = ("sql/[0-9][0-9]_*.sql", "sql/select_*.sql")
DEFAULT_RESOURCE_DISK_MAX_USED_PCT = 90
DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_PCT = 10
DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_MB = 2048
DEFAULT_RESOURCE_CPU_MAX_PCT = 90
DEFAULT_RESOURCE_CPU_WINDOW_SECONDS = 60
DEFAULT_RESOURCE_CHECK_INTERVAL = 5
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
JOB_TYPES = {"pgbench", "psql"}
EXCLUDED_DISK_FS_TYPES = {
    "autofs",
    "binfmt_misc",
    "bpf",
    "cgroup",
    "cgroup2",
    "configfs",
    "debugfs",
    "devpts",
    "devtmpfs",
    "efivarfs",
    "fusectl",
    "hugetlbfs",
    "mqueue",
    "nsfs",
    "proc",
    "pstore",
    "rpc_pipefs",
    "securityfs",
    "squashfs",
    "sysfs",
    "tracefs",
}


class WorkloadError(RuntimeError):
    pass


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def csv_list(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return result


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parse_positive_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkloadError(f"{field_name} must be an integer") from exc
    if parsed <= 0:
        raise WorkloadError(f"{field_name} must be greater than zero")
    return parsed


def positive_int_arg(value: str) -> int:
    try:
        return parse_positive_int(value, "value")
    except WorkloadError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def positive_float_arg(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a finite number greater than zero")
    return parsed


def non_negative_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be greater than or equal to zero")
    return parsed


def percent_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 0 or parsed > 100:
        raise argparse.ArgumentTypeError("value must be between 0 and 100")
    return parsed


def redact_text(value: str, secrets: list[str | None]) -> str:
    redacted = value
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        redacted = redacted.replace(str(secret), "***")
    return redacted


def redact_command(cmd: list[str], secrets: list[str | None]) -> list[str]:
    redacted = [redact_text(str(part), secrets) for part in cmd]
    for index, part in enumerate(redacted[:-1]):
        if part in {"--admin-password", "--workload-password"}:
            redacted[index + 1] = "***"
        elif part.startswith("--admin-password="):
            redacted[index] = "--admin-password=***"
        elif part.startswith("--workload-password="):
            redacted[index] = "--workload-password=***"
    return redacted


def format_command(cmd: list[str], secrets: list[str | None] | None = None) -> str:
    return shlex.join(redact_command(cmd, secrets or []))


def libpq_options(settings: dict[str, str]) -> str:
    return " ".join(shlex.join(["-c", f"{name}={value}"]) for name, value in settings.items())


def merge_pgoptions(existing: str | None, settings: dict[str, str]) -> str:
    options = libpq_options(settings)
    return " ".join(part for part in (existing or "", options) if part)


def safe_extension_name(value: str) -> str:
    if not IDENT_RE.match(value):
        raise WorkloadError(f"Unsafe extension name: {value}")
    return quote_ident(value)


def as_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return csv_list([value])
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise WorkloadError(f"{field_name} must be a string or list of strings")


def is_safe_relative_path(value: str, root: Path | None = None) -> bool:
    if not value:
        return False
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return False
    if root is None:
        return True
    root = root.resolve()
    target = (root / path).resolve()
    return target == root or root in target.parents


def resolve_relative_path(root: Path, value: str, field_name: str) -> Path:
    if not is_safe_relative_path(value, root):
        raise WorkloadError(f"{field_name} must stay inside {root}: {value}")
    return (root / value).resolve()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise WorkloadError(f"YAML document must be a mapping: {path}")
    return data


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=True)
    os.replace(tmp_path, path)


@contextlib.contextmanager
def file_lock(path: Path, *, nonblocking: bool = False) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover - Linux uses fcntl, this keeps imports portable.
        lock_dir = path.with_name(path.name + ".lockdir")
        while True:
            try:
                lock_dir.mkdir()
                break
            except FileExistsError as exc:
                if nonblocking:
                    raise WorkloadError(f"Lock is already held: {path}") from exc
                time.sleep(0.1)
        handle = path.open("a+", encoding="utf-8")
        try:
            yield handle
        finally:
            handle.close()
            try:
                lock_dir.rmdir()
            except OSError:
                pass
        return

    handle = path.open("a+", encoding="utf-8")
    flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
    try:
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError as exc:
            raise WorkloadError(f"Lock is already held: {path}") from exc
        yield handle
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def resolve_binary(bin_dir: Path | None, name: str) -> str:
    if bin_dir:
        candidate = bin_dir / name
        if candidate.exists():
            return str(candidate)
    return name
