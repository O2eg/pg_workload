SET search_path = "simple_stock_spec_symbols";

CREATE INDEX stock_items_description_hash_idx
    ON "Stock_$#@.&\n\r_items" USING hash ("ThisIsAVeryLongFieldNameThatWillBreakTheLayoutIfNotHandledPrope");
CREATE INDEX "stock_items_µ_idx_01" ON "Stock_$#@.&\n\r_items" USING btree ("order_items_2_µ");
CREATE INDEX stock_items_µ_idx_02 ON "Stock_$#@.&\n\r_items" USING btree ("order_items_1_µ");

ANALYZE "Aufträge_1";
ANALYZE "Aufträge_2";
ANALYZE "Stock_$#@.&\n\r_items";
