CREATE INDEX stock_items_descr_hash_idx ON simple_stock.stock_items USING hash (descr);
CREATE INDEX stock_items_order_2_idx ON simple_stock.stock_items USING btree (order_items_2_id);
CREATE INDEX stock_items_order_1_idx ON simple_stock.stock_items USING btree (order_items_1_id);

ANALYZE simple_stock.order_items_1;
ANALYZE simple_stock.order_items_2;
ANALYZE simple_stock.stock_items;
