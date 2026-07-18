-- 1. Deadlock
\set deadlock_prob random(1, 100)
\if :deadlock_prob <= 5
BEGIN;
UPDATE emulate_errors.accounts SET balance = balance - 10 WHERE id = 1;
UPDATE emulate_errors.accounts SET balance = balance + 10 WHERE id = 2;
COMMIT;

BEGIN;
UPDATE emulate_errors.accounts SET balance = balance - 10 WHERE id = 2;
UPDATE emulate_errors.accounts SET balance = balance + 10 WHERE id = 1;
COMMIT;
\endif

-- 2. Unique Violation
\set unique_violation_prob random(1, 100)
\if :unique_violation_prob < 3
INSERT INTO emulate_errors.accounts (id, balance) VALUES (1, 400);
\endif

-- 3. Check Violation
\set check_violation_prob random(1, 100)
\if :check_violation_prob < 3
INSERT INTO emulate_errors.accounts (balance) VALUES (-100);
\endif

-- 4. Foreign Key Violation
\set fk_violation_prob random(1, 100)
\if :fk_violation_prob < 3
INSERT INTO emulate_errors.transactions (account_id, amount) VALUES (999, 100);
\endif

-- 5. Division by Zero
\set division_by_zero_prob random(1, 100)
\if :division_by_zero_prob < 3
SELECT 1 / 0;
\endif

-- 6. Syntax Error
\set syntax_error_prob random(1, 100)
\if :syntax_error_prob < 3
SELECT * FROM emulate_errors.accounts WHERE;
\endif

-- 7. Table Does Not Exist
\set table_not_exist_prob random(1, 100)
\if :table_not_exist_prob < 3
SELECT * FROM emulate_errors.non_existent_table;
\endif

-- 8. Column Does Not Exist
\set column_not_exist_prob random(1, 100)
\if :column_not_exist_prob < 3
SELECT non_existent_column FROM emulate_errors.accounts;
\endif

-- 9. Custom Error
\set invalid_data_type_prob random(1, 100)
\if :invalid_data_type_prob < 3
DO $$
BEGIN
    RAISE EXCEPTION 'Some error: %', md5(random()::text);
END $$;
\endif

-- 10. Runtime Error
\set runtime_error_prob random(1, 100)
\if :runtime_error_prob < 3
SELECT CAST('not_a_number' AS INTEGER);
\endif

-- 11. Lock Timeout
\set lock_timeout_prob random(1, 100)
\if :lock_timeout_prob < 3
BEGIN;
LOCK TABLE emulate_errors.accounts IN ACCESS EXCLUSIVE MODE;

SELECT pg_sleep(2);

LOCK TABLE emulate_errors.accounts IN ACCESS EXCLUSIVE MODE NOWAIT;

COMMIT;
\endif

-- 12. Permission Denied
\set permission_denied_prob random(1, 100)
\if :permission_denied_prob < 3
SELECT rolname FROM pg_authid LIMIT 1;
\endif

-- 13. Invalid Cursor State
\set invalid_cursor_state_prob random(1, 100)
\if :invalid_cursor_state_prob < 3
BEGIN;
DECLARE test_cursor CURSOR FOR SELECT * FROM emulate_errors.accounts;
CLOSE test_cursor;
FETCH test_cursor;
COMMIT;
\endif

-- 14. Invalid Data Type
\set invalid_data_type_prob random(1, 100)
\if :invalid_data_type_prob < 3
SELECT CAST('invalid' AS INTEGER);
\endif

-- 15. Invalid Source Table
\set invalid_name_prob random(1, 100)
\if :invalid_name_prob < 3
SELECT * FROM "invalid-table-name";
\endif
