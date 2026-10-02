SET search_path = pagila, public;

-- pagila OLTP: write transactions. Every transaction records a rental with its payment;
-- customer registration, catalogue and staff changes are gated by pgbench-side
-- probabilities, so the mix stays shop-like and reproducible under --random-seed. Dates
-- stay inside the 2022 payment partitions (2022-01-01 .. 2022-07-31).
-- Live bounds come from pagila.bench_bounds using primary-key indexes.
-- They include rows inserted by earlier scheduler runs.
SELECT * FROM bench_bounds \gset
\set customer_id random(1, :max_customer)
\set inventory_id random(1, :max_inventory)
\set staff_id random(1, :max_staff)
\set store_id random(1, :max_store)
\set film_id random(1, :max_film)
\set category_id random(1, :max_category)
\set actor_id random(1, :max_actor)
\set city_id random(1, :max_city)
\set language_id random(1, :max_language)
\set address_id random(1, :max_address)
\set day random(0, 200)
\set sec random(0, 86399)
\set hours random(1, 72)
\set suffix random(1, 1000000)
\set rating_idx random(1, 5)
\set copies random(1, 3)
\set chance_customer random(1, 100)
\set chance_film random(1, 100)
\set chance_stock random(1, 100)
\set chance_staff random(1, 1000)
\set chance_store random(1, 1000)

-- Sequence gaps can remain after an interrupted transaction. Resolve candidates by
-- primary key so future runs can use new rows without inserting invalid foreign keys.
SELECT
    (SELECT customer_id FROM customer WHERE customer_id >= :customer_id ORDER BY customer_id LIMIT 1) AS customer_id,
    (SELECT inventory_id FROM inventory WHERE inventory_id >= :inventory_id ORDER BY inventory_id LIMIT 1) AS inventory_id,
    (SELECT staff_id FROM staff WHERE staff_id >= :staff_id ORDER BY staff_id LIMIT 1) AS staff_id,
    (SELECT store_id FROM store WHERE store_id >= :store_id ORDER BY store_id LIMIT 1) AS store_id,
    (SELECT film_id FROM film WHERE film_id >= :film_id ORDER BY film_id LIMIT 1) AS film_id,
    (SELECT category_id FROM category WHERE category_id >= :category_id ORDER BY category_id LIMIT 1) AS category_id,
    (SELECT actor_id FROM actor WHERE actor_id >= :actor_id ORDER BY actor_id LIMIT 1) AS actor_id,
    (SELECT city_id FROM city WHERE city_id >= :city_id ORDER BY city_id LIMIT 1) AS city_id,
    (SELECT language_id FROM language WHERE language_id >= :language_id ORDER BY language_id LIMIT 1) AS language_id,
    (SELECT address_id FROM address WHERE address_id >= :address_id ORDER BY address_id LIMIT 1) AS address_id
\gset

-- New rental with its payment. ON CONFLICT keeps a replayed seed (same database, same
-- --random-seed) from aborting the client. Scheduled runs use pgbench's default seed.
BEGIN;
WITH new_rental AS (
    INSERT INTO rental (rental_date, inventory_id, customer_id, staff_id)
    VALUES (
        TIMESTAMPTZ '2022-01-01 00:00:00+00' + make_interval(days => :day, secs => :sec),
        :inventory_id,
        :customer_id,
        :staff_id
    )
    ON CONFLICT (rental_date, inventory_id, customer_id) DO NOTHING
    RETURNING rental_id, rental_date
)
INSERT INTO payment (customer_id, staff_id, rental_id, amount, payment_date)
SELECT
    :customer_id::bigint,
    :staff_id::bigint,
    nr.rental_id,
    (SELECT f.rental_rate
     FROM inventory i
     JOIN film f ON f.film_id = i.film_id
     WHERE i.inventory_id = :inventory_id),
    nr.rental_date + make_interval(hours => :hours)
FROM new_rental AS nr;
COMMIT;

