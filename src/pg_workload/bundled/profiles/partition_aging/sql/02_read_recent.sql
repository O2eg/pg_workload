-- Recent window: prunes to one or two partitions.
SELECT kind, count(*) AS events
FROM partition_aging.events
WHERE ts > now() - interval '6 hours'
GROUP BY kind
ORDER BY 2 DESC;

SELECT count(*)
FROM partition_aging.events
WHERE ts > now() - interval '1 hour'
  AND kind = 'error';
