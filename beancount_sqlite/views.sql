-- SQL views for beancount-sqlite analytics layer.
-- These are the intended query surface — prefer views over raw tables.
-- Each view flattens joins and metadata so callers get clean, named columns.
--
-- Rebuild strategy: DROP + CREATE so this script is idempotent.

DROP VIEW IF EXISTS v_spending;
DROP VIEW IF EXISTS v_income;
DROP VIEW IF EXISTS v_postings;
DROP VIEW IF EXISTS v_transactions;
DROP VIEW IF EXISTS v_accounts;

-- v_accounts: accounts with label/group from open_metadata.
CREATE VIEW v_accounts AS
SELECT
    a.id,
    a.name,
    a.account_type,
    om_label."value" AS label,
    om_group."value" AS "group",
    a.open_date,
    a.close_date
FROM account AS a
LEFT JOIN open_metadata AS om_label
    ON
        a.id = om_label.account_id
        AND om_label."key" = 'label'
LEFT JOIN open_metadata AS om_group
    ON
        a.id = om_group.account_id
        AND om_group."key" = 'group';

-- v_transactions: transactions with comma-separated tags and links.
CREATE VIEW v_transactions AS
SELECT
    t.id,
    t."date",
    t.flag,
    t.payee,
    t.narration,
    (
        SELECT GROUP_CONCAT(tg.name, ',')
        FROM transaction_tag AS tt
        INNER JOIN tag AS tg ON tt.tag_id = tg.id
        WHERE tt.transaction_id = t.id
    ) AS tags,
    (
        SELECT GROUP_CONCAT(lk.name, ',')
        FROM transaction_link AS tl
        INNER JOIN link AS lk ON tl.link_id = lk.id
        WHERE tl.transaction_id = t.id
    ) AS links
FROM "transaction" AS t;

-- v_postings: all postings with account and transaction context.
-- posting_id, date, flag, payee, narration, account, account_type,
-- account_label, account_group, amount_number, amount_currency, tags
CREATE VIEW v_postings AS
SELECT
    p.id AS posting_id,
    t."date",
    t.flag,
    t.payee,
    t.narration,
    a.name AS account,
    a.account_type,
    om_label."value" AS account_label,
    om_group."value" AS account_group,
    p.amount_number,
    p.amount_currency,
    (
        SELECT GROUP_CONCAT(tg.name, ',')
        FROM transaction_tag AS tt
        INNER JOIN tag AS tg ON tt.tag_id = tg.id
        WHERE tt.transaction_id = t.id
    ) AS tags
FROM posting AS p
INNER JOIN "transaction" AS t ON p.transaction_id = t.id
INNER JOIN account AS a ON p.account_id = a.id
LEFT JOIN open_metadata AS om_label
    ON
        a.id = om_label.account_id
        AND om_label."key" = 'label'
LEFT JOIN open_metadata AS om_group
    ON
        a.id = om_group.account_id
        AND om_group."key" = 'group';

-- v_spending: expense postings. Filtered subset of v_postings.
CREATE VIEW v_spending AS
SELECT
    posting_id,
    "date",
    flag,
    payee,
    narration,
    account,
    account_type,
    account_label,
    account_group,
    amount_number,
    amount_currency,
    tags
FROM v_postings
WHERE account_type = 'Expenses';

-- v_income: income postings. Filtered subset of v_postings.
-- Note: income postings typically carry a negative amount_number.
-- Use ABS(amount_number) for magnitudes.
CREATE VIEW v_income AS
SELECT
    posting_id,
    "date",
    flag,
    payee,
    narration,
    account,
    account_type,
    account_label,
    account_group,
    amount_number,
    amount_currency,
    tags
FROM v_postings
WHERE account_type = 'Income';
