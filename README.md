# beancount-sqlite

A read-only analytics layer that loads [Beancount](https://beancount.github.io/) ledger data into a queryable SQLite database.

Beancount is the source of truth. This tool mirrors ledger data into SQLite so you can query it with standard SQL — CTEs, window functions, aggregations — from any SQL-capable tool or LLM.

Forked from [beanpost](https://github.com/gerdemb/beanpost).

## Installation

**From a local path** (add to your project's `pyproject.toml`):

```toml
[tool.uv.sources]
beancount-sqlite = { path = "../beancount-sqlite" }
```

**From GitHub:**

```toml
[tool.uv.sources]
beancount-sqlite = { git = "https://github.com/slimslickner/beancount-sqlite" }
```

Then add to your dependencies:

```toml
[project]
dependencies = ["beancount-sqlite"]
```

## Usage

```
beancount-sqlite load <beancount_file> [db_file]
```

The database file defaults to `ledger.db` in the current directory. Override with a positional argument or the `BEANCOUNT_DB` environment variable.

```bash
uv run beancount-sqlite load main.bean
uv run beancount-sqlite load main.bean ~/finance/ledger.db
uv run beancount-sqlite -v load main.bean          # verbose logging
uv run beancount-sqlite load main.bean --tags-yaml tags.yaml
uv run beancount-sqlite load main.bean --post-sql custom.sql
```

Loading aborts if `bean-check` reports errors — the database is only written when the ledger is valid. Each load writes to a temp file and renames it atomically, so a failed load never corrupts the existing database.

A schema summary is written to `{db}.schema.md` on every load (e.g. `ledger.schema.md`). This file is suitable for embedding in an LLM system prompt.

### Flags

| Flag | Description |
|---|---|
| `--tags-yaml FILE` | Populate tag `label` and `group` from a YAML file (same format as [`check_valid_tags`](https://github.com/slimslickner/beancount-plugins/blob/main/beancount_plugins/check_valid_tags.py) plugin) |
| `--post-sql FILE` | Run a SQL file after the main load. Use for custom views, indexes, or `schema_description`s. |

## Query surface

Query using the **views** — they flatten joins and metadata into clean, named columns. Don't query raw tables directly. Additional views can be defined using the `--post-sql` flag.

| View | Description |
|---|---|
| `v_accounts` | Accounts with `label` and `group` from `open_metadata` |
| `v_transactions` | Transactions with comma-separated `tags` and `links` |
| `v_postings` | All postings with account and transaction context |
| `v_spending` | Expense postings — filtered subset of `v_postings` |
| `v_income` | Income postings — filtered subset of `v_postings` |

**Conventions:**
- Amounts are stored as `TEXT` — cast for arithmetic: `CAST(amount_number AS REAL)`
- Dates are `TEXT` in ISO 8601 format
- Tags and links are `TEXT` comma-separated strings

## Semantic layer

Account labels and groups are set directly in the `.bean` file via metadata on `open` directives (the [`check_valid_metadata`](https://github.com/slimslickner/beancount-plugins/blob/main/beancount_plugins/check_valid_metadata.py) plugin can help control this):

```beancount
2020-01-01 open Assets:Checking:Primary USD
  label: "Primary Checking used for Bill Pay and Direct Deposit"
  group: "Cash"

2020-01-01 open Expenses:Groceries USD
  label: "Groceries"
  group: "Living Expenses"
```

These appear as `account_label` and `account_group` in all posting views.

Tag labels and groups come from a YAML file passed via `--tags-yaml`:

```yaml
tags:
  vacation-2024:
    description: "Summer 2024 vacation to Hawaii"
    group: "Vacations"
```

## Extending the schema

Use `--post-sql` to add custom views, indexes, or derived tables without modifying this package:

```bash
beancount-sqlite load main.bean --post-sql my_views.sql
```

To document a custom view in the schema summary, insert into `schema_description`:

```sql
INSERT INTO schema_description (object_type, name, description)
VALUES ('view', 'v_my_view', 'My custom view description');
```

## Raw schema

All Beancount directives are stored in normalized tables:

| Table | Source |
|---|---|
| `account`, `account_category`, `account_currency` | Open / Close |
| `transaction`, `posting`, `tag`, `link` | Transaction |
| `assertion` | Balance |
| `price` | Price |
| `commodity` | Commodity |
| `document` | Document |
| `note` | Note |
| `event` | Event |
| `query` | Query |
| `custom` | Custom |

Metadata for every directive type is stored in normalized key/value tables (`open_metadata`, `posting_metadata`, `transaction_metadata`, etc.) with a `value_type` column encoding the original grammar type (`str`, `bool`, `date`, `decimal`, `amount`, `null`).

## Development

```bash
uv sync
uv run beancount-sqlite load example.beancount
uv run ruff check && uv run ruff format
uv run ty check
uv run sqlfluff lint beancount_sqlite/schema.sql beancount_sqlite/views.sql
```
