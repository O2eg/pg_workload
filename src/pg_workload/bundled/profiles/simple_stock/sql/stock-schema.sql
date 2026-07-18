
DROP SCHEMA IF EXISTS simple_stock CASCADE;

CREATE SCHEMA IF NOT EXISTS simple_stock;

CREATE TABLE simple_stock.order_items_1
(
    id bigserial,
    name character varying(32),
    CONSTRAINT order_items_1_pkey UNIQUE (id)
);

CREATE TABLE simple_stock.order_items_2
(
    id bigserial,
    name character varying(32),
    CONSTRAINT order_items_2_pkey UNIQUE (id)
);

CREATE TABLE simple_stock.stock_items (
    id bigserial,
    order_items_1_id integer NOT NULL,
    order_items_2_id integer NOT NULL,
    amount numeric(16,4) DEFAULT 0 NOT NULL,
    optcounter smallint DEFAULT 0 NOT NULL,
    descr text,
    CONSTRAINT stock_items_pk UNIQUE (id)
);

ALTER TABLE ONLY simple_stock.stock_items
    ADD CONSTRAINT stock_items_fk01 FOREIGN KEY (order_items_1_id) REFERENCES simple_stock.order_items_1(id);
ALTER TABLE ONLY simple_stock.stock_items
    ADD CONSTRAINT stock_items_fk02 FOREIGN KEY (order_items_2_id) REFERENCES simple_stock.order_items_2(id);
