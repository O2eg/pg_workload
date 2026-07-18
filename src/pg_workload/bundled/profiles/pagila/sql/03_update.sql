set search_path = 'pagila';

SELECT customer_id FROM customer ORDER BY random() LIMIT 1 \gset
\set v_rnd_customer_id :customer_id

SELECT film_id FROM film ORDER BY random() LIMIT 1 \gset
\set v_rnd_film_id :film_id

SELECT inventory_id FROM inventory ORDER BY random() LIMIT 1 \gset
\set v_rnd_inventory_id :inventory_id

SELECT rental_id FROM rental ORDER BY random() LIMIT 1 \gset
\set v_rnd_rental_id :rental_id

SELECT payment_id FROM payment ORDER BY random() LIMIT 1 \gset
\set v_rnd_payment_id :payment_id

SELECT quote_literal(
    min(rental_date) +
    (
        random() *
        (max(return_date) - min(rental_date))
    )
) as rnd_date
FROM rental \gset

SELECT staff_id FROM staff ORDER BY random() LIMIT 1 \gset
\set v_rnd_staff_id :staff_id

-- Transaction 1: Process rental return
BEGIN;
UPDATE rental
SET return_date = :rnd_date::timestamp,
    last_update = :rnd_date::timestamp
WHERE rental_id = :v_rnd_rental_id
AND return_date IS NULL;
COMMIT;

-- Transaction 2: Update customer information
BEGIN;
UPDATE customer
SET email = 'updated' || floor(random() * 1000) || '@mail.com',
    activebool = CASE WHEN random() < 0.1 THEN false ELSE true END,
    active = CASE WHEN random() < 0.1 THEN 0 ELSE 1 END,
    last_update = :rnd_date::timestamp
WHERE customer_id = :v_rnd_customer_id;
COMMIT;

-- Transaction 3: Update film rental rates based on popularity
BEGIN;
WITH rental_stats AS (
    SELECT i.film_id,
           COUNT(*) as rental_count
    FROM rental r
    JOIN inventory i ON r.inventory_id = i.inventory_id
    WHERE r.rental_date >= :rnd_date::timestamp - INTERVAL '30 days'
    GROUP BY i.film_id
)
UPDATE film
SET rental_rate =
    CASE
        WHEN rs.rental_count > 50 THEN LEAST(rental_rate * 1.1, 4.99)
        WHEN rs.rental_count < 10 THEN GREATEST(rental_rate * 0.9, 0.99)
        ELSE rental_rate
    END,
    last_update = :rnd_date::timestamp
FROM rental_stats rs
WHERE film.film_id = :v_rnd_film_id
AND rs.film_id = film.film_id;
COMMIT;

-- Transaction 4: Update staff information
BEGIN;
UPDATE staff
SET email = 'staff' || floor(random() * 1000) || '@sakilastaff.com',
    username = 'user' || floor(random() * 1000),
    password = 'pass' || floor(random() * 1000),
    last_update = :rnd_date::timestamp
WHERE staff_id = :v_rnd_staff_id;
COMMIT;

-- Transaction 5: Update payment amounts (late fees)
BEGIN;
UPDATE payment
SET amount = amount +
    CASE
        WHEN EXISTS (
            SELECT 1 FROM rental r
            JOIN inventory i ON r.inventory_id = i.inventory_id
            JOIN film f ON i.film_id = f.film_id
            WHERE r.rental_id = payment.rental_id
            AND r.return_date > r.rental_date + make_interval(days => f.rental_duration)
        )
        THEN 1.00  -- Late fee
        ELSE 0
    END
WHERE payment_id = :v_rnd_payment_id;
COMMIT;

-- Transaction 6: Update film metadata
BEGIN;
UPDATE film
SET
    rental_duration = GREATEST(3, LEAST(7, rental_duration +
        CASE random() * 10
            WHEN 0 THEN -1
            WHEN 1 THEN 1
            ELSE 0
        END)),
    replacement_cost = GREATEST(9.99, LEAST(29.99, replacement_cost + (random() * 2 - 1))),
    rating = CASE floor(random() * 20)
        WHEN 0 THEN 'G'::mpaa_rating
        WHEN 1 THEN 'PG'::mpaa_rating
        WHEN 2 THEN 'PG-13'::mpaa_rating
        WHEN 3 THEN 'R'::mpaa_rating
        WHEN 4 THEN 'NC-17'::mpaa_rating
        ELSE rating
    END,
    last_update = :rnd_date::timestamp
WHERE film_id = :v_rnd_film_id;
COMMIT;

-- Transaction 7: Bulk update of overdue rentals
BEGIN;
UPDATE rental
SET last_update = :rnd_date::timestamp
WHERE rental_id IN (
    SELECT r.rental_id
    FROM rental r
    JOIN inventory i ON r.inventory_id = i.inventory_id
    JOIN film f ON i.film_id = f.film_id
    WHERE r.return_date IS NULL
    AND r.rental_date + make_interval(days => f.rental_duration) < :rnd_date::timestamp
    AND r.customer_id = :v_rnd_customer_id
);
COMMIT;

-- Transaction 8: Update inventory store assignments
BEGIN;
UPDATE inventory
SET store_id = CASE WHEN store_id = 1 THEN 2 ELSE 1 END,
    last_update = :rnd_date::timestamp
WHERE inventory_id = :v_rnd_inventory_id
AND NOT EXISTS (
    SELECT 1 FROM rental
    WHERE inventory_id = :v_rnd_inventory_id
    AND return_date IS NULL
);
COMMIT;
