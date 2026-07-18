set search_path = 'pagila';

SELECT customer_id FROM customer ORDER BY random() LIMIT 1 \gset
\set v_rnd_customer_id :customer_id

SELECT film_id FROM film ORDER BY random() LIMIT 1 \gset
\set v_rnd_film_id :film_id

SELECT store_id FROM store ORDER BY random() LIMIT 1 \gset
\set v_rnd_store_id :store_id

SELECT inventory_id FROM inventory ORDER BY random() LIMIT 1 \gset
\set v_rnd_inventory_id :inventory_id

SELECT actor_id FROM actor ORDER BY random() LIMIT 1 \gset
\set v_rnd_actor_id :actor_id

SELECT quote_literal(
    min(rental_date) +
    (
        random() *
        (max(return_date) - min(rental_date))
    )
) as rnd_date
FROM rental \gset

SELECT quote_literal(
    min(payment_date) +
    (
        random() *
        (max(payment_date) - min(payment_date))
    )
) as rnd_payment_date
FROM payment \gset

SELECT category_id FROM category ORDER BY random() LIMIT 1 \gset
\set v_rnd_category_id :category_id

SELECT staff_id FROM staff ORDER BY random() LIMIT 1 \gset
\set v_rnd_staff_id :staff_id

SELECT address_id FROM address ORDER BY random() LIMIT 1 \gset
\set v_rnd_address_id :address_id


-- Transaction 1: New rental with payment
BEGIN;
WITH new_rental AS (
    INSERT INTO rental (
        rental_date,
        inventory_id,
        customer_id,
        staff_id,
        last_update
    )
    SELECT
        :rnd_date,
        :v_rnd_inventory_id,
        :v_rnd_customer_id,
        :v_rnd_staff_id,
        :rnd_date
    RETURNING rental_id
)
INSERT INTO payment (
    customer_id,
    staff_id,
    rental_id,
    amount,
    payment_date
)
SELECT
    :v_rnd_customer_id,
    :v_rnd_staff_id,
    rental_id,
    (SELECT rental_rate FROM film
     JOIN inventory ON film.film_id = inventory.film_id
     WHERE inventory_id = :v_rnd_inventory_id),
    :rnd_payment_date
FROM new_rental;
COMMIT;


-- Transaction 2: New customer registration
BEGIN;
WITH new_address AS (
    INSERT INTO address (
        address,
        district,
        city_id,
        postal_code,
        phone,
        last_update
    )
    VALUES (
        'Street ' || floor(random() * 1000),
        'District ' || floor(random() * 100),
        (SELECT city_id FROM city ORDER BY random() LIMIT 1),
        floor(random() * 90000) + 10000,
        floor(random() * 900000000) + 100000000,
        :rnd_date::timestamp
    )
    RETURNING address_id
)
INSERT INTO customer (
    store_id,
    first_name,
    last_name,
    email,
    address_id,
    activebool,
    create_date,
    last_update,
    active
)
SELECT
    :v_rnd_store_id,
    'Name' || floor(random() * 1000),
    'Surname' || floor(random() * 1000),
    'email' || floor(random() * 1000) || '@mail.com',
    address_id,
    true,
    :rnd_date::date,
    :rnd_date::timestamp,
    1
FROM new_address;
COMMIT;


-- Transaction 3: New film with categories and inventory
BEGIN;
WITH new_film AS (
    INSERT INTO film (
        title,
        description,
        release_year,
        language_id,
        rental_duration,
        rental_rate,
        length,
        replacement_cost,
        rating,
        last_update,
        special_features
    )
    VALUES (
        'Film ' || floor(random() * 1000),
        'Description ' || floor(random() * 1000),
        EXTRACT(YEAR FROM :rnd_date::timestamp),
        (SELECT language_id FROM language ORDER BY random() LIMIT 1),
        floor(random() * 7) + 1,
        (floor(random() * 4) + 1)::numeric(4,2),
        floor(random() * 180) + 60,
        (floor(random() * 20) + 10)::numeric(5,2),
        (ARRAY['G', 'PG', 'PG-13', 'R', 'NC-17'])[floor(random() * 5) + 1]::mpaa_rating,
        :rnd_date::timestamp,
        ARRAY['Trailers', 'Commentaries']
    )
    RETURNING film_id
),
new_film_category AS (
    INSERT INTO film_category (
        film_id,
        category_id,
        last_update
    )
    SELECT
        film_id,
        :v_rnd_category_id,
        :rnd_date::timestamp
    FROM new_film
),
new_film_actor AS (
    INSERT INTO film_actor (
        actor_id,
        film_id,
        last_update
    )
    SELECT
        :v_rnd_actor_id,
        film_id,
        :rnd_date::timestamp
    FROM new_film
)
INSERT INTO inventory (
    film_id,
    store_id,
    last_update
)
SELECT
    film_id,
    :v_rnd_store_id,
    :rnd_date::timestamp
FROM new_film;
COMMIT;

-- Transaction 4: New store staff registration
BEGIN;
WITH new_address AS (
    INSERT INTO address (
        address,
        district,
        city_id,
        postal_code,
        phone,
        last_update
    )
    VALUES (
        'Staff Street ' || floor(random() * 1000),
        'Staff District ' || floor(random() * 100),
        (SELECT city_id FROM city ORDER BY random() LIMIT 1),
        floor(random() * 90000) + 10000,
        floor(random() * 900000000) + 100000000,
        :rnd_date::timestamp
    )
    RETURNING address_id
)
INSERT INTO staff (
    first_name,
    last_name,
    address_id,
    email,
    store_id,
    active,
    username,
    password,
    last_update
)
SELECT
    'Staff' || floor(random() * 1000),
    'StaffSurname' || floor(random() * 1000),
    address_id,
    'staff' || floor(random() * 1000) || '@store.com',
    :v_rnd_store_id,
    true,
    'staff' || floor(random() * 1000),
    'pass' || floor(random() * 1000),
    :rnd_date::timestamp
FROM new_address;
COMMIT;

-- Transaction 5: Batch inventory addition
\set should_call random(0, 1)
\if :should_call < 0.3

BEGIN;
INSERT INTO inventory (
    film_id,
    store_id,
    last_update
)
SELECT
    :v_rnd_film_id,
    :v_rnd_store_id,
    :rnd_date::timestamp
FROM generate_series(1, (floor(random() * 3) + 1)::integer);
COMMIT;

\endif

-- -- Transaction 6: New store creation
BEGIN;
WITH new_staff AS (
    SELECT staff_id FROM staff
    WHERE staff_id NOT IN (SELECT manager_staff_id FROM store)
    ORDER BY random()
    LIMIT 1
)
INSERT INTO store (manager_staff_id, address_id)
SELECT
    staff_id,
    :v_rnd_address_id
FROM new_staff;
COMMIT;
