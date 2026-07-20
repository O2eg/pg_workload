from __future__ import annotations

import argparse
import dataclasses
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pg_workload.common import (
    DEFAULT_RESOURCE_CHECK_INTERVAL,
    DEFAULT_RESOURCE_CPU_MAX_PCT,
    DEFAULT_RESOURCE_CPU_WINDOW_SECONDS,
    DEFAULT_RESOURCE_DISK_MAX_USED_PCT,
    DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_MB,
    DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_PCT,
    WorkloadError,
    csv_list,
    resolve_binary,
)


@dataclasses.dataclass
class RuntimeConfig:
    root: Path
    target: str
    pg_major: str
    bin_dir: Path | None
    host: str
    port: int
    dbname: str
    workload_user: str
    workload_password: str | None
    passfile: Path | None
    admin_db: str
    admin_user: str
    admin_password: str | None
    patroni_urls: list[str]
    patroni_role: str
    connect_timeout: int
    sslmode: str | None
    pgbench_clients: int | None
    pgbench_threads: int | None
    pgbench_duration: int | None
    pgbench_transactions: int | None
    scale: float
    libpq_workload_settings: bool
    log_max_bytes: int
    log_backups: int
    log_rotate_on_start: bool
    dry_run: bool
    verbose: bool
    resource_monitor_enabled: bool = True
    resource_disk_max_used_pct: int = DEFAULT_RESOURCE_DISK_MAX_USED_PCT
    resource_mem_min_available_pct: int = DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_PCT
    resource_mem_min_available_mb: int = DEFAULT_RESOURCE_MEM_MIN_AVAILABLE_MB
    resource_cpu_max_pct: int = DEFAULT_RESOURCE_CPU_MAX_PCT
    resource_cpu_window_seconds: int = DEFAULT_RESOURCE_CPU_WINDOW_SECONDS
    resource_check_interval: int = DEFAULT_RESOURCE_CHECK_INTERVAL
    machine_output: bool = False

    @property
    def psql(self) -> str:
        return resolve_binary(self.bin_dir, "psql")

    @property
    def pgbench(self) -> str:
        return resolve_binary(self.bin_dir, "pgbench")


def normalize_patroni_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise WorkloadError("Empty Patroni URL")
    if "://" not in value:
        value = "http://" + value
    return value.rstrip("/")


def discover_patroni_member(urls: list[str], role: str, timeout: int) -> str:
    endpoint = role.strip("/")
    errors: list[str] = []
    for raw_url in urls:
        url = normalize_patroni_url(raw_url)
        check_url = f"{url}/{endpoint}"
        request = urllib.request.Request(check_url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status == 200:
                    parsed = urllib.parse.urlparse(url)
                    if not parsed.hostname:
                        raise WorkloadError(f"Cannot parse Patroni hostname from {url}")
                    return parsed.hostname
                errors.append(f"{check_url}: HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            errors.append(f"{check_url}: HTTP {exc.code}")
        except OSError as exc:
            errors.append(f"{check_url}: {exc}")
    joined = "\n  ".join(errors)
    raise WorkloadError(f"No Patroni member answered as {role}. Checked:\n  {joined}")


def build_runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    root = Path(args.root).resolve()
    pg_major = str(args.pg_major)
    bin_dir = Path(args.bin_dir).resolve() if args.bin_dir else Path(f"/usr/lib/postgresql/{pg_major}/bin")
    host = args.host
    port = int(args.port) if args.port else 5432
    patroni_urls = csv_list(args.patroni_url)
    passfile = Path(args.passfile).expanduser().resolve() if args.passfile else None
    if passfile and not passfile.is_file():
        raise WorkloadError(f"Password file does not exist or is not a regular file: {passfile}")

    if args.target == "local":
        host = host or "/var/run/postgresql"
    elif args.target == "external":
        host = host or "127.0.0.1"
    elif args.target == "patroni":
        if not patroni_urls:
            raise WorkloadError("--patroni-url is required with --target=patroni")
        host = discover_patroni_member(patroni_urls, args.patroni_role, args.connect_timeout)
    else:
        raise WorkloadError(f"Unsupported target: {args.target}")

    return RuntimeConfig(
        root=root,
        target=args.target,
        pg_major=pg_major,
        bin_dir=bin_dir,
        host=host,
        port=port,
        dbname=args.database,
        workload_user=args.workload_user,
        workload_password=args.workload_password,
        passfile=passfile,
        admin_db=args.admin_db,
        admin_user=args.admin_user,
        admin_password=args.admin_password,
        patroni_urls=patroni_urls,
        patroni_role=args.patroni_role,
        connect_timeout=args.connect_timeout,
        sslmode=args.sslmode,
        pgbench_clients=args.pgbench_clients,
        pgbench_threads=args.pgbench_threads,
        pgbench_duration=args.pgbench_duration,
        pgbench_transactions=args.pgbench_transactions,
        scale=args.scale,
        libpq_workload_settings=args.libpq_workload_settings,
        log_max_bytes=args.log_max_mb * 1024 * 1024,
        log_backups=args.log_backups,
        log_rotate_on_start=args.log_rotate_on_start,
        dry_run=args.dry_run,
        verbose=args.verbose,
        resource_monitor_enabled=args.resource_monitor_enabled,
        resource_disk_max_used_pct=args.resource_disk_max_used_pct,
        resource_mem_min_available_pct=args.resource_mem_min_available_pct,
        resource_mem_min_available_mb=args.resource_mem_min_available_mb,
        resource_cpu_max_pct=args.resource_cpu_max_pct,
        resource_cpu_window_seconds=args.resource_cpu_window_seconds,
        resource_check_interval=args.resource_check_interval,
        machine_output=getattr(args, "machine", False),
    )
