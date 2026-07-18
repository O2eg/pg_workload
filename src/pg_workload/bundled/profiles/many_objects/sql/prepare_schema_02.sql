DO $$
DECLARE
    schema_name TEXT;
    table_name TEXT := 'partitioned_table';
    partition_count INT := 20;      -- Number of partitions per schema
    subpartition_count INT := 20;   -- Number of subpartitions per partition
    i INT;
    j INT;
    partition_start TIMESTAMP;
    partition_end TIMESTAMP;
	last_schema_index INT;
BEGIN
    SELECT COALESCE(MAX(SUBSTRING(nspname FROM 'many_objects_([0-9]+)')::INT), 0)
    INTO last_schema_index
    FROM pg_namespace
    WHERE nspname LIKE 'many_objects_%';

    FOR i IN (last_schema_index + 1)..(last_schema_index + 5) LOOP
        schema_name := 'many_objects_' || i;

        -- Create the schema
        EXECUTE 'CREATE SCHEMA ' || schema_name;

        -- Create the partitioned table in the schema
        EXECUTE format('
            CREATE TABLE %I.%I (
                id SERIAL,
                created_at TIMESTAMP NOT NULL,
                data TEXT
            ) PARTITION BY RANGE (created_at);
        ', schema_name, table_name);

        -- Loop to create partitions
        FOR j IN 1..partition_count LOOP
            -- Calculate partition bounds
            partition_start := (j - 1) * interval '1 month' + '2000-01-01 00:00:00'::TIMESTAMP;
            partition_end := j * interval '1 month' + '2000-01-01 00:00:00'::TIMESTAMP;

            -- Create the partition
            EXECUTE format('
                CREATE TABLE %I.%I_partition_%s
                PARTITION OF %I.%I
                FOR VALUES FROM (%L) TO (%L)
                PARTITION BY LIST (data);
            ', schema_name, table_name, j, schema_name, table_name,
               partition_start, partition_end);

            -- Loop to create subpartitions
            FOR k IN 1..subpartition_count LOOP
                EXECUTE format('
                    CREATE TABLE %I.%I_partition_%s_subpartition_%s
                    PARTITION OF %I.%I_partition_%s
                    FOR VALUES IN (%L);
                ', schema_name, table_name, j, k, schema_name, table_name, j, 'value_' || k);
            END LOOP;
        END LOOP;

        -- Create indexes on the partitioned table
        EXECUTE format('
            CREATE INDEX ON %I.%I (created_at);
            CREATE INDEX ON %I.%I (data);
        ', schema_name, table_name, schema_name, table_name);

        RAISE NOTICE 'Created schema % and partitioned table with partitions and subpartitions.', schema_name;
    END LOOP;
END $$;
