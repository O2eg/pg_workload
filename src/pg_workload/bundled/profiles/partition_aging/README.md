# partition_aging

Daily-partitioned time-series with a lifecycle: hot ingest into the current partition,
reads that mostly prune to recent partitions, and an aging job that creates tomorrow's
partition and drops expired ones. Use it to observe partition pruning, per-partition
statistics, and DDL (create/drop) activity under load.

## Objects

- `partition_aging.events` — range-partitioned by `ts`; 33 daily partitions
  (30 days back, today, 2 days ahead), named `events_YYYY_MM_DD`
- 200,000 events at scale 1, skewed toward recent days
- `events_kind_ts_idx (kind, ts)` created on the parent (per-partition indexes)

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `ingest` | pgbench | 60 s | insert a 100-row batch into the current partition |
| `readers` | pgbench | 60 s | recent-window reads with pruning (weight 5), rare full-history aggregate (weight 1) |
| `aging` | psql | 3600 s | idempotent `DO` block: create tomorrow's partition, drop partitions older than 30 days |

## What to watch in pg_diag

- `object_workload` — per-partition IO split (hot current partition vs cold history)
- `activity_locks` — brief DDL locks from partition create/drop
- `sql_workload` — plans with partition pruning vs full scans of all partitions

## Recommended scale and observation window

- Scale 0.01–0.1; partition count is fixed (33), only row volume scales.
- 5–10 minutes for ingest/read cycles; the aging job runs hourly — trigger it on demand
  with `pg-workload run --profile partition_aging --job aging`.
