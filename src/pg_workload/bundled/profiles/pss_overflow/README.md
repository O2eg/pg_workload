# pss_overflow

Churn generator for `pg_stat_statements`: thousands of distinct normalized statements
against dozens of generated tables, pushing entries out of the `pg_stat_statements` limit
(`max` is 5000 on pg_stand diagnostic stands). Use it to observe deallocation behaviour and
"top-N misses" in statement reporting.

## Objects

- 50+ tables `pss_overflow.table_N` (count scales with `--scale`, minimum 50)
- `pss_overflow.profile_config` records the generated table count

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `statement_churn` | pgbench | 60 s | per-transaction statements against random generated tables |

## Requirements

- `pg_stat_statements` must be in `shared_preload_libraries` and the extension created
  (declared via `requires_preload_libraries`; `install` fails fast otherwise)

## What to watch in pg_diag

- `sql_workload` — `pg_stat_statements` capabilities and deallocation statistics
- `sql_workload` top-N tables — churn pushes useful statements out of the limit
- `overview` — statement count vs `pg_stat_statements.max`

## Recommended scale and observation window

- Scale 0.1–1 (table count scales; 50 tables minimum).
- 5–10 minutes; distinct-statement count grows with every `statement_churn` cycle.
