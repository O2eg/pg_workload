SET search_path = "simple_stock_spec_symbols";

BEGIN;
INSERT INTO "Stock_$#@.&\n\r_items"
    ("order_items_1_µ", "order_items_2_µ", amount, optcounter,
     "<b>Beschreibung</b>$#@&\n", "Preis<script>alert('XSS');</script>$#@&", "Menge\tTab$#@&", "Bewertung漢字$#@&",
     "Prozentsatz😊$#@&", "Kleinster_Wert<style>*{color:red;}</style>$#@&", "Groesster_Wert!@#$%^&*()_+{}[]|\:;'<>,.?/~`""$#@&",
     "Genauigkeit\nNewLine", "Fließkomma\r\nCRLF$#@&", "ThisIsAVeryLongFieldNameThatWillBreakTheLayoutIfNotHandledPrope")
SELECT
    1 + floor(random() * (SELECT max("µ") FROM "Aufträge_1"))::integer,
    1 + floor(random() * (SELECT max("µ") FROM "Aufträge_2"))::integer,
    floor(random() * 500)::integer, -- amount
    floor(random() * 20000)::integer, -- optcounter
    'Beschreibung ' || generate_series(1,50) || ' <script>alert("XSS!");</script> <!-- SQL --> OR 1=1; --', -- Beschreibung$#@&\n
    random() * 10000, -- Preis$#@& (decimal(19,4) - no NaN/Infinity)
    CASE
        WHEN random() < 0.1 THEN 'NaN'::float -- NaN (Not a Number)
        WHEN random() < 0.2 THEN 'Infinity'::float -- Infinity
        WHEN random() < 0.3 THEN '-Infinity'::float -- -Infinity
        ELSE random() * 1e18 -- Very large floating-point value
    END AS "Menge\tTab$#@&", -- Menge$#@& (float)
    CASE
        WHEN random() < 0.1 THEN 'NaN'::real -- NaN (Not a Number)
        WHEN random() < 0.2 THEN 'Infinity'::real -- Infinity
        WHEN random() < 0.3 THEN '-Infinity'::real -- -Infinity
        ELSE random() * 100 -- Normal floating-point value
    END AS "Bewertung漢字$#@&", -- Bewertung$#@& (real)
    random() * 100, -- Prozentsatz$#@& (numeric(5,2) - no NaN/Infinity)
    floor(random() * 32767)::smallint, -- Kleinster_Wert$#@&
    floor(random() * 9223372036854775807)::bigint, -- Groesster_Wert$#@&
    random() * 100 AS "Genauigkeit\nNewLine", -- Genauigkeit$#@& (numeric)
    CASE
        WHEN random() < 0.1 THEN 'NaN'::double precision -- NaN (Not a Number)
        WHEN random() < 0.2 THEN 'Infinity'::double precision -- Infinity
        WHEN random() < 0.3 THEN '-Infinity'::double precision -- -Infinity
        ELSE random() * 1e18 -- Very large floating-point value
    END AS "Fließkomma\r\nCRLF$#@&", -- Fließkomma$#@& (double precision)
    'descr ' || generate_series(1,50) || ' <script>alert("XSS!");</script> <!-- SQL --> OR 1=1; DROP TABLE "Stock_$#@.&\n\r_items"; --' -- "ThisIsAVeryLongFieldNameThatWillBreakTheLayoutIfNotHandledPrope";
COMMIT;

BEGIN;
UPDATE "Stock_$#@.&\n\r_items"
SET "ThisIsAVeryLongFieldNameThatWillBreakTheLayoutIfNotHandledPrope" = 'updated at ' || now() || ' <script>alert("SQL injection attempt!");</script>  -- "XSS" attack',
    amount = amount + 1
WHERE "order_items_1_µ" in (
    SELECT T."order_items_1_µ" from(
        SELECT "µ" AS "order_items_1_µ" FROM "Aufträge_1" ORDER BY random() LIMIT 100
    ) T
);
COMMIT;

BEGIN;
DELETE FROM "Stock_$#@.&\n\r_items"
WHERE "order_items_1_µ" in (
    SELECT T."order_items_1_µ" from(
        SELECT "µ" AS "order_items_1_µ" FROM "Aufträge_1" ORDER BY random() LIMIT 100
    ) T
);
COMMIT;

\set v1 random(14000, 15000)
\set v2 random(15000, 16000)

BEGIN;
SELECT
    t1."µ",
    t1."order_items_1_µ",
    t1."order_items_2_µ",
    t1.optcounter,
    t1."<b>Beschreibung</b>$#@&\n",
    t1."Preis<script>alert('XSS');</script>$#@&",
    t1."Menge\tTab$#@&",
    t1."Bewertung漢字$#@&",
    t1."Prozentsatz😊$#@&",
    t1."Kleinster_Wert<style>*{color:red;}</style>$#@&",
    t1."Groesster_Wert!@#$%^&*()_+{}[]|\:;'<>,.?/~`""$#@&",
    t1."Genauigkeit\nNewLine",
    t1."Fließkomma\r\nCRLF$#@&",
    t1."ThisIsAVeryLongFieldNameThatWillBreakTheLayoutIfNotHandledPrope",
    max(t1.amount) as max_amount
FROM "Stock_$#@.&\n\r_items" t1
JOIN "Aufträge_1" oi1 ON t1."order_items_1_µ" = oi1."µ"
JOIN "Aufträge_2" oi2 ON t1."order_items_2_µ" = oi2."µ"
WHERE t1.optcounter > :v1 AND t1.optcounter < :v2
GROUP BY
    t1."µ",
    t1."order_items_1_µ",
    t1."order_items_2_µ",
    t1.optcounter,
    t1."<b>Beschreibung</b>$#@&\n",
    t1."Preis<script>alert('XSS');</script>$#@&",
    t1."Menge\tTab$#@&",
    t1."Bewertung漢字$#@&",
    t1."Prozentsatz😊$#@&",
    t1."Kleinster_Wert<style>*{color:red;}</style>$#@&",
    t1."Groesster_Wert!@#$%^&*()_+{}[]|\:;'<>,.?/~`""$#@&",
    t1."Genauigkeit\nNewLine",
    t1."Fließkomma\r\nCRLF$#@&",
    t1."ThisIsAVeryLongFieldNameThatWillBreakTheLayoutIfNotHandledPrope";
COMMIT;
