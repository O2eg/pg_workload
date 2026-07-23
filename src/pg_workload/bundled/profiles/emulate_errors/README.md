# emulate_errors

Intentional SQL errors: constraint violations, bad syntax, division by zero, and similar
failures. The job runs with `allow_failure: true`, so errors are expected and logged. Use
it to fill PostgreSQL error logs and transaction rollback statistics
(`pg_stat_database.xact_rollback`) without breaking the workload runner.

## Objects

- `emulate_errors.accounts`, `emulate_errors.transactions` — small fixed seed
  (`--scale` is ignored by design)

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `errors` | pgbench | 60 s | statements that fail in various ways, with `allow_failure` |

## What to watch in pg_diag

- PostgreSQL CSV logs — ERROR/FATAL entries with statements (pg_stand stands collect them)
- `snapshot_delta_workload` — rollback-heavy transaction statistics
- `sql_workload` — failing statements still visible in `pg_stat_statements`

## Recommended scale and observation window

- Any scale (ignored); the seed is intentionally tiny.
- 5 minutes is enough to produce a representative error stream.
