-- Non-HOT updates on indexed columns: dead tuples grow in heap and indexes.
UPDATE bloat_vacuum.accounts a
SET balance = a.balance + (random() * 100 - 50)::numeric(14, 2),
    updated_at = clock_timestamp(),
    filler = md5(random()::text) || repeat('x', 40)
WHERE a.id IN (
    SELECT 1 + floor(random() * (SELECT max(id) FROM bloat_vacuum.accounts))::bigint
    FROM generate_series(1, 10)
);

-- A small insert/delete tail keeps autovacuum interesting.
INSERT INTO bloat_vacuum.accounts (owner_name, balance, status, filler)
SELECT
    'churn user ' || g,
    round((random() * 10000)::numeric, 2),
    'active',
    md5(random()::text) || repeat('x', 40)
FROM generate_series(1, 3) AS g;

DELETE FROM bloat_vacuum.accounts
WHERE id IN (
    SELECT id
    FROM bloat_vacuum.accounts
    WHERE owner_name LIKE 'churn user %'
    ORDER BY random()
    LIMIT 3
);
