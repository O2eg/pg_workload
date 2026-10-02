SET search_path = pagila, public;

-- pagila OLTP: short read transactions with point lookups. Random identifiers come from
-- pgbench (\set random) within live bounds read per script. Dates are offsets from 2022-01-01, the start of the generated data.
-- Live bounds come from pagila.bench_bounds using primary-key indexes.
-- They include rows inserted by earlier scheduler runs.
SELECT * FROM bench_bounds \gset
\set customer_id random(1, :max_customer)
\set film_id random(1, :max_film)
\set store_id random(1, :max_store)
\set inventory_id random(1, :max_inventory)
\set actor_id random(1, :max_actor)
\set staff_id random(1, :max_staff)
\set category_id random(1, :max_category)
\set day random(0, 200)
\set next_day :day + 1

-- Resolve sequence gaps left by earlier concurrent or interrupted writes.
SELECT
    (SELECT customer_id FROM customer WHERE customer_id >= :customer_id ORDER BY customer_id LIMIT 1) AS customer_id,
    (SELECT film_id FROM film WHERE film_id >= :film_id ORDER BY film_id LIMIT 1) AS film_id,
    (SELECT store_id FROM store WHERE store_id >= :store_id ORDER BY store_id LIMIT 1) AS store_id,
    (SELECT inventory_id FROM inventory WHERE inventory_id >= :inventory_id ORDER BY inventory_id LIMIT 1) AS inventory_id,
    (SELECT actor_id FROM actor WHERE actor_id >= :actor_id ORDER BY actor_id LIMIT 1) AS actor_id,
    (SELECT staff_id FROM staff WHERE staff_id >= :staff_id ORDER BY staff_id LIMIT 1) AS staff_id,
    (SELECT category_id FROM category WHERE category_id >= :category_id ORDER BY category_id LIMIT 1) AS category_id
\gset

-- Customer rental history
SELECT c.first_name, c.last_name, f.title, r.rental_date, r.return_date
FROM customer c
JOIN rental r ON r.customer_id = c.customer_id
JOIN inventory i ON i.inventory_id = r.inventory_id
JOIN film f ON f.film_id = i.film_id
WHERE c.customer_id = :customer_id
ORDER BY r.rental_date DESC
LIMIT 10;

-- Customer balance as of a date
SELECT get_customer_balance(:customer_id, TIMESTAMPTZ '2022-01-01 00:00:00+00' + make_interval(days => :day));

-- Film availability at a store
SELECT film_in_stock(:film_id, :store_id);
SELECT inventory_in_stock(:inventory_id);

-- Film card: category, copies, rented copies, actors
SELECT f.title, f.rental_rate, f.rating, c.name AS category,
       count(DISTINCT i.inventory_id) AS total_copies,
       count(DISTINCT r.inventory_id) AS rented_copies,
       string_agg(DISTINCT a.first_name || ' ' || a.last_name, ', ') AS actors
FROM film f
JOIN film_category fc ON fc.film_id = f.film_id
JOIN category c ON c.category_id = fc.category_id
LEFT JOIN inventory i ON i.film_id = f.film_id
LEFT JOIN rental r ON r.inventory_id = i.inventory_id AND r.return_date IS NULL
LEFT JOIN film_actor fa ON fa.film_id = f.film_id
LEFT JOIN actor a ON a.actor_id = fa.actor_id
WHERE f.film_id = :film_id
GROUP BY f.film_id, f.title, f.rental_rate, f.rating, c.name;

-- Films of a category available in a store
SELECT f.film_id, f.title, f.rental_rate
FROM film_category fc
JOIN film f ON f.film_id = fc.film_id
JOIN inventory i ON i.film_id = f.film_id AND i.store_id = :store_id
WHERE fc.category_id = :category_id
  AND NOT EXISTS (
      SELECT 1 FROM rental r WHERE r.inventory_id = i.inventory_id AND r.return_date IS NULL
  )
ORDER BY f.title
LIMIT 10;

-- Staff: rentals processed during one day
SELECT r.rental_id, r.rental_date, c.first_name || ' ' || c.last_name AS customer, f.title
FROM rental r
JOIN customer c ON c.customer_id = r.customer_id
JOIN inventory i ON i.inventory_id = r.inventory_id
JOIN film f ON f.film_id = i.film_id
WHERE r.staff_id = :staff_id
  AND r.rental_date >= TIMESTAMPTZ '2022-01-01 00:00:00+00' + make_interval(days => :day)
  AND r.rental_date <  TIMESTAMPTZ '2022-01-01 00:00:00+00' + make_interval(days => :next_day)
ORDER BY r.rental_date DESC
LIMIT 20;

-- Overdue rentals of a customer
SELECT r.rental_id, f.title, r.rental_date, f.rental_duration
FROM rental r
JOIN inventory i ON i.inventory_id = r.inventory_id
JOIN film f ON f.film_id = i.film_id
WHERE r.customer_id = :customer_id
  AND r.return_date IS NULL
  AND r.rental_date + make_interval(days => f.rental_duration)
      < TIMESTAMPTZ '2022-01-01 00:00:00+00' + make_interval(days => :day)
ORDER BY r.rental_date;

-- Actor filmography
SELECT f.title, f.release_year, f.rating
FROM film_actor fa
JOIN film f ON f.film_id = fa.film_id
WHERE fa.actor_id = :actor_id
ORDER BY f.release_year DESC, f.title
LIMIT 20;

-- Inventory status of a film in a store
SELECT i.inventory_id,
       inventory_in_stock(i.inventory_id) AS in_stock,
       inventory_held_by_customer(i.inventory_id) AS held_by_customer
FROM inventory i
WHERE i.film_id = :film_id AND i.store_id = :store_id;
