DROP SCHEMA IF EXISTS queue_skip_locked CASCADE;
CREATE SCHEMA queue_skip_locked;

CREATE TABLE queue_skip_locked.tasks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payload text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    priority integer NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);

-- The dequeue path: highest priority first, pending rows only.
CREATE INDEX tasks_pending_idx ON queue_skip_locked.tasks (priority DESC, id)
    WHERE status = 'pending';