-- New customer with address (one transaction in ten)
\if :chance_customer <= 10
BEGIN;
WITH new_address AS (
    INSERT INTO address (address, district, city_id, postal_code, phone)
    VALUES (
        'Street ' || :suffix,
        'District ' || (:suffix % 100),
        :city_id,
        lpad((:suffix % 100000)::text, 5, '0'),
        '+1-' || lpad(:suffix::text, 10, '0')
    )
    RETURNING address_id
)
INSERT INTO customer
    (store_id, first_name, last_name, email, address_id, activebool, create_date, active)
SELECT
    :store_id::bigint,
    'Name' || :suffix,
    'Surname' || (:suffix % 1000),
    'customer' || :suffix || '@example.test',
    na.address_id,
    true,
    (TIMESTAMPTZ '2022-01-01 00:00:00+00' + make_interval(days => :day))::date,
    1
FROM new_address AS na;
COMMIT;
\endif

-- New film with category, actor and first inventory copy (one transaction in twenty)
\if :chance_film <= 5
BEGIN;
WITH new_film AS (
    INSERT INTO film
        (title, description, release_year, language_id, rental_duration, rental_rate,
         length, replacement_cost, rating, special_features)
    VALUES (
        'Film ' || :suffix,
        'Description ' || :suffix,
        (2000 + :suffix % 23)::year,
        :language_id,
        1 + :suffix % 7,
        (0.99 + (:suffix % 5))::numeric(4,2),
        60 + :suffix % 120,
        (9.99 + (:suffix % 20))::numeric(5,2),
        (ARRAY['G', 'PG', 'PG-13', 'R', 'NC-17'])[:rating_idx::integer]::mpaa_rating,
        ARRAY['Trailers', 'Commentaries']
    )
    RETURNING film_id
),
new_film_category AS (
    INSERT INTO film_category (film_id, category_id)
    SELECT film_id, :category_id::bigint FROM new_film
),
new_film_actor AS (
    INSERT INTO film_actor (actor_id, film_id)
    SELECT :actor_id::bigint, film_id FROM new_film
)
INSERT INTO inventory (film_id, store_id)
SELECT film_id, :store_id::bigint FROM new_film;
COMMIT;
\endif

-- Extra copies of a film for a store (one transaction in ten)
\if :chance_stock <= 10
INSERT INTO inventory (film_id, store_id)
SELECT :film_id::bigint, :store_id::bigint
FROM generate_series(1, :copies::integer);
\endif

-- New staff member (one transaction in five hundred)
\if :chance_staff <= 2
BEGIN;
WITH new_address AS (
    INSERT INTO address (address, district, city_id, postal_code, phone)
    VALUES (
        'Staff Street ' || :suffix,
        'Staff District ' || (:suffix % 100),
        :city_id,
        lpad((:suffix % 100000)::text, 5, '0'),
        '+1-' || lpad(:suffix::text, 10, '0')
    )
    RETURNING address_id
)
INSERT INTO staff (first_name, last_name, address_id, email, store_id, active, username, password)
SELECT
    'Staff' || :suffix,
    'StaffSurname' || (:suffix % 1000),
    na.address_id,
    'staff' || :suffix || '@example.test',
    :store_id::bigint,
    true,
    'staff_' || :suffix,
    NULL
FROM new_address AS na;
COMMIT;
\endif

-- New store managed by a staff member without a store (one transaction in five hundred).
-- SKIP LOCKED plus ON CONFLICT keeps concurrent clients from racing on the same manager.
\if :chance_store <= 2
BEGIN;
WITH new_staff AS (
    SELECT staff_id
    FROM staff
    WHERE NOT EXISTS (
        SELECT 1 FROM store WHERE store.manager_staff_id = staff.staff_id
    )
    ORDER BY staff_id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
INSERT INTO store (manager_staff_id, address_id)
SELECT staff_id, :address_id::bigint
FROM new_staff
ON CONFLICT (manager_staff_id) DO NOTHING;
COMMIT;
\endif
