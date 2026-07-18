DROP SCHEMA IF EXISTS pss_overflow CASCADE;

CREATE SCHEMA IF NOT EXISTS pss_overflow;

DO $$
DECLARE
    i INT;
BEGIN
    FOR i IN 1..1000 LOOP
        EXECUTE format('CREATE TABLE pss_overflow.table_%s (id INT PRIMARY KEY, value TEXT);', i);
        EXECUTE format('INSERT INTO pss_overflow.table_%s (id, value) VALUES (1, ''test'');', i);
    END LOOP;
END;
$$;

SELECT query FROM pg_stat_statements LIMIT 1;
