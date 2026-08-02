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
    characters = scaled(50_000, args.scale, 1_000)
    keywords = scaled(20_000, args.scale, 500)
    titles = scaled(100_000, args.scale, 1_000)
    cast_rows = scaled(600_000, args.scale, titles * 3)
    keyword_rows = scaled(300_000, args.scale, titles * 2)
    company_rows = scaled(150_000, args.scale, titles)
    info_rows = scaled(250_000, args.scale, titles * 2)
    info_index_rows = scaled(300_000, args.scale, titles * 3)
    movie_links = scaled(100_000, args.scale, titles)

    sql = f"""
        BEGIN;
        SET search_path = imdb;
        SELECT setseed(0.14142135);

        INSERT INTO kind_type (id, kind) VALUES
            (1, 'movie'),
            (2, 'tv series'),
            (3, 'episode'),
            (4, 'short'),
            (5, 'tv movie'),
            (6, 'video movie'),
            (7, 'video game');

        INSERT INTO company_type (id, kind) VALUES
            (1, 'production companies'),
            (2, 'distributors'),
            (3, 'special effects companies'),
            (4, 'miscellaneous companies');

        INSERT INTO info_type (id, info) VALUES
            (1, 'top 250 rank'),
            (2, 'bottom 10 rank'),
            (3, 'rating'),
            (4, 'genres'),
            (5, 'votes'),
            (6, 'budget'),
            (7, 'countries'),
            (8, 'release dates'),
            (9, 'mini biography'),
            (10, 'trivia'),
            (11, 'height'),
            (12, 'runtimes');

        INSERT INTO link_type (id, link) VALUES
            (1, 'sequel'),
            (2, 'follows'),
            (3, 'followed by'),
            (4, 'features'),
            (5, 'featured in'),
            (6, 'references'),
            (7, 'referenced in');

        INSERT INTO role_type (id, role) VALUES
            (1, 'actor'),
            (2, 'actress'),
            (3, 'writer'),
            (4, 'costume designer'),
            (5, 'producer'),
            (6, 'director');

        INSERT INTO comp_cast_type (id, kind) VALUES
            (1, 'cast'),
            (2, 'crew'),
            (3, 'complete'),
            (4, 'complete+verified');

        INSERT INTO company_name
            (id, name, country_code, imdb_id, name_pcode_nf, name_pcode_sf, md5sum)
        SELECT
            g,
            CASE g
                WHEN 1 THEN 'Lionsgate Synthetic'
                WHEN 2 THEN 'DreamWorks Animation'
                WHEN 3 THEN 'Warner Film Synthetic'
                WHEN 4 THEN '20th Century Fox Synthetic'
                WHEN 5 THEN 'Twentieth Century Fox Synthetic'
                WHEN 6 THEN 'Synthetic Japan Studio'
                WHEN 7 THEN 'Synthetic German Studio'
                WHEN 8 THEN 'Synthetic Netherlands Studio'
                WHEN 9 THEN 'Synthetic San Marino Studio'
                WHEN 10 THEN 'Synthetic Russian Studio'
                WHEN 11 THEN 'Synthetic Money Film'
                WHEN 12 THEN 'YouTube'
                WHEN 13 THEN 'Synthetic Warner Film'
                ELSE 'Synthetic Company ' || g
            END,
            CASE g
                WHEN 3 THEN '[pl]'
                WHEN 6 THEN '[jp]'
                WHEN 7 THEN '[de]'
                WHEN 8 THEN '[nl]'
                WHEN 9 THEN '[sm]'
                WHEN 10 THEN '[ru]'
                ELSE '[us]'
            END,
            100000 + g,
            left(md5('company-nf-' || g), 5),
            left(md5('company-sf-' || g), 5),
            md5('company-' || g)
        FROM generate_series(1, {companies}) AS g;

        INSERT INTO name
            (id, name, imdb_index, imdb_id, gender, name_pcode_cf, name_pcode_nf,
             surname_pcode, md5sum)
        SELECT
            g,
            CASE g
                WHEN 1 THEN 'Downey Synthetic Robert'
                WHEN 2 THEN 'Angela Synthetic Actress'
                WHEN 3 THEN 'Yoko Synthetic Voice'
                WHEN 4 THEN 'Tim Synthetic Writer'
                WHEN 5 THEN 'Bert Synthetic Actor'
                WHEN 6 THEN 'Alice Synthetic Designer'
                WHEN 7 THEN 'Zoe Synthetic Actor'
                WHEN 8 THEN 'Xavier Synthetic Actor'
                ELSE 'Synthetic Person ' || g || ' Family ' || (g % 5000)
            END,
            CASE WHEN g % 7 = 0 THEN 'I' || g ELSE NULL END,
            200000 + g,
            CASE
                WHEN g IN (2, 3, 6) THEN 'f'
                WHEN g IN (1, 4, 5, 7, 8) THEN 'm'
                WHEN g % 2 = 0 THEN 'f'
                ELSE 'm'
            END,
            CASE g WHEN 1 THEN 'D0001' WHEN 2 THEN 'A0002' WHEN 5 THEN 'B0005'
                ELSE chr(65 + (g % 6)) || lpad((g % 10000)::text, 4, '0') END,
            left(md5('name-nf-' || g), 5),
            left(md5('surname-' || g), 5),
            md5('person-' || g)
        FROM generate_series(1, {people}) AS g;

        INSERT INTO aka_name
            (id, person_id, name, imdb_index, name_pcode_cf, name_pcode_nf,
             surname_pcode, md5sum)
        SELECT
            source.id,
            source.id,
            'Alias ' || source.name,
            'A' || source.id,
            left(md5('aka-cf-' || source.id), 5),
            left(md5('aka-nf-' || source.id), 5),
            left(md5('aka-surname-' || source.id), 5),
            md5('aka-' || source.id)
        FROM name AS source;

        INSERT INTO char_name
            (id, name, imdb_index, imdb_id, name_pcode_nf, surname_pcode, md5sum)
        SELECT
            g,
            CASE g
                WHEN 1 THEN 'Tony Stark Synthetic Hero'
                WHEN 2 THEN 'Sherlock Synthetic Hero'
                WHEN 3 THEN 'Kung Fu Panda Synthetic Hero'
                WHEN 4 THEN 'Iron Man Synthetic Hero'
                WHEN 5 THEN 'Queen'
                ELSE 'Synthetic Character ' || g
            END,
            'C' || g,
            300000 + g,
            left(md5('character-nf-' || g), 5),
            left(md5('character-surname-' || g), 5),
            md5('character-' || g)
        FROM generate_series(1, {characters}) AS g;

        INSERT INTO keyword (id, keyword, phonetic_code)
        SELECT
            g,
            CASE g
                WHEN 1 THEN 'character-name-in-title'
                WHEN 2 THEN 'sequel'
                WHEN 3 THEN 'marvel-cinematic-universe'
                WHEN 4 THEN 'superhero'
                WHEN 5 THEN 'second-part'
                WHEN 6 THEN 'marvel-comics'
                WHEN 7 THEN 'based-on-comic'
                WHEN 8 THEN 'tv-special'
                WHEN 9 THEN 'fight'
                WHEN 10 THEN 'violence'
                WHEN 11 THEN 'revenge'
                WHEN 12 THEN 'based-on-novel'
                WHEN 13 THEN 'murder'
                WHEN 14 THEN 'murder-in-title'
                WHEN 15 THEN 'blood'
                WHEN 16 THEN 'gore'
                WHEN 17 THEN 'death'
                WHEN 18 THEN 'female-nudity'
                WHEN 19 THEN 'hospital'
                WHEN 20 THEN 'computer-animation'
                WHEN 21 THEN 'computer-animated-movie'
                WHEN 22 THEN 'hand-to-hand-combat'
                WHEN 23 THEN 'hero'
                WHEN 24 THEN 'alienation'
                WHEN 25 THEN 'dignity'
                WHEN 26 THEN 'loner'
                WHEN 27 THEN 'nerd'
                WHEN 28 THEN '10,000-mile-club'
                WHEN 29 THEN 'claw'
                WHEN 30 THEN 'laser'
                WHEN 31 THEN 'magnet'
                WHEN 32 THEN 'web'
                ELSE 'keyword-' || g || '-topic-' || (g % 200)
            END,
            left(md5('keyword-' || g), 5)
        FROM generate_series(1, {keywords}) AS g;

        INSERT INTO title
            (id, title, imdb_index, kind_id, production_year, imdb_id, phonetic_code,
             episode_of_id, season_nr, episode_nr, series_years, md5sum)
        SELECT
            g,
            CASE g
                WHEN 1 THEN 'Synthetic Hero Movie'
                WHEN 2 THEN 'One Piece Synthetic Feature'
                WHEN 3 THEN 'Dragon Ball Z Synthetic Feature'
                WHEN 4 THEN 'Birdemic Synthetic Movie'
                WHEN 5 THEN 'Champion Synthetic Movie'
                WHEN 6 THEN 'Loser Synthetic Movie'
                WHEN 7 THEN 'Murder Synthetic Movie'
                WHEN 8 THEN 'YouTube Synthetic Movie'
                WHEN 9 THEN 'Kung Fu Panda Synthetic Feature'
                WHEN 10 THEN 'Iron Man Synthetic Feature'
                WHEN 11 THEN 'Sherlock Synthetic Feature'
                WHEN 12 THEN 'Saw Synthetic Horror'
                WHEN 13 THEN 'Freddy Synthetic Horror'
                WHEN 14 THEN 'Jason Synthetic Horror'
                WHEN 15 THEN 'Vampire Synthetic Horror'
                WHEN 16 THEN 'Shrek 2'
                WHEN 17 THEN 'Synthetic TV Series First'
                WHEN 18 THEN 'Synthetic TV Series Second'
                WHEN 19 THEN 'Synthetic Biography'
                WHEN 20 THEN 'Synthetic VHS Movie'
                WHEN 21 THEN 'Money Synthetic Film'
                WHEN 22 THEN 'Kung Fu Panda Legacy'
                ELSE 'Synthetic Title ' || g
            END,
            CASE WHEN g % 9 = 0 THEN 'T' || g ELSE NULL END,
            CASE WHEN g IN (17, 18) THEN 2 WHEN g % 23 = 0 THEN 3 ELSE 1 END,
            CASE g
                WHEN 1 THEN 2016 WHEN 2 THEN 2007 WHEN 3 THEN 2006 WHEN 4 THEN 2009
                WHEN 5 THEN 2008 WHEN 6 THEN 2007 WHEN 7 THEN 2016 WHEN 8 THEN 2007
                WHEN 9 THEN 2011 WHEN 10 THEN 2015 WHEN 11 THEN 2012 WHEN 12 THEN 2007
                WHEN 13 THEN 2008 WHEN 14 THEN 2009 WHEN 15 THEN 2015 WHEN 16 THEN 2004
                WHEN 17 THEN 2006 WHEN 18 THEN 2007 WHEN 19 THEN 1982 WHEN 20 THEN 2016
                WHEN 21 THEN 1998 WHEN 22 THEN 2008
                ELSE 1950 + (g * 17) % 73
            END,
            400000 + g,
            left(md5('title-' || g), 5),
            NULL,
            NULL,
            CASE WHEN g = 1 THEN 60 ELSE NULL END,
            NULL,
            md5('title-' || g)
        FROM generate_series(1, {titles}) AS g;

        INSERT INTO aka_title
            (id, movie_id, title, imdb_index, kind_id, production_year, phonetic_code,
             episode_of_id, season_nr, episode_nr, note, md5sum)
        SELECT
            id,
            id,
            'Alternative ' || title,
            imdb_index,
            kind_id,
            production_year,
            phonetic_code,
            episode_of_id,
            season_nr,
            episode_nr,
            '(internet)',
            md5('aka-title-' || id)
        FROM title;

        INSERT INTO cast_info
            (id, person_id, movie_id, person_role_id, note, nr_order, role_id)
        SELECT
            g,
            1 + ((g::bigint * 104729 - 1) % {people}),
            1 + ((g::bigint * 65537 - 1) % {titles}),
            1 + ((g::bigint * 8191 - 1) % {characters}),
            (ARRAY['(producer)', '(writer)', '(voice)', '(uncredited)', NULL])[1 + g % 5],
            1 + g % 20,
            1 + g % 6
        FROM generate_series(1, {cast_rows}) AS g;

        WITH anchor_cast(person_id, person_role_id, note, role_id, nr_order) AS (
            VALUES
                (1, 1, '(producer)', 1, 1),
                (1, 1, '(voice) (uncredited)', 1, 2),
                (2, 5, '(voice)', 2, 3),
                (2, 5, '(writer)', 3, 4),
                (3, 3, '(voice: English version)', 2, 5),
                (4, 4, '(producer)', 5, 6),
                (4, 4, '(writer)', 3, 7),
                (5, 1, '(uncredited)', 1, 8),
                (6, 2, '(costume designer)', 4, 9),
                (7, 1, '(actor)', 1, 10),
                (8, 1, '(actor)', 1, 11)
        )
        INSERT INTO cast_info
            (id, person_id, movie_id, person_role_id, note, nr_order, role_id)
        SELECT
            {cast_rows} + (movie_id - 1) * 11 + nr_order,
            person_id,
            movie_id,
            person_role_id,
            note,
            nr_order,
            role_id
        FROM generate_series(1, 22) AS movie_id
        CROSS JOIN anchor_cast;

        INSERT INTO movie_keyword (id, movie_id, keyword_id)
        SELECT
            g,
            1 + ((g::bigint * 65537 - 1) % {titles}),
            1 + ((g::bigint * 32771 - 1) % {keywords})
        FROM generate_series(1, {keyword_rows}) AS g;

        INSERT INTO movie_keyword (id, movie_id, keyword_id)
        SELECT
            {keyword_rows} + (movie_id - 1) * 32 + keyword_id,
            movie_id,
            keyword_id
        FROM generate_series(1, 22) AS movie_id
        CROSS JOIN generate_series(1, 32) AS keyword_id;

        INSERT INTO movie_companies
            (id, movie_id, company_id, company_type_id, note)
        SELECT
            g,
            1 + ((g::bigint * 32771 - 1) % {titles}),
            1 + ((g::bigint * 8191 - 1) % {companies}),
            1 + g % 4,
            CASE g % 4
                WHEN 0 THEN '(co-production) (presents)'
                WHEN 1 THEN '(worldwide) (2007)'
                WHEN 2 THEN '(Blu-ray) (USA)'
                ELSE '(theatrical) (France)'
            END
        FROM generate_series(1, {company_rows}) AS g;

        INSERT INTO movie_companies
            (id, movie_id, company_id, company_type_id, note)
        SELECT
            {company_rows} + (movie_id - 1) * 26 + (company_id - 1) * 2 + company_type_id,
            movie_id,
            company_id,
            company_type_id,
            CASE company_id
                WHEN 6 THEN '(Japan) (2006) (2007)'
                WHEN 3 THEN '(co-production) (presents) Synthetic Warner Film Money'
                WHEN 11 THEN '(co-production) (presents) Synthetic Film Money Warner'
                WHEN 13 THEN NULL
                ELSE '(co-production) (presents) (theatrical) (France) (VHS) (USA) '
                     || '(1994) (worldwide) (2007) (2008) (Blu-ray) Synthetic Film Money Warner'
            END
        FROM generate_series(1, 22) AS movie_id
        CROSS JOIN generate_series(1, 13) AS company_id
        CROSS JOIN generate_series(1, 2) AS company_type_id;

        INSERT INTO movie_info (id, movie_id, info_type_id, info, note)
        SELECT
            g,
            1 + ((g::bigint * 8191 - 1) % {titles}),
            (ARRAY[4, 6, 7, 8])[1 + g % 4],
            CASE g % 4
                WHEN 0 THEN (ARRAY['Horror', 'Thriller', 'Action', 'Sci-Fi'])[1 + g % 4]
                WHEN 1 THEN '$' || (100000 + (g::bigint * 7919) % 200000000)
                WHEN 2 THEN (ARRAY['USA', 'Germany', 'Sweden', 'Norway'])[1 + g % 4]
                ELSE 'USA: 2007'
            END,
            CASE WHEN g % 4 = 3 THEN '(internet)' ELSE NULL END
        FROM generate_series(1, {info_rows}) AS g;

        WITH anchor_info(info_type_id, info, note) AS (
            VALUES
                (4, 'Horror', NULL),
                (4, 'Thriller', NULL),
                (4, 'Action', NULL),
                (4, 'Sci-Fi', NULL),
                (4, 'Crime', NULL),
                (4, 'War', NULL),
                (4, 'Drama', NULL),
                (4, 'Family', NULL),
                (4, 'Western', NULL),
                (6, '$1000000', NULL),
                (7, 'Sweden', NULL),
                (7, 'Norway', NULL),
                (7, 'Germany', NULL),
                (7, 'Denmark', NULL),
                (7, 'Swedish', NULL),
                (7, 'Denish', NULL),
                (7, 'Norwegian', NULL),
                (7, 'German', NULL),
                (7, 'USA', NULL),
                (7, 'American', NULL),
                (7, 'Bulgaria', NULL),
                (8, 'USA: 1994', '(internet)'),
                (8, 'USA: 2007', '(internet)'),
                (8, 'USA: 2008', '(internet)'),
                (8, 'USA: 2011', '(internet)'),
                (8, 'Japan:2007', '(internet)'),
                (8, 'Japan:2011', '(internet)'),
                (10, 'Synthetic trivia', NULL),
                (11, '180 cm', NULL)
        )
        INSERT INTO movie_info (id, movie_id, info_type_id, info, note)
        SELECT
            ({info_rows} + row_number() OVER (ORDER BY movie_id, info_type_id, info))::integer,
            movie_id,
            info_type_id,
            info,
            note
        FROM generate_series(1, 22) AS movie_id
        CROSS JOIN anchor_info;

        INSERT INTO movie_info_idx (id, movie_id, info_type_id, info, note)
        SELECT
            g,
            1 + ((g::bigint * 8191 - 1) % {titles}),
            (ARRAY[1, 3, 5])[1 + g % 3],
            CASE g % 3
                WHEN 0 THEN (1 + g % 250)::text
                WHEN 1 THEN to_char(2.0 + random() * 8.0, 'FM99.0')
                ELSE (1000 + (g::bigint * 15485863) % 500000)::text
            END,
            NULL
        FROM generate_series(1, {info_index_rows}) AS g;

        WITH anchor_info_idx(info_type_id, info) AS (
            VALUES
                (1, '1'),
                (2, '1'),
                (3, '2.5'),
                (3, '9.5'),
                (5, '250000')
        )
        INSERT INTO movie_info_idx (id, movie_id, info_type_id, info, note)
        SELECT
            ({info_index_rows} + row_number() OVER (ORDER BY movie_id, info_type_id))::integer,
            movie_id,
            info_type_id,
            info,
            NULL
        FROM generate_series(1, 22) AS movie_id
        CROSS JOIN anchor_info_idx;

        INSERT INTO person_info (id, person_id, info_type_id, info, note)
        SELECT
            g,
            g,
            CASE WHEN g % 3 = 0 THEN 9 WHEN g % 3 = 1 THEN 10 ELSE 11 END,
            CASE WHEN g % 3 = 0 THEN 'Synthetic biography'
                 WHEN g % 3 = 1 THEN 'Synthetic trivia' ELSE '180 cm' END,
            CASE WHEN g % 3 = 0 THEN 'Volker Boehm' ELSE NULL END
        FROM generate_series(1, {people}) AS g;

        WITH anchor_person_info(info_type_id, info, note) AS (
            VALUES
                (9, 'Synthetic mini biography', 'Volker Boehm'),
                (10, 'Queen', 'Synthetic trivia'),
                (11, '180 cm', NULL)
        )
        INSERT INTO person_info (id, person_id, info_type_id, info, note)
        SELECT
            ({people} + row_number() OVER (ORDER BY person_id, info_type_id))::integer,
            person_id,
            info_type_id,
            info,
            note
        FROM generate_series(1, 6) AS person_id
        CROSS JOIN anchor_person_info;

        INSERT INTO complete_cast (id, movie_id, subject_id, status_id)
        SELECT g, 1 + (g - 1) % {titles}, 1 + g % 2, 4
        FROM generate_series(1, {titles} * 2) AS g;

        WITH anchor_complete_cast(subject_id, status_id) AS (
            VALUES (1, 3), (2, 3), (1, 4), (2, 4)
        )
        INSERT INTO complete_cast (id, movie_id, subject_id, status_id)
        SELECT
            ({titles} * 2 + row_number() OVER (ORDER BY movie_id, subject_id, status_id))::integer,
            movie_id,
            subject_id,
            status_id
        FROM generate_series(1, 22) AS movie_id
        CROSS JOIN anchor_complete_cast;

        INSERT INTO movie_link (id, movie_id, linked_movie_id, link_type_id)
        SELECT
            g,
            1 + (g - 1) % {titles},
            1 + g % {titles},
            1 + g % 7
        FROM generate_series(1, {movie_links}) AS g;

        INSERT INTO movie_link (id, movie_id, linked_movie_id, link_type_id)
        SELECT
            {movie_links} + (movie_id - 1) * 7 + link_type_id,
            movie_id,
            movie_id,
            link_type_id
        FROM generate_series(1, 22) AS movie_id
        CROSS JOIN generate_series(1, 7) AS link_type_id;

        COMMIT;
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(
        "Generated imdb: "
        f"companies={companies}, people={people}, characters={characters}, "
        f"keywords={keywords}, titles={titles}, cast_info={cast_rows}, "
        f"movie_keyword={keyword_rows}, movie_companies={company_rows}, "
        f"movie_info={info_rows}, movie_info_idx={info_index_rows}, "
        f"movie_link={movie_links}"
    )


if __name__ == "__main__":
    main()
