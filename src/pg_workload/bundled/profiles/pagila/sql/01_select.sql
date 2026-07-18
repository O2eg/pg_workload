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

SELECT category_id FROM category ORDER BY random() LIMIT 1 \gset
\set v_rnd_category_id :category_id

SELECT staff_id FROM staff ORDER BY random() LIMIT 1 \gset
\set v_rnd_staff_id :staff_id

BEGIN;

SELECT c.first_name, c.last_name, f.title, r.rental_date, r.return_date
FROM customer c
JOIN rental r ON c.customer_id = r.customer_id
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film f ON i.film_id = f.film_id
WHERE c.customer_id = :v_rnd_customer_id
ORDER BY r.rental_date DESC
LIMIT 10;

SELECT get_customer_balance(:v_rnd_customer_id, :rnd_date);

SELECT r.rental_date, f.title,
       p.amount as payment_amount,
       CASE WHEN r.return_date IS NULL THEN 'OUT' ELSE 'RETURNED' END as status
FROM rental r
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film f ON i.film_id = f.film_id
LEFT JOIN payment p ON r.rental_id = p.rental_id
WHERE r.customer_id = :v_rnd_customer_id
ORDER BY r.rental_date DESC
LIMIT 10;

COMMIT;


-- Transaction 2: Film availability search
BEGIN;
SELECT film_in_stock(:v_rnd_film_id, :v_rnd_store_id);
SELECT inventory_in_stock(:v_rnd_inventory_id);

SELECT f.title, f.rental_rate, f.rating,
       c.name as category,
       COUNT(i.inventory_id) as total_copies,
       COUNT(i.inventory_id) FILTER (WHERE r.return_date IS NULL) as rented_copies,
       string_agg(DISTINCT a.first_name || ' ' || a.last_name, ', ') as actors
FROM film f
JOIN film_category fc ON f.film_id = fc.film_id
JOIN category c ON fc.category_id = c.category_id
JOIN inventory i ON f.film_id = i.film_id
JOIN film_actor fa ON f.film_id = fa.film_id
JOIN actor a ON fa.actor_id = a.actor_id
LEFT JOIN rental r ON i.inventory_id = r.inventory_id AND r.return_date IS NULL
WHERE f.film_id = :v_rnd_film_id
GROUP BY f.title, f.rental_rate, f.rating, c.name;
COMMIT;

-- Transaction 3: Category browsing
BEGIN;
SELECT f.film_id, f.title, f.rental_rate, f.rating,
       COUNT(DISTINCT i.inventory_id) as total_copies,
       COUNT(DISTINCT i.inventory_id) - COUNT(r.rental_id) FILTER (WHERE r.return_date IS NULL) as available_copies
FROM film f
JOIN film_category fc ON f.film_id = fc.film_id
JOIN inventory i ON f.film_id = i.film_id
LEFT JOIN rental r ON i.inventory_id = r.inventory_id AND r.return_date IS NULL
WHERE fc.category_id = :v_rnd_category_id
AND i.store_id = :v_rnd_store_id
GROUP BY f.film_id, f.title, f.rental_rate, f.rating
HAVING COUNT(DISTINCT i.inventory_id) - COUNT(r.rental_id) FILTER (WHERE r.return_date IS NULL) > 0
LIMIT 10;
COMMIT;

-- Transaction 4: Store performance analysis
BEGIN;
SELECT DATE_TRUNC('day', r.rental_date) as rental_day,
       COUNT(*) as rental_count,
       SUM(p.amount) as daily_revenue
FROM rental r
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN payment p ON r.rental_id = p.rental_id
WHERE i.store_id = :v_rnd_store_id
AND r.rental_date >= :rnd_date::timestamp - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', r.rental_date)
ORDER BY rental_day DESC;

SELECT c.name as category,
       COUNT(*) as rental_count
FROM rental r
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film f ON i.film_id = f.film_id
JOIN film_category fc ON f.film_id = fc.film_id
JOIN category c ON fc.category_id = c.category_id
WHERE i.store_id = :v_rnd_store_id
AND r.rental_date >= :rnd_date::timestamp - INTERVAL '30 days'
GROUP BY c.name
ORDER BY rental_count DESC;
COMMIT;

-- Transaction 5: Staff rental processing lookups
BEGIN;
SELECT r.rental_date,
       c.first_name || ' ' || c.last_name as customer_name,
       f.title,
       p.amount
FROM rental r
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film f ON i.film_id = f.film_id
JOIN customer c ON r.customer_id = c.customer_id
JOIN payment p ON r.rental_id = p.rental_id
WHERE r.staff_id = :v_rnd_staff_id
AND r.rental_date >= :rnd_date::timestamp - INTERVAL '1 day'
ORDER BY r.rental_date DESC;

