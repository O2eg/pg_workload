INSERT INTO jsonb_docs.documents (doc_type, doc)
SELECT
    (ARRAY['order', 'invoice', 'ticket', 'profile'])[1 + floor(random() * 4)::integer],
    jsonb_build_object(
        'status', 'new',
        'customer_id', 1 + floor(power(random(), 2) * 10000)::integer,
        'amount', round((random() * 1000)::numeric, 2),
        'priority', floor(random() * 5)::integer,
        'tags', jsonb_build_array('tag-' || floor(random() * 50)::integer)
    )
FROM generate_series(1, 10) AS g;

-- Non-HOT-friendly update of a wide jsonb column on random rows.
UPDATE jsonb_docs.documents d
SET doc = jsonb_set(d.doc, '{status}', to_jsonb('closed'::text), false),
    updated_at = clock_timestamp()
WHERE d.id IN (
    SELECT 1 + floor(random() * (SELECT max(id) FROM jsonb_docs.documents))::bigint
    FROM generate_series(1, 5)
);
