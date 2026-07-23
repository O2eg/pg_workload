# imdb

Analytical read-only workload over a synthetic movie-domain model: multi-way joins,
aggregations, selective lookups, and skewed popularity distributions. An original compact
schema — not the Join Order Benchmark and no IMDB source data (both excluded for licensing
reasons). Use it to exercise the planner and to produce interesting plans for
`auto_explain` and `pg_stat_statements`.

## Objects (at scale 1)

- 10,000 companies; 100,000 people; 100,000 titles; ~1,300,000 fact rows
  (`cast_info`, `movie_keyword`, `movie_company`, `movie_info`)
- Secondary indexes created after the data load

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `analytical_selects` | pgbench | 60 s | five join/aggregation scripts of varying selectivity |

## What to watch in pg_diag

- `sql_workload` — top statements by total/mean time with real join plans
- `object_workload` — sequential vs index scan split on fact tables
- `buffer_cache` — relation caching behaviour under repeated analytical reads
- `snapshot_charts_db` — read I/O rates during the observation window

## Recommended scale and observation window

- Scale 1 for meaningful planning; scale 0.1 still keeps join selectivity sensible.
- 5–10 minutes of scheduled runs; analytical queries dominate `pg_stat_statements`
  quickly because the job interval is 60 s.
