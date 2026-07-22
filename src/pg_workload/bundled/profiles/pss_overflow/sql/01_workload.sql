SELECT table_count FROM pss_overflow.profile_config \gset
\set table1_id random(1, :table_count)
\set table2_id random(1, :table_count)
\set table3_id random(1, :table_count)

set search_path = 'pss_overflow';

SELECT t1.value AS value1, t2.value AS value2, t3.value AS value3
FROM table_:table1_id t1
JOIN table_:table2_id t2 ON t1.id = t2.id
JOIN table_:table3_id t3 ON t2.id = t3.id
WHERE t1.id = 1 AND t2.id = 1 AND t3.id = 1;
