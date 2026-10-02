from __future__ import annotations

import math
from pathlib import Path

from pg_workload.initialization import LoadPlan, LoadTask, generator_main, read_sql_tasks


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def build_load_plan(scale: float) -> LoadPlan:
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be a finite number greater than zero")
    stores = max(2, round(2 * max(1.0, scale**0.5)))
    staff = stores
    countries = scaled(109, scale, 10)
    cities = scaled(600, scale, 50)
    customers = scaled(600, scale, 100)
    addresses = stores + staff + customers
    actors = scaled(200, scale, 50)
    films = scaled(1_000, scale, 100)
    inventory = scaled(4_500, scale, films * 2)
    rentals = scaled(16_000, scale, 1_000)
    payments = scaled(16_500, scale, rentals)
    categories = 16
    languages = 6

    data = (
        LoadTask(
            "language",
            """
INSERT INTO language (language_id, name)
        SELECT g, rpad(
            (ARRAY['English', 'Italian', 'Japanese', 'Mandarin', 'French', 'German'])[g],
            20
        )
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=languages,
        ),
        LoadTask(
            "category",
            """
INSERT INTO category (category_id, name)
        SELECT g, (ARRAY[
            'Action', 'Animation', 'Children', 'Classics', 'Comedy', 'Documentary', 'Drama',
            'Family',
            'Foreign', 'Games', 'Horror', 'Music', 'New', 'Science Fiction', 'Sports', 'Travel'
        ])[g]
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=categories,
        ),
        LoadTask(
            "country",
            """
INSERT INTO country (country_id, country)
        SELECT g, 'Country ' || lpad(g::text, 3, '0')
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=countries,
        ),
        LoadTask(
            "city",
            f"""
INSERT INTO city (city_id, city, country_id)
        SELECT g, 'City ' || g, 1 + ((g * 37 - 1) % {countries})
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=cities,
            depends_on=("country",),
        ),
        LoadTask(
            "address",
            f"""
INSERT INTO address (address_id, address, address2, district, city_id, postal_code, phone)
        SELECT g,
            (10 + (g * 17) % 9999) || ' Synthetic Street',
            CASE WHEN g % 9 = 0 THEN 'Suite ' || (g % 200) ELSE NULL END,
            'District ' || (1 + g % 80),
            1 + ((g * 53 - 1) % {cities}),
            lpad(((g * 7919) % 100000)::text, 5, '0'),
            '+1-' || lpad(((g * 104729) % 10000000000)::text, 10, '0')
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=addresses,
            depends_on=("city",),
        ),
        LoadTask(
            "store",
            """
INSERT INTO store (store_id, manager_staff_id, address_id)
        SELECT g, g, g
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=stores,
            depends_on=("address",),
        ),
        LoadTask(
            "staff",
            f"""
INSERT INTO staff (staff_id, first_name, last_name, address_id, email, store_id, username, password)
        SELECT g,
            'Staff' || g,
            'Manager' || g,
            {stores} + g,
            'staff' || g || '@example.test',
            g,
            'staff_' || g,
            NULL
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=staff,
            depends_on=("address", "store"),
        ),
        LoadTask(
            "customer",
            f"""
INSERT INTO customer
            (customer_id, store_id, first_name, last_name, email, address_id, activebool,
            create_date, active)
        SELECT g,
            1 + ((g * 17 - 1) % {stores}),
            'Customer' || g,
            'Family' || (1 + (g * 31) % 500),
            CASE WHEN g % 20 = 0 THEN NULL ELSE 'customer' || g || '@example.test' END,
            {stores + staff} + g,
            g % 25 <> 0,
            DATE '2021-01-01' + ((g * 13) % 365)::integer,
            CASE WHEN g % 25 = 0 THEN 0 ELSE 1 END
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=customers,
            depends_on=("address", "store"),
        ),
        LoadTask(
            "actor",
            """
INSERT INTO actor (actor_id, first_name, last_name)
        SELECT g, 'Actor' || g, 'Surname' || (1 + (g * 43) % 300)
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=actors,
        ),
        LoadTask(
            "film",
            f"""
INSERT INTO film
            (film_id, title, description, release_year, language_id, original_language_id,
            rental_duration,
             rental_rate, length, replacement_cost, rating, special_features)
        SELECT g,
            'Synthetic Film ' || g,
            'A generated film in topic ' || (g % 50) || ' with popularity bucket ' || (g % 17),
            (1980 + (g * 7) % 43)::text::pagila.year,
            1 + ((g * 5 - 1) % {languages}),
            CASE WHEN g % 5 = 0 THEN 1 + ((g * 3 - 1) % {languages}) ELSE NULL END,
            2 + (g % 7),
            round((0.99 + power(det_uniform(g, 1), 1.8) * 5)::numeric, 2),
            45 + (g * 17) % 150,
            round((9.99 + power(det_uniform(g, 2), 1.5) * 25)::numeric, 2),
            (ARRAY['G'::pagila.mpaa_rating, 'PG', 'PG-13', 'R', 'NC-17'])[1 + (g % 5)],
            ARRAY['Trailers', CASE WHEN g % 3 = 0 THEN 'Commentaries' ELSE 'Deleted Scenes' END]
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=films,
            depends_on=("language",),
        ),
        LoadTask(
            "film_category",
            f"""
INSERT INTO film_category (film_id, category_id)
        SELECT g, 1 + ((g * 11 - 1) % {categories})
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=films,
            depends_on=("film", "category"),
        ),
        LoadTask(
            "film_actor",
            f"""
INSERT INTO film_actor (film_id, actor_id)
        SELECT film_id, 1 + ((film_id * 19 + actor_offset * 37 - 1) % {actors})
        FROM generate_series($1::bigint, $2::bigint) AS film_id
        CROSS JOIN LATERAL generate_series(1, 3 + (film_id % 5)) AS actor_offset;
        """,
            count=films,
            depends_on=("film", "actor"),
            max_rows_per_key=7,
        ),
        LoadTask(
            "inventory",
            f"""
INSERT INTO inventory (inventory_id, film_id, store_id)
        SELECT g,
            1 + floor(power(det_uniform(g, 3), 1.35) * {films})::bigint,
            1 + ((g * 7 - 1) % {stores})
        FROM generate_series($1::bigint, $2::bigint) AS g;
        """,
            count=inventory,
            depends_on=("film", "store"),
        ),
        LoadTask(
            "rental",
            f"""
INSERT INTO rental (rental_id, rental_date, inventory_id, customer_id, return_date, staff_id)
        SELECT g,
            rental_date,
            inventory_id,
            customer_id,
            CASE WHEN g % 7 = 0 THEN NULL ELSE rental_date + (1 + g % 8) * INTERVAL '1 day' END,
            1 + ((inventory_id - 1) % {staff})
        FROM (
            SELECT
                g,
                TIMESTAMPTZ '2022-01-01 00:00:00+00'
                    + ((g * 977) % (181 * 86400)) * INTERVAL '1 second' AS rental_date,
                1 + floor(power(det_uniform(g, 4), 1.25) * {inventory})::bigint AS inventory_id,
                1 + floor(power(det_uniform(g, 5), 1.8) * {customers})::bigint AS customer_id
            FROM generate_series($1::bigint, $2::bigint) AS g
        ) AS generated;
        """,
            count=rentals,
            depends_on=("inventory", "customer", "staff"),
        ),
        LoadTask(
            "payment",
            f"""
WITH payment_keys AS (
                    SELECT g AS payment_id, 1 + ((g - 1) % {rentals}) AS rental_id
                    FROM generate_series($1::bigint, $2::bigint) AS g
                ), rentals_generated AS (
                    SELECT payment_id, rental_id,
                        1 + floor(power(det_uniform(rental_id, 5),
            1.8) * {customers})::bigint AS customer_id,
                        1 + ((floor(power(det_uniform(rental_id, 4),
            1.25) * {inventory})::bigint) % {staff}) AS staff_id,
                        TIMESTAMPTZ '2022-01-01 00:00:00+00'
                            + ((rental_id * 977) % (181 * 86400)) * INTERVAL '1 second' AS
            rental_date
                    FROM payment_keys
                )
                INSERT INTO payment (payment_id, customer_id, staff_id, rental_id, amount,
            payment_date)
                SELECT payment_id, customer_id, staff_id, rental_id,
                    round((0.99 + power(det_uniform(payment_id, 6), 2.2) * 12)::numeric, 2),
                    LEAST(rental_date + (1 + payment_id % 72) * INTERVAL '1 hour',
                        TIMESTAMPTZ '2022-06-30 23:50:00+00')
                        + (payment_id / {rentals}) * INTERVAL '1 microsecond'
                FROM rentals_generated;
        """,
            count=payments,
            depends_on=("rental", "customer", "staff"),
        ),
    )
    root = Path(__file__).parent
    return LoadPlan(
        schemas=("pagila",),
        schema_sql=(root / "sql/pagila-schema.sql").read_text(),
        data=data,
        indexes=read_sql_tasks(root / "initialization-indexes.json"),
        constraints=read_sql_tasks(root / "initialization-constraints.json"),
        prepare_sql="""CREATE FUNCTION pagila.det_uniform(seed bigint, stream integer)
        RETURNS double precision
        LANGUAGE sql IMMUTABLE
        AS $$
            SELECT (hashint8($1 * 1000003 + $2 * 7919) & 2147483647)::double precision
                   / 2147483648.0
        $$;""",
        after_data_sql=f"""SELECT setval('pagila.language_language_id_seq', {languages}, true);
SELECT setval('pagila.category_category_id_seq', {categories}, true);
SELECT setval('pagila.country_country_id_seq', {countries}, true);
SELECT setval('pagila.city_city_id_seq', {cities}, true);
SELECT setval('pagila.address_address_id_seq', {addresses}, true);
SELECT setval('pagila.store_store_id_seq', {stores}, true);
SELECT setval('pagila.staff_staff_id_seq', {staff}, true);
SELECT setval('pagila.customer_customer_id_seq', {customers}, true);
SELECT setval('pagila.actor_actor_id_seq', {actors}, true);
SELECT setval('pagila.film_film_id_seq', {films}, true);
SELECT setval('pagila.inventory_inventory_id_seq', {inventory}, true);
SELECT setval('pagila.rental_rental_id_seq', {rentals}, true);
SELECT setval('pagila.payment_payment_id_seq', {payments}, true);
DROP FUNCTION pagila.det_uniform(bigint, integer);""",
        finalize_sql=(root / "sql/initialization-finalize.sql").read_text(),
    )


if __name__ == "__main__":
    generator_main(build_load_plan)
