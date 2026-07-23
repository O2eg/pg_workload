# many_objects

Metadata-heavy workload: many schemas, partitioned tables, and subpartitions created in
scale-aware SQL batches. Use it to see how catalogs, relcache, and diagnostic queries
behave when the database contains thousands of relations instead of dozens.

## Objects

- `many_objects_*` schemas with partitioned and subpartitioned tables; batch count scales
  with `--scale` via `scale_repeat` (25 batches at scale 1)

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `metadata_scan` | pgbench | 600 s | catalog and information_schema queries over the object farm |

## What to watch in pg_diag

- `cluster_inventory` — relation counts per schema
- `sql_workload` — cost of catalog queries on a crowded catalog
- report collection time itself — large catalogs slow down metadata queries

## Recommended scale and observation window

- Scale 0.1–1. Note `scale_repeat` multiplies DDL batches, so scale 1 creates many objects;
  keep scale low on small stands.
- One `metadata_scan` cycle (interval 600 s) inside a snapshots window is enough; run it
  on demand with `pg-workload run --profile many_objects` if you do not want to wait.
