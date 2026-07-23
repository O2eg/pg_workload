# simple_stock_spec_symbols

The same write-heavy CRUD shape as `simple_stock`, but with hostile identifiers and values:
quoted table names with punctuation and control characters, Unicode data, and parser edge
cases. Use it to verify that reporting, logging, and monitoring pipelines survive
non-trivial identifiers instead of breaking rendering or CSV exports.

## Objects

- `"Aufträge_1"`, `"Aufträge_2"` — quoted Unicode table names (same cardinalities as
  `simple_stock` at scale 1)
- `"Stock_$#@.&\n\r_items"` — punctuation and control characters in the table name

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `main` | pgbench | 1800 s | the same insert/update/delete/join mix as `simple_stock`, over the hostile schema |

## What to watch in pg_diag

- `object_workload` — quoted/Unicode identifiers in table listings
- `sql_workload` — statement text with escaped identifiers
- `overview` / HTML rendering — names must not break layout or exports

## Recommended scale and observation window

- Scale 0.01–0.1; the point is identifier handling, not volume.
- One or two `main` cycles are enough; the default interval is 30 minutes, so prefer
  `pg-workload run --profile simple_stock_spec_symbols` for an on-demand pass.
