from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from pg_workload.common import WorkloadError, resolve_relative_path, save_yaml

PACKAGE_ROOT = Path(__file__).resolve().parent
BUNDLED_ROOT = PACKAGE_ROOT / "bundled"


def bundled_profiles_root() -> Path:
    root = BUNDLED_ROOT / "profiles"
    manifests = sorted(root.glob("*/profile.yml"))
    if not manifests:
        raise WorkloadError("Installed pg-workload package contains no bundled profiles")
    return root


def _copy_asset(source: Path, destination: Path, *, force: bool) -> str:
    if source.is_symlink():
        raise WorkloadError(f"Bundled asset must not be a symlink: {source}")
    if destination.is_symlink():
        raise WorkloadError(f"Refusing to overwrite symlink: {destination}")
    content = source.read_bytes()
    existed = destination.exists()
    if existed:
        if not destination.is_file():
            raise WorkloadError(f"Asset destination is not a file: {destination}")
        if destination.read_bytes() == content:
            return "unchanged"
        if not force:
            raise WorkloadError(
                f"Local asset differs from the packaged version: {destination}. "
                "Re-run init with --force to update immutable assets."
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(f".{destination.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp_path.write_bytes(content)
    os.replace(tmp_path, destination)
    return "updated" if existed else "created"


def _copy_tree(source_root: Path, destination_root: Path, *, force: bool) -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    if destination_root.is_symlink():
        raise WorkloadError(f"Refusing to traverse symlink: {destination_root}")
    destination_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_root.rglob("*")):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        if source.is_symlink():
            raise WorkloadError(f"Bundled asset must not be a symlink: {source}")
        if source.is_dir():
            if destination.is_symlink():
                raise WorkloadError(f"Refusing to traverse symlink: {destination}")
            destination.mkdir(parents=True, exist_ok=True)
            continue
        result = _copy_asset(source, destination, force=force)
        counts[result] += 1
    return counts


def initialize_project(directory: Path, *, force: bool = False) -> dict[str, Any]:
    root = directory.expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise WorkloadError(f"Project path is not a directory: {root}")
    root.mkdir(parents=True, exist_ok=True)

    counts = _copy_tree(bundled_profiles_root(), root / "data", force=force)
    schema_root = BUNDLED_ROOT / "schema"
    schema_counts = _copy_tree(schema_root, root / "schema", force=force)
    for key, value in schema_counts.items():
        counts[key] += value

    for manifest in sorted((root / "data").glob("*/profile.yml")):
        log_dir = manifest.parent / "log"
        if log_dir.is_symlink():
            raise WorkloadError(f"Refusing to use symlink as a log directory: {log_dir}")
        log_dir.mkdir(parents=True, exist_ok=True)

    state_dir = root / "state"
    if state_dir.is_symlink():
        raise WorkloadError(f"Refusing to traverse symlink: {state_dir}")
    state_path = resolve_relative_path(root, "state/workloads.yml", "state file")
    if not state_path.exists():
        save_yaml(state_path, {"profiles": {}})
        counts["created"] += 1

    return {"root": str(root), "assets": counts}
