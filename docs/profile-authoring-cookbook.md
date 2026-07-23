# Profile Authoring Cookbook

This guide explains how to write custom `pg_workload/v1` profiles: the file layout, the
`profile.yml` contract, generator conventions, job semantics, and four complete recipes that
match the bundled profiles `queue_skip_locked`, `jsonb_docs`, `partition_aging`, and
`bloat_vacuum`.

Use it together with the [Profile contract](../README.md#profile-contract) section of the
README and the public JSON Schema (`schema/pg_workload-v1.schema.json`, copied into your
project by `pg-workload init`).

## 1. Profile anatomy

A profile is a directory under `data/<profile>/` in a pg-workload project:

```
data/<profile>/
  profile.yml        # required manifest, api_version: pg_workload/v1
  sql/               # schema, prepare, and pgbench scripts
  generator.py       # optional synthetic data generator (Python, stdlib only)
  log/               # job logs (created by pg-workload, never bundle content here)
```

Rules that apply to every file:

- all paths in `profile.yml` are relative to the profile directory and must stay inside it,
  even through symlinks — escaping paths are validation errors;
- unknown YAML fields are errors at every level, so typos fail fast instead of being ignored;
- `validate` checks the whole contract, including file existence, without touching PostgreSQL:

```bash
pg-workload validate                      # every profile in the project
pg-workload validate --profile my_profile # one profile
```

## 2. `profile.yml` reference

```yaml
api_version: pg_workload/v1     # required, exact string
name: my_profile                # required, [A-Za-z0-9][A-Za-z0-9_.-]*
schema: my_profile              # optional PostgreSQL schema name; defaults to name
description: What this profile emulates.
requires_write: true            # true if any job mutates data
min_pg_version: 12              # optional major-version floor; install rejects older servers
requires_preload_libraries:     # optional; install fails if not in shared_preload_libraries
  - pg_stat_statements

prepare:
  steps: [ ... ]                # see section 3

jobs: [ ... ]                   # see section 4, at least one job is required
```

Conventions used by the bundled profiles (follow them for consistency):

- `schema` equals `name`, so every profile is isolated and `install` can recreate it cleanly;
- every table is created inside that schema and referenced schema-qualified;
- `requires_write: true` is set honestly — orchestrators use it to gate read-only targets;
- `min_pg_version` is declared whenever a script or schema uses a feature newer than the
  PostgreSQL 10 baseline (for example SQL/JSON path queries need 12);
- `description` is one sentence that states the scenario, not the mechanics;
- a `README.md` sits next to `profile.yml` with the scenario, the jobs, the pg_diag sections
  the profile is meant to exercise, and scale/observation guidance.

## 3. Prepare steps

`install` executes `prepare.steps` in declared order. Two step types exist.

### SQL steps

```yaml
- type: sql
  path: sql/schema.sql          # a file inside the profile, OR
- type: sql
  command: "ANALYZE my_schema.t;" # an inline command (mutually exclusive with path)
- type: sql
  path: sql/prepare_batch.sql
  repeat: 25                    # run the step N times
  scale_repeat: true            # and multiply N by --scale (min 1)
- type: sql
  command: "ALTER TABLE my_schema.t SET (autovacuum_vacuum_scale_factor = 0.05);"
  psql_args: ["--no-psqlrc"]    # extra psql arguments for this step
```

SQL steps run through `psql` with `ON_ERROR_STOP=1` as the workload role, so a failed
statement aborts the installation. Use them for schema creation, indexes, small seed data,
and per-table settings. Use `repeat`/`scale_repeat` for scale-aware batches of DDL (see
`many_objects`), which also bounds DDL locks on small stands.

### Generator steps

```yaml
- type: generator
  path: generator.py            # must be a .py file inside the profile
```

A generator is a plain Python program invoked as `python generator.py --scale VALUE` from the
profile directory. It receives the target connection through environment variables:
`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGAPPNAME`, `PGPASSWORD` (or `PGPASSFILE`), and
`PG_WORKLOAD_PSQL` (the selected `psql` binary). Contract and conventions:

- accept `--scale` (positive float); validate it is finite and > 0;
- use only the Python standard library — no third-party imports;
- stream server-side SQL to `psql` (`SELECT setseed(...)`, `INSERT ... SELECT
  generate_series(...)`) so rows never pass through local files;
- use a deterministic seed (`setseed`) and skewed distributions (`power(random(), k)`) so
  datasets are reproducible but realistic;
- enforce a small minimum size per table so `--scale 0.01` still keeps FK structure and
  query selectivity meaningful in CI;
- make the dataset recreatable: the schema SQL drops and recreates objects, so re-running
  `install` with a different `--scale` yields a clean dataset instead of appending;
- print a one-line summary of the generated cardinalities.

Minimal skeleton:

```python
from __future__ import annotations

import argparse
import math
import os
import subprocess


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic my_profile data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    row_count = scaled(100_000, args.scale, 1_000)
    sql = f"""
        SELECT setseed(0.123456);
        INSERT INTO my_profile.items (name, value)
        SELECT 'item ' || g, round((power(random(), 1.7) * 1000)::numeric, 2)
        FROM generate_series(1, {row_count}) AS g;
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )
    print(f"Generated my_profile: items={row_count}")


if __name__ == "__main__":
    main()
```

Warning: a generator executes arbitrary code with the runner account. Only run profiles from
a trusted project directory.

## 4. Jobs

Jobs are the recurring activity. The scheduler re-runs each job every `interval` seconds
(required, minimum 1); `pg-workload run` executes one job (or all of a profile) once.

### pgbench jobs

```yaml
- name: workers
  type: pgbench
  interval: 60
  log: workers.log              # under data/<profile>/log/, defaults to <job name>.log
  clients: 4
  threads: 2                    # must not exceed clients
  transactions: 5               # exactly one of transactions / duration (seconds)
  no_vacuum: true               # passes --no-vacuum to pgbench (default behaviour)
  allow_failure: false          # if true, a failing run is logged but not fatal
  recover_on_failure: true      # scheduler reinstalls the whole profile (schema + data)
                                # after a job failure, then runs the job again
  scripts:                      # explicit list with optional weights, OR
    - path: sql/01_enqueue.sql
      weight: 1
    - path: sql/02_dequeue.sql
      weight: 4
  scripts_glob: ["sql/0[13]_*.sql"]   # glob alternative (mutually exclusive with scripts)
  extra_args: ["--rate=50"]     # raw extra pgbench arguments
```

Notes:

- if neither `scripts` nor `scripts_glob` is given, scripts are auto-discovered via
  `auto_scripts_glob`, defaulting to `sql/[0-9][0-9]_*.sql` and `sql/select_*.sql` — the
  `NN_name.sql` naming convention is what makes zero-config script pickup work;
- script paths may carry a `weight` so one script runs more often than others;
- inside scripts use pgbench `\set var random(a, b)` for per-transaction values and `:var`
  references; each script execution is one transaction by default — use `\begin`/`\end`
  explicitly when you need multi-statement atomicity semantics of your own;
- CLI overrides `--pgbench-duration` / `--pgbench-transactions` / `--pgbench-clients` beat
  profile values for ad-hoc runs.

### psql jobs

```yaml
- name: maintenance
  type: psql
  interval: 1800
  log: maintenance.log
  allow_failure: false
  command: "ANALYZE my_schema.items;"
```

A psql job runs one command as the workload role with `ON_ERROR_STOP=1`; output goes to the
job log. Use psql jobs for maintenance that should be visible in logs and statistics:
`ANALYZE`, `VACUUM`, `REFRESH MATERIALIZED VIEW`, partition aging, requeueing stale rows, or
read-only reporting queries whose output you want captured. `clients`, `threads`, `duration`,
`transactions`, and script fields are rejected for psql jobs.

## 5. Recipe: task queue with `SKIP LOCKED` (`queue_skip_locked`)

Goal: concurrent producers and consumers on a task queue, so lock wait, `pg_stat_activity`,
and row-lock sections of a diagnostic report show real contention without deadlocks.

Schema (`sql/queue-schema.sql`): a `tasks` table with `status
('pending'/'processing'/'done'/'failed')`, `priority`, timestamps, and `attempts`, plus a
partial index on the dequeue path:

```sql
CREATE INDEX tasks_pending_idx ON queue_skip_locked.tasks (priority DESC, id)
    WHERE status = 'pending';
```

The partial index keeps dequeue cheap and shows up in index-usage reports as the hot index.

Workload:

- producer script inserts a small batch of tasks with random priorities;
- a claim script picks a batch `FOR UPDATE SKIP LOCKED` and marks it `processing`;
- a settle script completes the oldest in-flight batch as `done`/`failed` (a small failure
  rate keeps the `failed` state populated). Claim and settle are separate statements — a
  row cannot be updated twice inside one statement (a data-modifying CTE plus an outer
  `UPDATE` of the same rows silently affects 0 rows), and the split models real workers:
  in-flight tasks stay visible in `processing`;
- a psql sweeper job every few minutes requeues `processing` rows whose `started_at` is stale
  and deletes old `done` rows — this models real queue hygiene and generates its own delete
  activity.

Run consumers with `clients: 4` so several backends compete for the head of the queue;
`SKIP LOCKED` is what makes that safe.

Watch in pg_diag: `activity_locks` (row locks on `tasks`), `object_workload` (hot table and
its partial index), `sql_workload` (the dequeue CTE as a top statement).

## 6. Recipe: JSONB documents (`jsonb_docs`)

Goal: document-store access patterns — GIN-indexed containment, path queries, and in-place
`jsonb_set` updates.

Schema (`sql/docs-schema.sql`): a `documents` table with a `jsonb` payload, plus

```sql
CREATE INDEX documents_doc_gin ON jsonb_docs.documents USING gin (doc jsonb_path_ops);
CREATE INDEX documents_status_idx ON jsonb_docs.documents ((doc ->> 'status'));
```

`jsonb_path_ops` is smaller and faster for `@>` containment; the expression index serves the
equality predicate the writer/reader mix uses most.

Workload:

- writer script inserts a document and applies `jsonb_set` to a random existing row (this is
  a full-row update of a wide TOAST-able column — visible in IO and WAL statistics);
- reader script mixes `@>` containment, `jsonb_path_query` extraction, and key aggregation so
  both the GIN and the expression index appear in plans;
- a psql `ANALYZE` job keeps statistics fresh as the distribution shifts.

The reader script uses SQL/JSON path queries, so the profile declares `min_pg_version: 12` —
`install` then fails fast on older servers instead of breaking mid-run.

Watch in pg_diag: `indexes` (GIN vs expression index usage and size), `wal_io_checkpoints`
(WAL volume from JSONB updates), `storage_vacuum` (TOAST tables).

## 7. Recipe: partitioned time-series with aging (`partition_aging`)

Goal: daily range partitions, hot ingest into the current partition, reads that mostly prune
to recent partitions, and lifecycle DDL that detaches/drops expired ones.

Schema (`sql/events-schema.sql`): `events (...) PARTITION BY RANGE (ts)`; the generator
creates daily partitions named `events_YYYY_MM_DD` covering the retention window (30 days
back, 2 days ahead) and fills them with rows skewed toward recent days.

Workload:

- ingest script inserts a batch with `ts = clock_timestamp()` — always the current partition;
- two read scripts with weights: a recent-window query (partition pruning, weight 5) and a
  rare full-history aggregate (all partitions, weight 1);
- a psql aging job (hourly) that creates tomorrow's partition if missing and drops partitions
  older than the retention window, driven by `pg_inherits` lookups on the deterministic
  partition names. Keep it in a single `DO $$ ... $$;` block so it is idempotent.

Watch in pg_diag: `object_workload` (per-partition IO split), `activity_locks` (brief DDL
locks from create/drop), `sql_workload` (plans with vs without pruning).

## 8. Recipe: bloat and vacuum (`bloat_vacuum`)

Goal: accumulate dead tuples on purpose so autovacuum queue, vacuum progress, and table bloat
are observable, then clean up on a schedule.

Schema (`sql/accounts-schema.sql`): an `accounts` table with several secondary indexes and a
`filler` column. Updates touch indexed columns, which defeats HOT updates and multiplies dead
tuples. The indexes are created before the generator runs, and the generator pre-bloats the
already-indexed table with one non-HOT update round — that is exactly what makes the updates
non-HOT from the start.

Workload:

- churn script updates random rows (indexed columns + filler) and inserts/deletes a small
  fraction, so dead tuples grow continuously;
- a psql `VACUUM (ANALYZE)` job every few minutes produces explicit vacuum activity (visible
  in `pg_stat_progress_vacuum` and CSV logs) alongside autovacuum;
- a psql reporting job logs `n_dead_tup`, `n_mod_since_analyze`, and vacuum counts from
  `pg_stat_user_tables` into the job log for a quick before/after comparison.

Watch in pg_diag: `storage_vacuum` (autovacuum queue, dead tuples, xmin horizon),
`maintenance_progress` (vacuum phases), `object_workload` (table size growth vs row count).

## 9. Checklist before committing a profile

1. `pg-workload validate --profile <name>` passes with no errors.
2. `install` is re-runnable: schema SQL drops what it creates; a second `install` yields a
   clean dataset.
3. The generator is stdlib-only, deterministic (`setseed`), has per-table minimums, and
   streams SQL via `PG_WORKLOAD_PSQL`.
4. Every job has a sensible `interval` (hot loops 60–300 s, maintenance ≥ 300 s), and
   `threads <= clients`.
5. pgbench scripts follow `sql/NN_name.sql` or are listed explicitly with weights.
6. `requires_write` matches reality; `requires_preload_libraries` is declared when a metric
   depends on it; `min_pg_version` is declared when a feature needs more than PostgreSQL 10.
7. A `README.md` documents the scenario, jobs, pg_diag watch list, and scale guidance.
8. No dumps, CSV files, archives, or network downloads — everything is generated locally
   (enforced by the project test suite).
9. Logs are referenced by bare file names and land under `data/<profile>/log/`.
