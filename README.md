# beancount-sqlite

An opinionated and plugin-ready read-only analytics layer that loads [Beancount](https://beancount.github.io/) ledger data into a queryable SQLite database.

Beancount is the source of truth. This tool mirrors ledger data into SQLite so you can query it with standard SQL — CTEs, window functions, aggregations — from any SQL-capable tool or LLM.

Forked from [beanpost](https://github.com/BarrySong97/beancount-sqlite).

## Installation

**From a local path:**

```toml
# pyproject.toml
[tool.uv.sources]
beancount-sqlite = { path = "../beancount-sqlite" }

[project]
dependencies = ["beancount-sqlite"]
```

**From GitHub:**

```toml
[tool.uv.sources]
beancount-sqlite = { git = "https://github.com/slimslickner/beancount-sqlite" }
```

## Usage

```bash
beancount-sqlite load <beancount_file> [db_file]
```

The database file defaults to `ledger.db` in the current directory, or the `BEANCOUNT_DB` environment variable.

```bash
beancount-sqlite load main.bean
beancount-sqlite load main.bean ~/finance/ledger.db
beancount-sqlite -v load main.bean                     # verbose logging
beancount-sqlite load main.bean \
  --tags-yaml tags.yaml \
  --post-sql custom_views.sql
```

| Flag | Description |
|---|---|
| `--tags-yaml FILE` | Populate tag `label` from a YAML file — same format as the [`check_valid_tags`](https://github.com/slimslickner/beancount-plugins/blob/main/beancount_plugins/check_valid_tags.py) plugin |
| `--post-sql FILE` | Run a SQL file after the main load; repeatable. Use for custom views, indexes, or `schema_description` entries. |

Loading aborts if `bean-check` reports errors. Each run writes to a temp file and renames atomically — a failed load never corrupts the existing database.

A schema summary (`ledger.schema.md`) is written alongside the database on every load, suitable for embedding in an LLM system prompt.

## Query surface

Query using the **views** — they flatten joins and metadata into clean, named columns. Don't query raw tables directly. Additional views can be defined via `--post-sql`.

| View | Description |
|---|---|
| `v_accounts` | Accounts with `label` |
| `v_transactions` | Transactions with comma-separated `tags` and `links` |
| `v_postings` | All postings with account and transaction context |
| `v_spending` | Expense postings — filtered subset of `v_postings` |
| `v_income` | Income postings — filtered subset of `v_postings` |

**Conventions:**
- Amounts: `TEXT` — cast for arithmetic: `CAST(amount_number AS REAL)`
- Dates: `TEXT` in ISO 8601 format (`YYYY-MM-DD`)
- Tags/links: comma-separated `TEXT` string

## Semantic layer

Accounts and tags carry human-readable labels, exposed as columns in the views.

**Accounts** — set metadata on `open` directives in your `.bean` file (the [`check_valid_metadata`](https://github.com/slimslickner/beancount-plugins/blob/main/beancount_plugins/check_valid_metadata.py) plugin can enforce these):

```beancount
2020-01-01 open Assets:Checking:Primary USD
  label: "Primary Checking"

2020-01-01 open Expenses:Groceries USD
  label: "Groceries"
```

These surface as `account_label` in all posting views.

**Tags** — provide a YAML file via `--tags-yaml` (same format as `check_valid_tags`). All keys under each tag name are stored as rows in `tag_metadata` and can be queried or pivoted freely:

```yaml
tags:
  vacation-2024:
    label: "Summer 2024 vacation"
    category: "Travel"
```

## Extending

Use `--post-sql` to add custom views or derived tables without modifying this package. To include a custom view in the auto-generated schema summary, add a row to `schema_description`:

```sql
-- custom_views.sql
CREATE VIEW v_monthly_spending AS
SELECT
    strftime('%Y-%m', "date") AS month,
    account_label,
    SUM(CAST(amount_number AS REAL)) AS total
FROM v_spending
GROUP BY 1, 2;

INSERT INTO schema_description (object_type, name, description)
VALUES ('view', 'v_monthly_spending', 'Monthly spending totals by account label.');
```

## Schema

All Beancount directives are stored in normalized tables. See the auto-generated `*.schema.md` for the full column reference.

| Tables | Source directive |
|---|---|
| `account`, `account_category`, `account_currency` | `open` / `close` |
| `transaction`, `posting`, `tag`, `link` | `txn` |
| `assertion` | `balance` |
| `price` | `price` |
| `commodity` | `commodity` |
| `document`, `note`, `event`, `query`, `custom` | remaining directives |
| `*_metadata` | per-directive key/value metadata |

Metadata value types: `str`, `bool`, `date`, `decimal`, `amount`, `null`.

## Development

```bash
uv sync
uv run beancount-sqlite load example.beancount
uv run ruff check && uv run ruff format
uv run ty check
uv run sqlfluff lint beancount_sqlite/schema.sql beancount_sqlite/views.sql
```
