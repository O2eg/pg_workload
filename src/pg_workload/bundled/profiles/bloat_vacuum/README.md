# bloat_vacuum

Dead-tuple generation on purpose: updates touch indexed columns (defeating HOT updates),
so dead tuples accumulate in the heap and indexes. A scheduled manual `VACUUM` and a bloat
reporting job make the whole cycle observable. Use it to watch autovacuum queueing, vacuum
progress, and table/index growth versus live row count.

## Objects

- `bloat_vacuum.accounts` — 100,000 rows at scale 1, pre-bloated by one non-HOT update
  round during install
- Secondary indexes on `balance`, `status`, `updated_at` — the columns the churn job updates

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `churn` | pgbench | 60 s | non-HOT updates of random rows plus a small insert/delete tail |
| `vacuum_worker` | psql | 300 s | `VACUUM (ANALYZE) bloat_vacuum.accounts` — explicit vacuum activity |
| `bloat_report` | psql | 600 s | logs `n_dead_tup`, vacuum counts, and timestamps from `pg_stat_user_tables` |

## What to watch in pg_diag

- `storage_vacuum` — dead tuples, autovacuum queue, last vacuum/analyze timestamps
- `maintenance_progress` — vacuum phases while `vacuum_worker` runs
- `object_workload` — table and index size growth versus `n_live_tup`

## Recommended scale and observation window

- Scale 0.01–0.1; bloat accumulates per cycle, so longer runs show more.
- 10–15 minutes to see several churn cycles, at least one manual vacuum, and a bloat
  report entry. Compare `data/bloat_vacuum/log/bloat_report.log` over time.
