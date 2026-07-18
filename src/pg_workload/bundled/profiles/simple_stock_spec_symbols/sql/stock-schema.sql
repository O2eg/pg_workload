DROP SCHEMA IF EXISTS simple_stock_spec_symbols CASCADE;

CREATE SCHEMA IF NOT EXISTS simple_stock_spec_symbols;

SET search_path = "simple_stock_spec_symbols";

CREATE TABLE "Aufträge_1"
(
    "µ" bigserial,
    """.Name""$#@&" character varying(128),
    CONSTRAINT "pkey_"".Name""$#'@&" UNIQUE ("µ")
);

CREATE TABLE "Aufträge_2"
(
    "µ" bigserial,
    """.Name""$#@&" character varying(128),
    CONSTRAINT order_items_2_pkey UNIQUE ("µ")
);

CREATE TABLE "Stock_$#@.&\n\r_items" (
    "µ" bigserial,
    "order_items_1_µ" integer NOT NULL,
    "order_items_2_µ" integer NOT NULL,
    amount numeric(16,4) DEFAULT 0 NOT NULL,
    optcounter smallint DEFAULT 0 NOT NULL,
    "<b>Beschreibung</b>$#@&\n" text,
    "Preis<script>alert('XSS');</script>$#@&" decimal(19,4),
    "Menge\tTab$#@&" float(53),
    "Bewertung漢字$#@&" real,
    "Prozentsatz😊$#@&" numeric(5,2),
    "Kleinster_Wert<style>*{color:red;}</style>$#@&" smallint,
    "Groesster_Wert!@#$%^&*()_+{}[]|\:;'<>,.?/~`""$#@&" bigint,
    "Genauigkeit\nNewLine" numeric(20,10),
    "Fließkomma\r\nCRLF$#@&" double precision,
    "ThisIsAVeryLongFieldNameThatWillBreakTheLayoutIfNotHandledPrope" text,
    CONSTRAINT stock_items_pk UNIQUE ("µ")
);


ALTER TABLE ONLY "Stock_$#@.&\n\r_items"
    ADD CONSTRAINT stock_items_fk01 FOREIGN KEY ("order_items_1_µ") REFERENCES "Aufträge_1"("µ");
ALTER TABLE ONLY "Stock_$#@.&\n\r_items"
    ADD CONSTRAINT stock_items_fk02 FOREIGN KEY ("order_items_2_µ") REFERENCES "Aufträge_2"("µ");
