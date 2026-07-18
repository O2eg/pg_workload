DROP SCHEMA IF EXISTS imdb CASCADE;
CREATE SCHEMA imdb;

CREATE TABLE imdb.kind_type (
    id smallserial PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE imdb.genre (
    id smallserial PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE imdb.company (
    id bigserial PRIMARY KEY,
    name text NOT NULL,
    country_code char(2) NOT NULL
);

CREATE TABLE imdb.person (
    id bigserial PRIMARY KEY,
    name text NOT NULL,
    gender char(1),
    birth_year smallint
);

CREATE TABLE imdb.keyword (
    id bigserial PRIMARY KEY,
    keyword text NOT NULL UNIQUE
);

CREATE TABLE imdb.title (
    id bigserial PRIMARY KEY,
    title text NOT NULL,
    kind_id smallint NOT NULL REFERENCES imdb.kind_type(id),
    genre_id smallint NOT NULL REFERENCES imdb.genre(id),
    production_year smallint NOT NULL,
    runtime_minutes smallint,
    rating numeric(3,1),
    votes integer NOT NULL
);

CREATE TABLE imdb.cast_info (
    id bigserial PRIMARY KEY,
    title_id bigint NOT NULL REFERENCES imdb.title(id),
    person_id bigint NOT NULL REFERENCES imdb.person(id),
    role_type text NOT NULL,
    billing_order smallint NOT NULL
);

CREATE TABLE imdb.movie_keyword (
    id bigserial PRIMARY KEY,
    title_id bigint NOT NULL REFERENCES imdb.title(id),
    keyword_id bigint NOT NULL REFERENCES imdb.keyword(id)
);

CREATE TABLE imdb.movie_company (
    id bigserial PRIMARY KEY,
    title_id bigint NOT NULL REFERENCES imdb.title(id),
    company_id bigint NOT NULL REFERENCES imdb.company(id),
    company_type text NOT NULL
);

CREATE TABLE imdb.movie_info (
    id bigserial PRIMARY KEY,
    title_id bigint NOT NULL REFERENCES imdb.title(id),
    info_type text NOT NULL,
    info text NOT NULL
);
