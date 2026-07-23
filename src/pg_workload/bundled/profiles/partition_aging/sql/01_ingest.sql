INSERT INTO partition_aging.events (ts, kind, payload)
SELECT
    clock_timestamp(),
    (ARRAY['click', 'view', 'purchase', 'signup', 'error'])[1 + floor(random() * 5)::integer],
    'live event ' || g || ' session=' || floor(random() * 100000)::integer
FROM generate_series(1, 100) AS g;