SELECT c.first_name || ' ' || c.last_name as customer_name,
       c.email,
       f.title,
       r.rental_date,
       f.rental_duration,
       EXTRACT(DAY FROM (:rnd_date::timestamp - r.rental_date)) as days_rented
FROM rental r
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film f ON i.film_id = f.film_id
JOIN customer c ON r.customer_id = c.customer_id
WHERE r.return_date IS NULL
AND EXTRACT(DAY FROM (:rnd_date::timestamp - r.rental_date)) > f.rental_duration
AND i.store_id = :v_rnd_store_id
ORDER BY r.rental_date;
COMMIT;

-- Transaction 6: Comprehensive Film Stock Check
BEGIN;
-- Check stock across multiple films in a category
SELECT f.film_id, f.title,
       film_in_stock(f.film_id, :v_rnd_store_id) as copies_available
FROM film f
JOIN film_category fc ON f.film_id = fc.film_id
WHERE fc.category_id = :v_rnd_category_id
LIMIT 5;

-- Check specific film availability across all stores
SELECT s.store_id, a.address,
       film_in_stock(f.film_id, s.store_id) as copies_available
FROM store s
JOIN address a ON s.address_id = a.address_id
CROSS JOIN (SELECT film_id FROM film WHERE film_id = :v_rnd_film_id) f;
COMMIT;

-- Transaction 7: Customer Rewards Analysis
BEGIN;
-- Get detailed balance for customer
SELECT c.first_name || ' ' || c.last_name as customer,
       get_customer_balance(:v_rnd_customer_id, :rnd_date::timestamp) as current_balance
FROM customer c
WHERE c.customer_id = :v_rnd_customer_id;

-- Get rewards report for active customers
WITH RECURSIVE reward_customers AS (
    SELECT * FROM rewards_report(3, 100.00)
)
SELECT first_name, last_name, email
FROM reward_customers
LIMIT 5;
COMMIT;


-- Transaction 8: Actor Performance Analysis
-- REFRESH MATERIALIZED VIEW rental_by_category
BEGIN;
-- Get actor filmography with categories
SELECT * FROM actor_info
WHERE actor_id = :v_rnd_actor_id;

-- Get detailed film list for actor's movies
SELECT DISTINCT fl.*
FROM film_list fl
JOIN film_actor fa ON fa.film_id = fl.fid
WHERE fa.actor_id = :v_rnd_actor_id
LIMIT 5;
COMMIT;


-- Transaction 9: Store Sales Analysis
BEGIN;
-- Get sales by store
SELECT * FROM sales_by_store;

SELECT * FROM staff_list;

-- Get sales by category
SELECT * FROM sales_by_film_category;

-- Get detailed rental metrics by category
SELECT rb.category,
       rb.total_sales,
       COUNT(r.rental_id) as rental_count,
       ROUND(AVG(f.rental_rate), 2) as avg_rental_rate
FROM rental_by_category rb
JOIN category c ON rb.category = c.name
JOIN film_category fc ON c.category_id = fc.category_id
JOIN film f ON fc.film_id = f.film_id
JOIN inventory i ON f.film_id = i.film_id
JOIN rental r ON i.inventory_id = r.inventory_id
GROUP BY rb.category, rb.total_sales
ORDER BY rb.total_sales DESC;
COMMIT;

-- Transaction 10: Inventory Status Report
BEGIN;
-- Check inventory status for random films
SELECT f.film_id, f.title,
       i.inventory_id,
       inventory_in_stock(i.inventory_id) as is_available,
       CASE
           WHEN inventory_held_by_customer(i.inventory_id) IS NOT NULL
           THEN 'Rented by customer ' || inventory_held_by_customer(i.inventory_id)::text
           ELSE 'Available'
       END as status
FROM film f
JOIN inventory i ON f.film_id = i.film_id
WHERE f.film_id IN (
    SELECT film_id FROM film
    ORDER BY random()
    LIMIT 5
)
ORDER BY f.title;

-- Get overdue rentals with customer balance
SELECT c.customer_id,
       c.first_name || ' ' || c.last_name as customer,
       f.title,
       r.rental_date,
       get_customer_balance(c.customer_id, CURRENT_TIMESTAMP) as current_balance
FROM rental r
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film f ON i.film_id = f.film_id
JOIN customer c ON r.customer_id = c.customer_id
WHERE r.return_date IS NULL
AND rental_date < :rnd_date::timestamp - INTERVAL '7 days'
LIMIT 10;
COMMIT;
