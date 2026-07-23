# simple_stock

Write-heavy CRUD over three related stock tables. This is the baseline "busy OLTP shop"
profile: constant inserts, updates, deletes, and a join/aggregate read — enough to make every
core section of a diagnostic report show live data.

## Objects

- `simple_stock.order_items_1` — 150,000 product groups at scale 1
- `simple_stock.order_items_2` — 1,000,000 SKUs at scale 1
- `simple_stock.stock_items` — 1,000,000 stock rows at scale 1, skewed FK distribution

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `main` | pgbench | 60 s | batch insert, update and delete by random groups, then a 3-table join/aggregate |

## What to watch in pg_diag

- `sql_workload` — the DML batch and the join query as top statements
- `object_workload` — hot `stock_items` table and its indexes
- `storage_vacuum` — dead tuples and autovacuum on a churning table
- `wal_io_checkpoints` — steady WAL volume from DML

## Recommended scale and observation window

- Scale 1 is the reference size; scale 0.01–0.1 is enough for CI and small stands.
- Run the scheduler for at least 5–10 minutes so several `main` cycles land inside a
  `pg-diag snapshots` window (default 30 s is enough to catch one cycle at interval 60 s).
