REFRESH MATERIALIZED VIEW pagila.rental_by_category;

-- Live index-backed bounds include rows added by earlier scheduler runs. Rentals may
-- be empty or have gaps; update/delete scripts resolve candidates to existing rows.
CREATE VIEW pagila.bench_bounds AS
SELECT
    (SELECT max(customer_id) FROM pagila.customer) AS max_customer,
    (SELECT max(film_id) FROM pagila.film) AS max_film,
    (SELECT max(store_id) FROM pagila.store) AS max_store,
    (SELECT max(inventory_id) FROM pagila.inventory) AS max_inventory,
    (SELECT max(actor_id) FROM pagila.actor) AS max_actor,
    COALESCE((SELECT min(rental_id) FROM pagila.rental), 1) AS min_rental,
    COALESCE((SELECT max(rental_id) FROM pagila.rental), 1) AS max_rental,
    (SELECT max(staff_id) FROM pagila.staff) AS max_staff,
    (SELECT max(address_id) FROM pagila.address) AS max_address,
    (SELECT max(city_id) FROM pagila.city) AS max_city,
    (SELECT max(category_id) FROM pagila.category) AS max_category,
    (SELECT max(language_id) FROM pagila.language) AS max_language;
