from __future__ import annotations

import argparse
import math
import os
import subprocess


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate relational synthetic Pagila data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    stores = max(2, round(2 * max(1.0, args.scale**0.5)))
    staff = stores
    countries = scaled(109, args.scale, 10)
    cities = scaled(600, args.scale, 50)
    customers = scaled(600, args.scale, 100)
    addresses = stores + staff + customers
    actors = scaled(200, args.scale, 50)
    films = scaled(1_000, args.scale, 100)
    inventory = scaled(4_500, args.scale, films * 2)
    rentals = scaled(16_000, args.scale, 1_000)
    payments = scaled(16_500, args.scale, rentals)
    categories = 16
    languages = 6

    sql = f"""
        SET search_path = pagila;
        SELECT setseed(0.61803398);

        INSERT INTO language (name)
        SELECT rpad((ARRAY['English', 'Italian', 'Japanese', 'Mandarin', 'French', 'German'])[g], 20)
        FROM generate_series(1, {languages}) AS g;

        INSERT INTO category (name)
        SELECT (ARRAY[
            'Action', 'Animation', 'Children', 'Classics', 'Comedy', 'Documentary', 'Drama', 'Family',
            'Foreign', 'Games', 'Horror', 'Music', 'New', 'Science Fiction', 'Sports', 'Travel'
        ])[g]
        FROM generate_series(1, {categories}) AS g;

        INSERT INTO country (country)
        SELECT 'Country ' || lpad(g::text, 3, '0')
        FROM generate_series(1, {countries}) AS g;

        INSERT INTO city (city, country_id)
        SELECT 'City ' || g, 1 + ((g * 37 - 1) % {countries})
        FROM generate_series(1, {cities}) AS g;

        INSERT INTO address (address, address2, district, city_id, postal_code, phone)
        SELECT
            (10 + (g * 17) % 9999) || ' Synthetic Street',
            CASE WHEN g % 9 = 0 THEN 'Suite ' || (g % 200) ELSE NULL END,
            'District ' || (1 + g % 80),
            1 + ((g * 53 - 1) % {cities}),
            lpad(((g * 7919) % 100000)::text, 5, '0'),
            '+1-' || lpad(((g * 104729) % 10000000000)::text, 10, '0')
        FROM generate_series(1, {addresses}) AS g;

        INSERT INTO store (manager_staff_id, address_id)
        SELECT g, g
        FROM generate_series(1, {stores}) AS g;

        INSERT INTO staff (first_name, last_name, address_id, email, store_id, username, password)
        SELECT
            'Staff' || g,
            'Manager' || g,
            {stores} + g,
            'staff' || g || '@example.test',
            g,
            'staff_' || g,
            NULL
        FROM generate_series(1, {staff}) AS g;

        INSERT INTO customer
            (store_id, first_name, last_name, email, address_id, activebool, create_date, active)
        SELECT
            1 + ((g * 17 - 1) % {stores}),
            'Customer' || g,
            'Family' || (1 + (g * 31) % 500),
            CASE WHEN g % 20 = 0 THEN NULL ELSE 'customer' || g || '@example.test' END,
            {stores + staff} + g,
            g % 25 <> 0,
            DATE '2021-01-01' + ((g * 13) % 365),
            CASE WHEN g % 25 = 0 THEN 0 ELSE 1 END
        FROM generate_series(1, {customers}) AS g;

        INSERT INTO actor (first_name, last_name)
        SELECT 'Actor' || g, 'Surname' || (1 + (g * 43) % 300)
        FROM generate_series(1, {actors}) AS g;

        INSERT INTO film
            (title, description, release_year, language_id, original_language_id, rental_duration,
             rental_rate, length, replacement_cost, rating, special_features)
        SELECT
            'Synthetic Film ' || g,
            'A generated film in topic ' || (g % 50) || ' with popularity bucket ' || (g % 17),
            (1980 + (g * 7) % 43)::text::pagila.year,
            1 + ((g * 5 - 1) % {languages}),
            CASE WHEN g % 5 = 0 THEN 1 + ((g * 3 - 1) % {languages}) ELSE NULL END,
            2 + (g % 7),
            round((0.99 + power(random(), 1.8) * 5)::numeric, 2),
            45 + (g * 17) % 150,
            round((9.99 + power(random(), 1.5) * 25)::numeric, 2),
            (ARRAY['G'::pagila.mpaa_rating, 'PG', 'PG-13', 'R', 'NC-17'])[1 + (g % 5)],
            ARRAY['Trailers', CASE WHEN g % 3 = 0 THEN 'Commentaries' ELSE 'Deleted Scenes' END]
        FROM generate_series(1, {films}) AS g;

        INSERT INTO film_category (film_id, category_id)
        SELECT g, 1 + ((g * 11 - 1) % {categories})
        FROM generate_series(1, {films}) AS g;

        INSERT INTO film_actor (film_id, actor_id)
        SELECT film_id, 1 + ((film_id * 19 + actor_offset * 37 - 1) % {actors})
        FROM generate_series(1, {films}) AS film_id
        CROSS JOIN LATERAL generate_series(1, 3 + (film_id % 5)) AS actor_offset;

        INSERT INTO inventory (film_id, store_id)
        SELECT
            1 + floor(power(random(), 1.35) * {films})::integer,
            1 + ((g * 7 - 1) % {stores})
        FROM generate_series(1, {inventory}) AS g;

        INSERT INTO rental (rental_date, inventory_id, customer_id, return_date, staff_id)
        SELECT
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
                1 + floor(power(random(), 1.25) * {inventory})::integer AS inventory_id,
                1 + floor(power(random(), 1.8) * {customers})::integer AS customer_id
            FROM generate_series(1, {rentals}) AS g
        ) AS generated;

        INSERT INTO payment (customer_id, staff_id, rental_id, amount, payment_date)
        SELECT
            rental.customer_id,
            rental.staff_id,
            rental.rental_id,
            round((0.99 + power(random(), 2.2) * 12)::numeric, 2),
            LEAST(
                rental.rental_date + (1 + g % 72) * INTERVAL '1 hour',
                TIMESTAMPTZ '2022-06-30 23:50:00+00'
            ) + (g / {rentals}) * INTERVAL '1 microsecond'
        FROM generate_series(1, {payments}) AS g
        JOIN rental ON rental.rental_id = 1 + ((g - 1) % {rentals});

        ANALYZE language;
        ANALYZE category;
        ANALYZE country;
        ANALYZE city;
        ANALYZE address;
        ANALYZE store;
        ANALYZE staff;
        ANALYZE customer;
        ANALYZE actor;
        ANALYZE film;
        ANALYZE film_actor;
        ANALYZE film_category;
        ANALYZE inventory;
        ANALYZE rental;
        ANALYZE payment;
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(
        "Generated pagila: "
        f"stores={stores}, staff={staff}, countries={countries}, cities={cities}, "
        f"customers={customers}, actors={actors}, films={films}, inventory={inventory}, "
        f"rentals={rentals}, payments={payments}"
    )


if __name__ == "__main__":
    main()
