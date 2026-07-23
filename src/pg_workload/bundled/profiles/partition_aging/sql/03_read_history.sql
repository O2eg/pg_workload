-- Full retention window: touches every partition.
SELECT date_trunc('day', ts) AS day, kind, count(*) AS events
FROM partition_aging.events
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC
LIMIT 100;
