DROP SCHEMA IF EXISTS partition_aging CASCADE;
CREATE SCHEMA partition_aging;

CREATE TABLE partition_aging.events (
    id bigint GENERATED ALWAYS AS IDENTITY,
    ts timestamptz NOT NULL,
    kind text NOT NULL,
    payload text NOT NULL,
    PRIMARY KEY (ts, id)
) PARTITION BY RANGE (ts);

CREATE INDEX events_kind_ts_idx ON partition_aging.events (kind, ts);
