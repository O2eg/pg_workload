
create schema imdb;

set search_path = 'imdb';

CREATE TABLE aka_name (
    id bigint NOT NULL,
    person_id bigint NOT NULL,
    name text NOT NULL,
    imdb_index character varying(12),
    name_pcode_cf character varying(5),
    name_pcode_nf character varying(5),
    surname_pcode character varying(5),
    md5sum character varying(32)
);

CREATE TABLE aka_title (
    id bigint NOT NULL,
    movie_id bigint NOT NULL,
    title text NOT NULL,
    imdb_index character varying(12),
    kind_id bigint NOT NULL,
    production_year integer,
    phonetic_code character varying(5),
    episode_of_id bigint,
    season_nr integer,
    episode_nr integer,
    note text,
    md5sum character varying(32)
);

CREATE TABLE cast_info (
    id bigint NOT NULL,
    person_id bigint NOT NULL,
    movie_id bigint NOT NULL,
    person_role_id bigint,
    note text,
    nr_order integer,
    role_id bigint NOT NULL
);

CREATE TABLE char_name (
    id bigint NOT NULL,
    name text NOT NULL,
    imdb_index character varying(12),
    imdb_id bigint,
    name_pcode_nf character varying(5),
    surname_pcode character varying(5),
    md5sum character varying(32)
);

CREATE TABLE comp_cast_type (
    id bigint NOT NULL,
    kind character varying(32) NOT NULL
);

CREATE TABLE company_name (
    id bigint NOT NULL,
    name text NOT NULL,
    country_code character varying(255),
    imdb_id bigint,
    name_pcode_nf character varying(5),
    name_pcode_sf character varying(5),
    md5sum character varying(32)
);

CREATE TABLE company_type (
    id bigint NOT NULL,
    kind character varying(32) NOT NULL
);

CREATE TABLE complete_cast (
    id bigint NOT NULL,
    movie_id bigint,
    subject_id bigint NOT NULL,
    status_id bigint NOT NULL
);

CREATE TABLE info_type (
    id bigint NOT NULL,
    info character varying(32) NOT NULL
);

CREATE TABLE keyword (
    id bigint NOT NULL,
    keyword text NOT NULL,
    phonetic_code character varying(5)
);

CREATE TABLE kind_type (
    id bigint NOT NULL,
    kind character varying(15) NOT NULL
);

CREATE TABLE link_type (
    id bigint NOT NULL,
    link character varying(32) NOT NULL
);

CREATE TABLE movie_companies (
    id bigint NOT NULL,
    movie_id bigint NOT NULL,
    company_id bigint NOT NULL,
    company_type_id bigint NOT NULL,
    note text
);

CREATE TABLE movie_info (
    id bigint NOT NULL,
    movie_id bigint NOT NULL,
    info_type_id bigint NOT NULL,
    info text NOT NULL,
    note text
);

CREATE TABLE movie_info_idx (
    id bigint NOT NULL,
    movie_id bigint NOT NULL,
    info_type_id bigint NOT NULL,
    info text NOT NULL,
    note text
);

CREATE TABLE movie_keyword (
    id bigint NOT NULL,
    movie_id bigint NOT NULL,
    keyword_id bigint NOT NULL
);

CREATE TABLE movie_link (
    id bigint NOT NULL,
    movie_id bigint NOT NULL,
    linked_movie_id bigint NOT NULL,
    link_type_id bigint NOT NULL
);

CREATE TABLE name (
    id bigint NOT NULL,
    name text NOT NULL,
    imdb_index character varying(12),
    imdb_id bigint,
    gender character varying(1),
    name_pcode_cf character varying(5),
    name_pcode_nf character varying(5),
    surname_pcode character varying(5),
    md5sum character varying(32)
);

CREATE TABLE person_info (
    id bigint NOT NULL,
    person_id bigint NOT NULL,
    info_type_id bigint NOT NULL,
    info text NOT NULL,
    note text
);

CREATE TABLE role_type (
    id bigint NOT NULL,
    role character varying(32) NOT NULL
);

CREATE TABLE title (
    id bigint NOT NULL,
    title text NOT NULL,
    imdb_index character varying(12),
    kind_id bigint NOT NULL,
    production_year integer,
    imdb_id bigint,
    phonetic_code character varying(5),
    episode_of_id bigint,
    season_nr integer,
    episode_nr integer,
    series_years character varying(49),
    md5sum character varying(32)
);
