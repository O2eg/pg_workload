DROP SCHEMA IF EXISTS pss_overflow CASCADE;

CREATE SCHEMA IF NOT EXISTS pss_overflow;

CREATE TABLE pss_overflow.profile_config (
    table_count integer NOT NULL CHECK (table_count > 0)
);

SELECT query FROM pg_stat_statements LIMIT 1;
