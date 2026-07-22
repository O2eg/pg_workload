from __future__ import annotations

import argparse
import math
import os
import subprocess


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic movie analytics data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    companies = scaled(10_000, args.scale, 100)
    people = scaled(100_000, args.scale, 1_000)
    keywords = scaled(20_000, args.scale, 500)
    titles = scaled(100_000, args.scale, 1_000)
    cast_rows = scaled(600_000, args.scale, titles * 3)
    keyword_rows = scaled(300_000, args.scale, titles * 2)
    company_rows = scaled(150_000, args.scale, titles)
    info_rows = scaled(250_000, args.scale, titles * 2)

    sql = f"""
        SET search_path = imdb;
        SELECT setseed(0.14142135);

        INSERT INTO kind_type (name)
        SELECT unnest(ARRAY['movie', 'series', 'episode', 'short', 'documentary', 'animation']);

        INSERT INTO genre (name)
        SELECT unnest(ARRAY[
            'Action', 'Adventure', 'Animation', 'Comedy', 'Crime', 'Documentary', 'Drama',
            'Family', 'Fantasy', 'History', 'Horror', 'Music', 'Mystery', 'Romance',
            'Science Fiction', 'Sport', 'Thriller', 'War', 'Western', 'Biography'
        ]);

        INSERT INTO company (name, country_code)
        SELECT
            'Studio ' || g,
            (ARRAY['US', 'GB', 'DE', 'FR', 'CA', 'JP', 'IN', 'ES', 'IT', 'AU'])[1 + (g * 7) % 10]
        FROM generate_series(1, {companies}) AS g;

        INSERT INTO person (name, gender, birth_year)
        SELECT
            'Person ' || g || ' Family ' || (g % 5000),
            CASE WHEN g % 11 = 0 THEN NULL WHEN g % 2 = 0 THEN 'F' ELSE 'M' END,
            1930 + (g * 17) % 75
        FROM generate_series(1, {people}) AS g;

        INSERT INTO keyword (keyword)
        SELECT 'keyword-' || g || '-topic-' || (g % 200)
        FROM generate_series(1, {keywords}) AS g;

        INSERT INTO title
            (title, kind_id, genre_id, production_year, runtime_minutes, rating, votes)
        SELECT
            'Synthetic Title ' || g,
            1 + ((g * 5 - 1) % 6),
            1 + ((g * 13 - 1) % 20),
            1950 + (g * 17) % 73,
            40 + (g * 29) % 150,
            round((2.0 + power(random(), 0.65) * 8.0)::numeric, 1),
            floor(power(random(), 2.8) * 500000)::integer
        FROM generate_series(1, {titles}) AS g;

        INSERT INTO cast_info (title_id, person_id, role_type, billing_order)
        SELECT
            1 + ((g::bigint * 104729 - 1) % {titles}),
            1 + floor(power(random(), 1.8) * {people})::bigint,
            (ARRAY['actor', 'actress', 'director', 'writer', 'producer'])[1 + (g * 3) % 5],
            1 + (g % 20)
        FROM generate_series(1, {cast_rows}) AS g;

        INSERT INTO movie_keyword (title_id, keyword_id)
        SELECT
            1 + ((g::bigint * 65537 - 1) % {titles}),
            1 + floor(power(random(), 2.3) * {keywords})::bigint
        FROM generate_series(1, {keyword_rows}) AS g;

        INSERT INTO movie_company (title_id, company_id, company_type)
        SELECT
            1 + ((g::bigint * 32771 - 1) % {titles}),
            1 + floor(power(random(), 2.0) * {companies})::bigint,
            (ARRAY['production', 'distributor', 'effects', 'post-production'])[1 + (g % 4)]
        FROM generate_series(1, {company_rows}) AS g;

        INSERT INTO movie_info (title_id, info_type, info)
        SELECT
            1 + ((g::bigint * 8191 - 1) % {titles}),
            (ARRAY['budget', 'gross', 'language', 'location'])[1 + (g % 4)],
            CASE g % 4
                WHEN 0 THEN '$' || (100000 + (g::bigint * 7919) % 200000000)
                WHEN 1 THEN '$' || (50000 + (g::bigint * 15485863) % 500000000)
                WHEN 2 THEN (ARRAY['English', 'Spanish', 'German', 'French', 'Japanese'])[1 + g % 5]
                ELSE 'Location ' || (g % 1000)
            END
        FROM generate_series(1, {info_rows}) AS g;
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(
        "Generated imdb: "
        f"companies={companies}, people={people}, keywords={keywords}, titles={titles}, "
        f"cast_info={cast_rows}, movie_keyword={keyword_rows}, movie_company={company_rows}, "
        f"movie_info={info_rows}"
    )


if __name__ == "__main__":
    main()
