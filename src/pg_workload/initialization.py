"""Small, serial psql loader for the bundled Pagila and IMDb load plans.

Each data batch commits independently. Indexes and constraints are installed after
the data; all tables keep normal logging and server durability settings.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoadTask:
    name: str
    sql: str
    count: int | None = None
    depends_on: tuple[str, ...] = ()
    max_rows_per_key: int = 1


@dataclass(frozen=True)
class LoadPlan:
    schemas: tuple[str, ...]
    schema_sql: str
    data: tuple[LoadTask, ...]
    indexes: tuple[LoadTask, ...]
    constraints: tuple[LoadTask, ...] = ()
    prepare_sql: str = ""
    after_data_sql: str = ""
    finalize_sql: str = ""


def read_sql_tasks(path: Path) -> tuple[LoadTask, ...]:
    return tuple(LoadTask(**item) for item in json.loads(path.read_text(encoding="utf-8")))


def ordered_tasks(tasks: tuple[LoadTask, ...]) -> tuple[LoadTask, ...]:
    pending = {task.name: task for task in tasks}
    if len(pending) != len(tasks):
        raise ValueError("Load task names must be unique within a phase")
    for task in tasks:
        if not task.name or not task.sql.strip() or task.max_rows_per_key < 1:
            raise ValueError("Invalid load task")
        if task.count is not None and (type(task.count) is not int or not 0 <= task.count <= 2**63 - 1):
            raise ValueError(f"Invalid row count for {task.name}")
        if not set(task.depends_on) <= pending.keys():
            raise ValueError(f"Unknown dependencies for {task.name}")
    ordered = []
    while pending:
        ready = [task for task in pending.values() if not set(task.depends_on) & pending.keys()]
        if not ready:
            raise ValueError("Load task dependencies contain a cycle")
        for task in ready:
            ordered.append(task)
            del pending[task.name]
    return tuple(ordered)


def batches(task: LoadTask, batch_rows: int) -> Iterator[tuple[str, str]]:
    """Render only numeric bounds in the trusted, parameterized data statements."""
    if batch_rows < 1:
        raise ValueError("batch-rows must be positive")
    if task.count is None:
        yield task.name, task.sql
        return
    size = max(1, batch_rows // task.max_rows_per_key)
    for first in range(1, task.count + 1, size):
        last = min(task.count, first + size - 1)
        values = {"1": str(first), "2": str(last)}
        sql = re.sub(r"\$([12])\b", lambda match, values=values: values[match[1]], task.sql)
        yield f"{task.name} [{first}..{last}]", sql


def run_plan(plan: LoadPlan, *, batch_rows: int = 100_000) -> None:
    # Validate the entire plan before replacing any existing schema.
    if batch_rows < 1:
        raise ValueError("batch-rows must be positive")
    if not plan.schemas or not plan.schema_sql.strip():
        raise ValueError("A load plan needs schemas and DDL")
    for schema in plan.schemas:
        if (
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema)
            or schema in {"public", "information_schema"}
            or schema.startswith("pg_")
        ):
            raise ValueError(f"Invalid profile schema: {schema}")
    phases = [(name, ordered_tasks(getattr(plan, name))) for name in ("data", "indexes", "constraints")]
    search_path = ", ".join(f'"{schema}"' for schema in plan.schemas) + ", public"
    command = [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"]

    def execute(label: str, sql: str) -> None:
        if not sql.strip():
            return
        try:
            subprocess.run(
                command,
                # asyncpg load tasks may omit a trailing semicolon. Terminate the
                # statement on its own line (also safe after a trailing SQL comment).
                input=f"SET search_path TO {search_path};\nBEGIN;\n{sql}\n;\nCOMMIT;\n",
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Loading failed at {label} (psql exit {exc.returncode}); reinstall to retry") from exc

    print(f"Initializing {', '.join(plan.schemas)} (batch rows: {batch_rows})", flush=True)
    reset = "\n".join(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;' for schema in plan.schemas)
    execute("schema", reset + "\n" + plan.schema_sql)
    execute("prepare", plan.prepare_sql)
    for phase, tasks in phases:
        for task in tasks:
            for label, sql in batches(task, batch_rows):
                execute(f"{phase}: {label}", sql)
            print(f"Loaded {phase}: {task.name}", flush=True)
        if phase == "data":
            execute("after data", plan.after_data_sql)
    execute("finalize", plan.finalize_sql)
    schemas_sql = ", ".join(f"'{schema}'" for schema in plan.schemas)
    execute(
        "analyze",
        f"""DO $$ DECLARE relation record; BEGIN
        FOR relation IN
            SELECT n.nspname, c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ({schemas_sql}) AND c.relkind IN ('r', 'p', 'm')
        LOOP
            EXECUTE format('ANALYZE %I.%I', relation.nspname, relation.relname);
        END LOOP;
        END $$;""",
    )


def generator_main(factory: Callable[[float], LoadPlan]) -> None:
    parser = argparse.ArgumentParser(description="Initialize synthetic profile data in committed SQL batches")
    parser.add_argument("--scale", type=float, required=True)
    parser.add_argument("--batch-rows", type=int, default=100_000)
    args = parser.parse_args()
    try:
        run_plan(factory(args.scale), batch_rows=args.batch_rows)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")
