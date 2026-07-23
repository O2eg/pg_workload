# pagila

Mixed OLTP over the Pagila DVD-rental model (schema redistributed under its upstream
license, rows generated locally — see `THIRD_PARTY_NOTICES.md`). Balanced
select/insert/update/delete plus maintenance jobs, which makes it a good "realistic
application" background for diagnostics.

## Objects (at scale 1)

- 600 customers; 1,000 films; 4,500 inventory rows; 16,000 rentals; 16,500 payments
- Materialized view `pagila.rental_by_category`

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `main` | pgbench | 60 s | four scripts: select, insert, update, delete |
| `analyze_customer` | psql | 60 s | `ANALYZE pagila.customer` — frequent manual analyze activity |
| `refresh_rental_by_category` | psql | 1800 s | `REFRESH MATERIALIZED VIEW` — periodic heavy maintenance |

## What to watch in pg_diag

- `sql_workload` — a balanced DML mix instead of a single hot query
- `maintenance_progress` / `activity_locks` — the periodic `REFRESH MATERIALIZED VIEW`
  and its locks
- `storage_vacuum` — update/delete churn on rental and payment tables

## Recommended scale and observation window

- Scale 0.1–1; reference cardinalities are modest by design.
- At least 30 minutes to also catch a `REFRESH MATERIALIZED VIEW` cycle; for a quick look,
  run `pg-workload run --profile pagila` and take a one-shot report.
