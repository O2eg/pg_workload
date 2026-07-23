# queue_skip_locked

Concurrent producer/consumer task queue built on `SELECT ... FOR UPDATE SKIP LOCKED`.
Producers enqueue batches, consumers claim the highest-priority pending tasks and settle
them, and a sweeper job requeues stale claims and purges old history. Use it to generate
real row-lock contention without deadlocks.

## Objects

- `queue_skip_locked.tasks` — 20,000 pending + 5,000 done tasks at scale 1
- Partial index `tasks_pending_idx (priority DESC, id) WHERE status = 'pending'` —
  the hot dequeue path

## Jobs

| Job | Type | Interval | What it does |
|---|---|---|---|
| `producer` | pgbench | 60 s | insert a 25-task batch with skewed priorities |
| `consumer` | pgbench | 60 s | claim a batch `FOR UPDATE SKIP LOCKED` (weight 3), then settle the oldest in-flight batch as done/failed (weight 2) |
| `sweeper` | psql | 600 s | requeue `processing` tasks stale for 10 min; delete `done`/`failed` older than 1 day |

Claim and settle are separate scripts: a row cannot be updated twice inside one statement,
and the split keeps in-flight work visible in the `processing` state.

## What to watch in pg_diag

- `activity_locks` — row locks and waiting backends on `tasks`
- `object_workload` — hot table and its partial index
- `sql_workload` — the dequeue CTE as a top statement

## Recommended scale and observation window

- Scale 0.01–0.1; contention comes from concurrency (4 consumer clients), not volume.
- 5–10 minutes to see claim/settle cycles; 10+ minutes to also catch a sweeper requeue.
