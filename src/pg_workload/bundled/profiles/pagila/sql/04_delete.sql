SET search_path = pagila, public;

-- Remove an existing rental with its payments, including rows from earlier runs.
-- Indexed successor lookup handles gaps; SKIP LOCKED avoids concurrent deleters
-- picking the same rental. An empty or fully locked table is a valid no-op.
SELECT * FROM bench_bounds \gset
\set rental_id random(:min_rental, :max_rental)

BEGIN;
SELECT COALESCE(
    (SELECT rental_id FROM rental WHERE rental_id >= :rental_id ORDER BY rental_id LIMIT 1 FOR UPDATE SKIP LOCKED),
    (SELECT rental_id FROM rental ORDER BY rental_id LIMIT 1 FOR UPDATE SKIP LOCKED),
    0
) AS rental_id \gset
DELETE FROM payment WHERE rental_id = :rental_id;
DELETE FROM rental WHERE rental_id = :rental_id;
COMMIT;
