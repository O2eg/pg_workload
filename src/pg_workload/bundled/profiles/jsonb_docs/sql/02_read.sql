\set customer_id random(1, 10000)

-- GIN-indexed containment lookup.
SELECT count(*)
FROM jsonb_docs.documents
WHERE doc @> jsonb_build_object('customer_id', :customer_id);

-- Expression-index filter plus a jsonpath extraction.
SELECT d.id, jsonb_path_query(d.doc, '$.tags[*]') AS tag
FROM jsonb_docs.documents d
WHERE d.doc ->> 'status' = 'open'
LIMIT 50;

-- Aggregation over extracted keys.
SELECT doc ->> 'status' AS status, count(*) AS docs
FROM jsonb_docs.documents
GROUP BY 1
ORDER BY 2 DESC;
