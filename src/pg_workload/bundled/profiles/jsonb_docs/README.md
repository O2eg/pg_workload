# jsonb_docs

Document-store workload over a `jsonb` column: GIN-indexed containment queries, jsonpath
extraction, and in-place `jsonb_set` updates of wide documents. Use it to exercise GIN
indexes, TOAST, and the WAL volume produced by JSONB updates.

## Objects

- `jsonb_docs.documents` — 50,000 documents at scale 1, skewed `customer_id` and tags
- `documents_doc_gin` — GIN index with `jsonb_path_ops` (containment)
- `documents_status_idx` — expression index on `(doc ->> 'status')`

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `writers` | pgbench | 60 s | insert documents; `jsonb_set` updates on random rows |
| `readers` | pgbench | 60 s | `@>` containment, `jsonb_path_query`, status aggregation |
| `analyze_docs` | psql | 1800 s | `ANALYZE jsonb_docs.documents` |

## Requirements

- PostgreSQL 12+ (`min_pg_version: 12`) — the reader script uses SQL/JSON path queries

## What to watch in pg_diag

- `indexes` — GIN vs expression index usage and size
- `wal_io_checkpoints` — WAL volume from full-row JSONB updates
- `storage_vacuum` — TOAST storage and dead tuples from updates

## Recommended scale and observation window

- Scale 0.01–0.1 for CI; scale 1 makes GIN vs seq-scan choices visible.
- 5–10 minutes of scheduled runs before a snapshots window.
