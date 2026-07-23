INSERT INTO queue_skip_locked.tasks (payload, priority)
SELECT
    'job-' || g || '-' || floor(random() * 1000000)::integer,
    floor(power(random(), 2) * 10)::integer
FROM generate_series(1, 25) AS g;
