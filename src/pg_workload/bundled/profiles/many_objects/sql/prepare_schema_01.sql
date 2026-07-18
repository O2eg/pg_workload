
DROP SCHEMA IF EXISTS many_objects CASCADE;

CREATE SCHEMA many_objects;

DO $$
DECLARE
    schema_name text;
BEGIN
    set search_path = 'public';

    FOR schema_name IN
        SELECT nspname
        FROM pg_namespace
        WHERE nspname LIKE 'many_objects_%'
    LOOP
        BEGIN
            EXECUTE format('DROP SCHEMA %I CASCADE', schema_name);
            RAISE NOTICE 'Dropped schema: %', schema_name;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Error dropping schema %: %', schema_name, SQLERRM;
        END;
    END LOOP;

END $$;
