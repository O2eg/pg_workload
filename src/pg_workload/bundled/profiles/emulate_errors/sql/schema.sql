DROP SCHEMA IF EXISTS emulate_errors CASCADE;

CREATE SCHEMA emulate_errors;

CREATE TABLE emulate_errors.accounts (
    id SERIAL PRIMARY KEY,
    balance INTEGER NOT NULL
);

INSERT INTO emulate_errors.accounts (balance) VALUES (100), (200), (300);

CREATE TABLE emulate_errors.transactions (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES emulate_errors.accounts(id),
    amount INTEGER
);

INSERT INTO emulate_errors.transactions (account_id, amount) VALUES (1, 100);
