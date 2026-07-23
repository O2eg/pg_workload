-- Claim a batch of pending tasks. A separate settle step (03_settle.sql)
-- completes them, so in-flight work is visible in the 'processing' state.
WITH picked AS (
    SELECT id
    FROM queue_skip_locked.tasks
    WHERE status = 'pending'
    ORDER BY priority DESC, id
    LIMIT 3
    FOR UPDATE SKIP LOCKED
)
UPDATE queue_skip_locked.tasks t
SET status = 'processing',
    started_at = clock_timestamp(),
    attempts = t.attempts + 1
FROM picked
WHERE t.id = picked.id;
