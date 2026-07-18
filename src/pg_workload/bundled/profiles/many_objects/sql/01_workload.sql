SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    a.attname AS column_name,
    pg_get_expr(ad.adbin, ad.adrelid) AS default_value,
    t.typname AS data_type,
    ic.relname AS index_name,
    pg_get_indexdef(i.indexrelid) AS index_definition,
    pgd.description AS table_description,
    pga.description AS column_description,
    con.conname AS constraint_name,  -- Constraint name
    pg_get_constraintdef(con.oid) AS constraint_definition -- Constraint definition
FROM
    pg_namespace n
JOIN
    pg_class c ON n.oid = c.relnamespace
LEFT JOIN
    pg_attribute a ON c.oid = a.attrelid
LEFT JOIN
    pg_attrdef ad ON a.attrelid = ad.adrelid AND a.attnum = ad.adnum
LEFT JOIN
    pg_type t ON a.atttypid = t.oid
LEFT JOIN
    pg_index i ON c.oid = i.indrelid
LEFT JOIN
    pg_class ic ON i.indexrelid = ic.oid
LEFT JOIN
    pg_description pgd ON c.oid = pgd.objoid AND pgd.classoid = 'pg_class'::regclass::oid
LEFT JOIN
    pg_description pga ON a.attrelid = pga.objoid AND pga.classoid = 'pg_attribute'::regclass::oid AND a.attnum = pga.objsubid
LEFT JOIN  -- Join for constraints
    pg_constraint con ON c.oid = con.conrelid AND a.attnum = ANY(con.conkey)
WHERE
    n.nspname LIKE 'many_objects_%'
ORDER BY
    n.nspname, c.relname, a.attnum;
