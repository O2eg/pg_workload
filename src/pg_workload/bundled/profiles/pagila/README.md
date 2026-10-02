# pagila

OLTP on the synthetic DVD-rental model from `pg_perf_bench` v0.6.1
(commit `5eec23ce4c0edf3001bdbdb70339406221a3c903`). The schema, generator formulas,
indexes and workload scripts replace the earlier mixed OLTP/reporting profile.
No upstream dataset or download is required; see `THIRD_PARTY_NOTICES.md`.

## Objects and preparation

At scale 1: 600 customers, 1,000 films, 4,500 inventory rows, 16,000 rentals and
16,500 payments. The materialized view `pagila.rental_by_category` is also populated.
Identifiers are bigint, and customer balance sums use unrestricted numeric values.

`generator.py` describes a load plan executed by `pg_workload.initialization` through
psql: recreate the schema, generate committed batches, reset sequences, build indexes
and constraints, refresh the materialized view and analyze the tables. Table logging
and server durability settings are preserved. `--batch-rows` defaults to 100,000;
generation uses independent deterministic hash streams and does not depend on batch size.

## Jobs

| Job | Interval | Behavior |
|---|---|---|
| `main` | 60 s after completion | pgbench with select/insert/update/delete script weights 50/25/20/5 |
| `analyze_customer` | 60 s | `ANALYZE pagila.customer` |
| `refresh_rental_by_category` | 1800 s | Refresh the materialized view |

The main job defaults to two clients and five script executions per client. Each script
contains several SQL statements; weights are script selection probabilities, not fractions
of individual statements or elapsed time. CLI pgbench overrides can increase the load.
Every insert script records a rental and payment; customer, film, inventory, staff and
store creation have separate probabilities. Store creation uses `SKIP LOCKED` and conflict
handling to support concurrent clients. Reporting queries are not part of the main mix.

## Adaptations for scheduled runs

- Each script sets its own search path; database and role defaults are unchanged.
- `bench_bounds` is a live view of indexed ID bounds, so new rows enter the working set.
- Scripts resolve sequence gaps with indexed lookups. Rental updates/deletes use existing
  IDs; deletes lock their selected rental and tolerate an empty or fully locked table.
- Repeated late fees are capped at the payment column's maximum value.
- Scheduled runs keep pgbench's default random seed. A fixed seed can be supplied through
  job `extra_args` for reproduction, but replaying it may skip duplicate rental inserts.

## What to watch in pg_diag

Use `sql_workload` for the DML mix, `storage_vacuum` for update/delete churn, and
`maintenance_progress` / `activity_locks` for the periodic materialized-view refresh.

## Recommended scale and observation window

Scale 0.1–1 is suitable for a small stand; increase scale and clients to exceed cache.
Observe for at least 30 minutes to include a scheduled refresh cycle.
