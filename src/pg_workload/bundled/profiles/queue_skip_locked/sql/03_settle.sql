-- Settle the oldest in-flight tasks, keeping a small failure rate.
WITH picked AS (
    SELECT id
    FROM queue_skip_locked.tasks
    WHERE status = 'processing'
    ORDER BY started_at
    LIMIT 3
    FOR UPDATE SKIP LOCKED
)
UPDATE queue_skip_locked.tasks t
SET status = CASE WHEN random() < 0.05 THEN 'failed' ELSE 'done' END,
    finished_at = clock_timestamp()
FROM picked
WHERE t.id = picked.id;
