-- SQLite schema for beancount-sqlite
-- Dates are stored as TEXT in ISO 8601 format (YYYY-MM-DD).
-- Numeric amounts are stored as TEXT to preserve Decimal precision.

-- Account category table (hierarchical account tree)
CREATE TABLE IF NOT EXISTS account_category (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER,
    account_type TEXT NOT NULL CHECK (
        account_type IN (
            'Assets', 'Liabilities', 'Equity', 'Income', 'Expenses'
        )
    ),
    FOREIGN KEY (parent_id) REFERENCES account_category (id),
    UNIQUE (name, parent_id, account_type)
);

-- Account table (Open/Close directives)
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL CHECK (
        account_type IN (
            'Assets', 'Liabilities', 'Equity', 'Income', 'Expenses'
        )
    ),
    account_category_id INTEGER NOT NULL,
    open_date TEXT NOT NULL,
    close_date TEXT,
    FOREIGN KEY (account_category_id) REFERENCES account_category (id)
);

-- Currencies declared on an account (Open.currencies)
CREATE TABLE IF NOT EXISTS account_currency (
    account_id INTEGER NOT NULL,
    currency TEXT NOT NULL,
    PRIMARY KEY (account_id, currency),
    FOREIGN KEY (account_id) REFERENCES account (id)
);

-- Transaction table
CREATE TABLE IF NOT EXISTS "transaction" (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    flag TEXT NOT NULL,
    payee TEXT NOT NULL,
    narration TEXT NOT NULL
);

-- Tag table
CREATE TABLE IF NOT EXISTS tag (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- Transaction <-> tag junction
CREATE TABLE IF NOT EXISTS transaction_tag (
    transaction_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (transaction_id, tag_id),
    FOREIGN KEY (transaction_id) REFERENCES "transaction" (id),
    FOREIGN KEY (tag_id) REFERENCES tag (id)
);

-- Link table
CREATE TABLE IF NOT EXISTS link (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- Transaction <-> link junction
CREATE TABLE IF NOT EXISTS transaction_link (
    transaction_id INTEGER NOT NULL,
    link_id INTEGER NOT NULL,
    PRIMARY KEY (transaction_id, link_id),
    FOREIGN KEY (transaction_id) REFERENCES "transaction" (id),
    FOREIGN KEY (link_id) REFERENCES link (id)
);

-- Posting table
CREATE TABLE IF NOT EXISTS posting (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    transaction_id INTEGER NOT NULL,
    flag TEXT,
    amount_number TEXT NOT NULL,
    amount_currency TEXT NOT NULL,
    price_number TEXT,
    price_currency TEXT,
    cost_number TEXT,
    cost_currency TEXT,
    cost_date TEXT,
    cost_label TEXT,
    matching_lot_id INTEGER,
    FOREIGN KEY (account_id) REFERENCES account (id),
    FOREIGN KEY (transaction_id) REFERENCES "transaction" (id),
    FOREIGN KEY (matching_lot_id) REFERENCES posting (id)
);

CREATE INDEX IF NOT EXISTS posting_account_id_date_idx ON posting (
    account_id, date, id
);
CREATE INDEX IF NOT EXISTS posting_transaction_id_idx ON posting (
    transaction_id
);

-- Commodity table
CREATE TABLE IF NOT EXISTS commodity (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    currency TEXT NOT NULL UNIQUE CHECK (currency != ''),
    decimal_places INTEGER NOT NULL DEFAULT 0
);

-- Price table
CREATE TABLE IF NOT EXISTS price (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount_number TEXT NOT NULL,
    amount_currency TEXT NOT NULL
);

-- Assertion table (Balance directives)
CREATE TABLE IF NOT EXISTS assertion (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    amount_number TEXT NOT NULL,
    amount_currency TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES account (id)
);

-- Document table (file path only — no binary storage)
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES account (id)
);

-- Note table (Note directives)
CREATE TABLE IF NOT EXISTS note (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    comment TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES account (id)
);

-- Event table (Event directives)
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    type TEXT NOT NULL,
    description TEXT NOT NULL
);

-- Query table (Query directives)
CREATE TABLE IF NOT EXISTS "query" (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    name TEXT NOT NULL,
    query_string TEXT NOT NULL
);

-- Custom table (Custom directives)
CREATE TABLE IF NOT EXISTS "custom" (
    id INTEGER PRIMARY KEY,
    "date" TEXT NOT NULL,
    type TEXT NOT NULL,
    "values" TEXT NOT NULL DEFAULT '[]'
);

-- Metadata tables (normalized key/value, one row per metadata entry).
-- value_type encodes the original beancount grammar type:
--   str     → STRING, account name, currency, or tag token
--   bool    → BOOL
--   date    → DATE
--   decimal → number expression (Decimal)
--   amount  → amount literal, stored as "<number> <currency>"
--   null    → NONE or empty value

CREATE TABLE IF NOT EXISTS transaction_metadata (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES "transaction" (id)
);

CREATE TABLE IF NOT EXISTS posting_metadata (
    id INTEGER PRIMARY KEY,
    posting_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (posting_id) REFERENCES posting (id)
);

CREATE TABLE IF NOT EXISTS open_metadata (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES account (id)
);

CREATE TABLE IF NOT EXISTS close_metadata (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES account (id)
);

CREATE TABLE IF NOT EXISTS commodity_metadata (
    id INTEGER PRIMARY KEY,
    commodity_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (commodity_id) REFERENCES commodity (id)
);

CREATE TABLE IF NOT EXISTS balance_metadata (
    id INTEGER PRIMARY KEY,
    assertion_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (assertion_id) REFERENCES assertion (id)
);

CREATE TABLE IF NOT EXISTS note_metadata (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (note_id) REFERENCES note (id)
);

CREATE TABLE IF NOT EXISTS document_metadata (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES document (id)
);

CREATE TABLE IF NOT EXISTS price_metadata (
    id INTEGER PRIMARY KEY,
    price_id INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "value" TEXT,
    value_type TEXT NOT NULL,
    FOREIGN KEY (price_id) REFERENCES price (id)
);
