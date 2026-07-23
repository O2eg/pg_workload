DROP SCHEMA IF EXISTS bloat_vacuum CASCADE;
CREATE SCHEMA bloat_vacuum;

-- Several secondary indexes on columns the churn job updates: every update
-- is non-HOT and leaves dead tuples in both the heap and the indexes.
CREATE TABLE bloat_vacuum.accounts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_name text NOT NULL,
    balance numeric(14, 2) NOT NULL,
    status text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    filler text NOT NULL
);

CREATE INDEX accounts_balance_idx ON bloat_vacuum.accounts (balance);
CREATE INDEX accounts_status_idx ON bloat_vacuum.accounts (status);
CREATE INDEX accounts_updated_at_idx ON bloat_vacuum.accounts (updated_at);
