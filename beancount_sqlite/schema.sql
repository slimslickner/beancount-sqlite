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
    meta TEXT NOT NULL DEFAULT '{}',
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
    decimal_places INTEGER NOT NULL DEFAULT 0,
    meta TEXT NOT NULL DEFAULT '{}'
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
