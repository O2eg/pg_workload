from __future__ import annotations

import dataclasses
import os
import re
import time
from pathlib import Path

from pg_workload.common import EXCLUDED_DISK_FS_TYPES, WorkloadError
from pg_workload.config import RuntimeConfig


@dataclasses.dataclass(frozen=True)
class DiskMount:
    mount_point: str
    source: str
    fs_type: str
    options: set[str]


@dataclasses.dataclass(frozen=True)
class CpuSample:
    timestamp: float
    total: int
    idle: int


@dataclasses.dataclass(frozen=True)
class ResourceIssue:
    kind: str
    message: str


def format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} TiB"


def unescape_mount_path(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def read_meminfo(path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if ":" not in line:
                    continue
                key, raw_value = line.split(":", 1)
                parts = raw_value.strip().split()
                if not parts:
                    continue
                try:
                    values[key] = int(parts[0]) * 1024
                except ValueError:
                    continue
    except OSError:
        return {}
    return values


def iter_disk_mounts(path: Path = Path("/proc/self/mountinfo")) -> list[DiskMount]:
    mounts: list[DiskMount] = []
    seen: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return mounts

    for line in lines:
        parts = line.split()
        if len(parts) < 10 or "-" not in parts:
            continue
        separator = parts.index("-")
        if separator + 2 >= len(parts):
            continue
        mount_point = unescape_mount_path(parts[4])
        fs_type = parts[separator + 1]
        source = unescape_mount_path(parts[separator + 2])
        options = set(parts[5].split(","))
        if fs_type in EXCLUDED_DISK_FS_TYPES or "ro" in options:
            continue
        if mount_point in seen:
            continue
        seen.add(mount_point)
        try:
            if not Path(mount_point).is_dir():
                continue
        except OSError:
            continue
        mounts.append(DiskMount(mount_point=mount_point, source=source, fs_type=fs_type, options=options))
    return mounts


def read_cpu_sample(path: Path = Path("/proc/stat"), timestamp: float | None = None) -> CpuSample | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline()
    except OSError:
        return None
    parts = first_line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(value) for value in parts[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return CpuSample(timestamp=timestamp or time.time(), total=sum(values), idle=idle)


def cpu_usage_pct(previous: CpuSample, current: CpuSample) -> float | None:
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0:
        return None
    busy_pct = (total_delta - idle_delta) * 100.0 / total_delta
    return max(0.0, min(100.0, busy_pct))


def memory_resource_issues(config: RuntimeConfig) -> list[ResourceIssue]:
    meminfo = read_meminfo()
    total = meminfo.get("MemTotal")
    available = meminfo.get("MemAvailable")
    if not total or available is None:
        return []
    pct_threshold = int(total * config.resource_mem_min_available_pct / 100)
    mb_threshold = config.resource_mem_min_available_mb * 1024 * 1024
    threshold = max(pct_threshold, mb_threshold)
    if available >= threshold:
        return []
    return [
        ResourceIssue(
            "memory",
            "memory available "
            f"{format_bytes(available)} is below required {format_bytes(threshold)} "
            f"(max({config.resource_mem_min_available_pct}% of MemTotal, "
            f"{config.resource_mem_min_available_mb} MiB))",
        )
    ]


def disk_resource_issues(config: RuntimeConfig) -> list[ResourceIssue]:
    issues: list[ResourceIssue] = []
    for mount in iter_disk_mounts():
        try:
            stats = os.statvfs(mount.mount_point)
        except OSError:
            continue
        total = stats.f_blocks * stats.f_frsize
        if total <= 0:
            continue
        available = stats.f_bavail * stats.f_frsize
        used_pct = max(0.0, min(100.0, (1.0 - (available / total)) * 100.0))
        if used_pct <= config.resource_disk_max_used_pct:
            continue
        issues.append(
            ResourceIssue(
                "disk",
                f"disk {mount.mount_point} ({mount.source}, {mount.fs_type}) used "
                f"{used_pct:.1f}% exceeds {config.resource_disk_max_used_pct}% "
                f"(available {format_bytes(available)} of {format_bytes(total)})",
            )
        )
    return issues


def loadavg_cpu_issue(config: RuntimeConfig) -> ResourceIssue | None:
    try:
        load_1m = os.getloadavg()[0]
    except OSError:
        return None
    cpu_count = os.cpu_count() or 1
    normalized_pct = load_1m * 100.0 / cpu_count
    if normalized_pct <= config.resource_cpu_max_pct:
        return None
    return ResourceIssue(
        "cpu",
        f"CPU 1m load average normalized by {cpu_count} CPU(s) is {normalized_pct:.1f}% "
        f"and exceeds {config.resource_cpu_max_pct}%",
    )


class ResourceGuard:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.cpu_samples: list[CpuSample] = []

    def cpu_issues(self, *, use_loadavg_fallback: bool) -> list[ResourceIssue]:
        sample = read_cpu_sample()
        if sample is None:
            issue = loadavg_cpu_issue(self.config) if use_loadavg_fallback else None
            return [issue] if issue else []

        self.cpu_samples.append(sample)
        window = self.config.resource_cpu_window_seconds
        cutoff = sample.timestamp - window
        while len(self.cpu_samples) > 2 and self.cpu_samples[1].timestamp <= cutoff:
            self.cpu_samples.pop(0)

        previous = self.cpu_samples[0]
        elapsed = sample.timestamp - previous.timestamp
        if elapsed >= window:
            usage_pct = cpu_usage_pct(previous, sample)
            if usage_pct is not None and usage_pct > self.config.resource_cpu_max_pct:
                return [
                    ResourceIssue(
                        "cpu",
                        f"CPU average over {elapsed:.0f}s is {usage_pct:.1f}% "
                        f"and exceeds {self.config.resource_cpu_max_pct}%",
                    )
                ]

        if elapsed < window and use_loadavg_fallback:
            issue = loadavg_cpu_issue(self.config)
            return [issue] if issue else []
        return []

    def issues(self, *, use_loadavg_fallback: bool = False) -> list[ResourceIssue]:
        if not self.config.resource_monitor_enabled or self.config.dry_run:
            return []
        return [
            *memory_resource_issues(self.config),
            *disk_resource_issues(self.config),
            *self.cpu_issues(use_loadavg_fallback=use_loadavg_fallback),
        ]


def format_resource_issues(issues: list[ResourceIssue]) -> str:
    return "; ".join(issue.message for issue in issues)


def assert_resources_available(
    config: RuntimeConfig,
    context: str,
    *,
    guard: ResourceGuard | None = None,
    use_loadavg_fallback: bool = True,
) -> None:
    resource_guard = guard or ResourceGuard(config)
    issues = resource_guard.issues(use_loadavg_fallback=use_loadavg_fallback)
    if issues:
        raise WorkloadError(f"Resource guard blocked {context}: {format_resource_issues(issues)}")
