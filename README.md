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
beancount-sqlite = { git = "https://github.com/<you>/beancount-sqlite" }
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

The database file defaults to `ledger.db` in the current directory. Override with `--db-file` or the `BEANCOUNT_DB` environment variable.

```bash
uv run python -m beancount_sqlite.cli load main.bean
uv run python -m beancount_sqlite.cli load main.bean ~/finance/ledger.db
uv run python -m beancount_sqlite.cli -v load main.bean   # verbose logging
```

Loading aborts if `bean-check` reports errors — the database is only updated when the ledger is valid.

## Schema

All Beancount directives are stored:

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

Metadata for every directive type is stored in normalized key/value tables (`open_metadata`, `posting_metadata`, `transaction_metadata`, etc.) with a `value_type` column encoding the original grammar token type (`str`, `bool`, `date`, `decimal`, `amount`, `null`).

Dates are stored as `TEXT` in ISO 8601 format. Numeric amounts are stored as `TEXT` to preserve Decimal precision.

## Development

```bash
uv sync
uv run python -m beancount_sqlite.cli load example.beancount
uv run ruff check && uv run ruff format
uv run ty check
uv run sqlfluff lint beancount_sqlite/schema.sql
```
