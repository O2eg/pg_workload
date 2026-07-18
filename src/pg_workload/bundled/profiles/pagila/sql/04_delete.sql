set search_path = 'pagila';

-- Get random existing rental_id with fallback
WITH sample_rental AS (
    SELECT rental_id FROM rental TABLESAMPLE SYSTEM (0.1) WHERE rental_id IS NOT NULL
    UNION ALL
    SELECT rental_id FROM rental WHERE rental_id IS NOT NULL
    LIMIT 1
)
SELECT rental_id FROM sample_rental LIMIT 1 \gset
\set v_rnd_rental_id :rental_id

-- Set delete threshold using pgbench's native random
\set should_delete random(1, 100)
\if :should_delete < 20
BEGIN;
    -- Single delete operation using JOIN
    DELETE FROM payment p
    USING rental r
    WHERE p.rental_id = r.rental_id
    AND r.rental_id = :v_rnd_rental_id;

    -- Direct delete using sampled ID
    DELETE FROM rental
    WHERE rental_id = :v_rnd_rental_id;
COMMIT;
\endif
