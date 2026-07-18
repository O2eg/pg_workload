WITH bounds AS (
    SELECT
        (SELECT max(id) FROM simple_stock.order_items_1) AS order_1_max,
        (SELECT max(id) FROM simple_stock.order_items_2) AS order_2_max
)
INSERT INTO simple_stock.stock_items (order_items_1_id, optcounter, amount, order_items_2_id, descr)
SELECT
    1 + floor(random() * order_1_max)::integer,
    floor(random() * 20000)::smallint,
    round((random() * 500)::numeric, 4),
    1 + floor(random() * order_2_max)::integer,
    'workload insert ' || g
FROM bounds
CROSS JOIN generate_series(1, 100) AS g;

UPDATE simple_stock.stock_items
SET descr = 'updated at ' || now(), amount = amount + 1
WHERE order_items_1_id IN (
    SELECT id FROM simple_stock.order_items_1 ORDER BY random() LIMIT 100
);

DELETE FROM simple_stock.stock_items
WHERE order_items_1_id IN (
    SELECT id FROM simple_stock.order_items_1 ORDER BY random() LIMIT 50
);

\set v1 random(14000, 15000)
\set v2 random(15000, 16000)

SELECT t1.order_items_1_id, t1.order_items_2_id, max(t1.amount) AS max_amount
FROM simple_stock.stock_items t1
JOIN simple_stock.order_items_1 oi1 ON t1.order_items_1_id = oi1.id
JOIN simple_stock.order_items_2 oi2 ON t1.order_items_2_id = oi2.id
WHERE t1.optcounter > :v1 AND t1.optcounter < :v2
GROUP BY t1.order_items_1_id, t1.order_items_2_id;
