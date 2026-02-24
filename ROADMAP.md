# Roadmap

Enhancements to convert this from a SQL-file generator into a robust, installable Beancount → SQLite loader with full directive and metadata coverage.

The whole process should not execute if bean-check fails on the ledger — specifically because balances should be inherently true at all times. The assumption is that if data is being loaded to SQLite, then assertions are not needed.

## Purpose

This package is a **read-only analytics layer**: Beancount is the source of truth, and this loader mirrors ledger data into a queryable SQLite database. The interface is standard SQL — not BQL (Beancount's built-in query language). Standard SQL is universal, fully expressive (CTEs, window functions, aggregations), and supported by any SQL-capable tool. BQL is purpose-built for Beancount's own query interface and lacks the expressiveness needed for general analytics.

The phases build in layers: correct infrastructure first, then richer data coverage, then a simplified query surface. The end result is a database that accurately reflects the full ledger and is easy to query without deep knowledge of Beancount internals.

## Phase 1: Core Infrastructure Rewrite

Replace the current SQL-file-generation approach with direct SQLite writing using the `sqlite3` stdlib module.

- [x] Convert to a `uv` project: add `pyproject.toml`, remove `requirements.txt`, run `uv sync`
- [x] Write directly to a `.db` file instead of generating a `.sql` text file
- [x] Use parameterized queries throughout (eliminate string interpolation)
- [x] Replace positional ID generation (`eid + 1`, `(eid+1)*1000+pid+1`) with proper `AUTOINCREMENT`
- [x] Remove debug `print()` statements; add structured `logging`
- [x] Upgrade from beancount v2 (`beancount==2.3.6`) to beancount v3
- [x] Add `date` column to the `transaction` table (currently only exists on `posting`)
- [x] Drop binary blob storage from `document` table — store relative file path only

**CLI target:**
```
beancount-sqlite load main.bean ledger.db
```

## Phase 2: Schema Enhancements — Missing Directives

Add tables for all Beancount directives not currently handled.

- [x] `note` — account notes and annotations
- [x] `event` — named life events (e.g. job changes, moves)
- [x] `query` — named BQL queries defined in the ledger
- [x] `custom` — catch-all for custom directives (Fava sidebar links, plugin config, etc.)

Each table follows the same pattern: `id`, `date`, foreign key to relevant entity, and directive-specific fields.

## Phase 3: Metadata Layer

Add queryable key/value metadata tables for all directive types. Currently, metadata is either lost entirely (transactions, postings) or stored as a non-queryable JSON blob (accounts, commodities).

Metadata carries critical analytical context that can't be recovered from the core directive fields alone — things like the originating institution, importer source, transfer counterparty, and commodity classification. Storing it as a JSON blob means it can't be filtered, joined, or aggregated in SQL. Normalized key/value tables make every metadata field a first-class queryable column.

**New tables:**

```sql
-- Per-directive metadata (key/value, fully queryable)
transaction_metadata (id, transaction_id, key, value, value_type)
posting_metadata     (id, posting_id,     key, value, value_type)
open_metadata        (id, account_id,     key, value, value_type)
close_metadata       (id, account_id,     key, value, value_type)
commodity_metadata   (id, commodity_id,   key, value, value_type)
balance_metadata     (id, assertion_id,   key, value, value_type)
note_metadata        (id, note_id,        key, value, value_type)
document_metadata    (id, document_id,    key, value, value_type)
price_metadata       (id, price_id,       key, value, value_type)
```

**`value_type` column** encodes the original beancount grammar token type:

| value_type | Beancount grammar | Example stored value         |
|------------|-------------------|------------------------------|
| `str`      | STRING, account, currency, TAG | `"Whole Foods"`   |
| `bool`     | BOOL              | `"true"`                     |
| `date`     | DATE              | `"2024-01-15"`               |
| `decimal`  | number_expr       | `"123.45"`                   |
| `amount`   | amount            | `"123.45 USD"`               |
| `null`     | NONE / empty      | `null`                       |

Remove the existing JSON `meta` blobs from `account` and `commodity` in favor of these normalized tables.

**Examples of metadata this captures from a real ledger:**
- `posting_metadata`: `matched_transfer_account`, `match_id`, `source_payee`, `narration`
- `transaction_metadata`: `source`, `importer`, `cleared_date`
- `open_metadata`: `institution`, `account_number`, `display_name`
- `commodity_metadata`: `name`, `asset-class`, `asset-subclass`, `quote`

## Phase 4: Packaging & Installation

Make the package installable as a proper Python package with a CLI entry point.

- [x] Add `pyproject.toml` with package metadata, dependencies, and build config
- [x] Expose `beancount-sqlite` CLI entry point
- [x] Support installation as a path dependency from other projects:
  ```toml
  # In ../beancount/pyproject.toml
  beancount-sqlite = { path = "../beancount-sqlite" }
  ```
- [x] Add description, readme, and license to `pyproject.toml`; rewrite `README.md`
- [ ] Publish to PyPI for general Beancount community use (deferred — local/GitHub installs sufficient for now)

## Phase 5: Analytical Views

Add SQL views that form the primary **query surface** for the database. The normalized schema requires multi-table joins to answer most useful questions; these views pre-encode those joins so callers can write simple queries against named, domain-meaningful tables rather than the raw schema.

Each view encodes domain vocabulary — `v_spending` is self-explanatory in a way that `SELECT p.* FROM posting p JOIN account a ON p.account_id = a.id WHERE a.account_type = 'Expenses'` is not. This makes the database usable from any SQL-capable tool without requiring knowledge of the full schema.

Views are the intended query surface — never query raw tables directly. Each view flattens joins and metadata into clean, named columns for use by SQL tools and LLMs.

- [x] `v_accounts` — accounts with `label` / `group` from `open_metadata`
- [x] `v_transactions` — transactions with comma-separated `tags` and `links`
- [x] `v_postings` — all postings with account and transaction context
- [x] `v_spending` — filtered subset of `v_postings` where `account_type = 'Expenses'`
- [x] `v_income` — filtered subset of `v_postings` where `account_type = 'Income'`

**Semantic layer** — accounts and tags carry human-readable labels and groups:

- [x] Account `label` and `group`: set via `open_metadata` keys in the `.bean` file; exposed as `account_label` / `account_group` in all posting views
- [x] Tag `label` and `group`: populated via `--tags-yaml <file>` using the same YAML format as `check_valid_tags.py` (keys: `description` → label, `group`)

**User-extensible SQL** — `--post-sql <file>` (repeatable) runs additional SQL files after the main load commits, enabling custom views, indexes, or derived tables without modifying this package.

## Phase 6: LLM Schema Documentation

Auto-generate a schema summary from the live `.db` file, suitable for embedding in an LLM system prompt. Output is `{db}.schema.md`, written automatically on every `load`.

- [x] Auto-generate a schema summary (views + tables, column names and types) from the live `.db` file
- [x] Output as Markdown alongside the `.db` file (`ledger.db` → `ledger.schema.md`)
- [x] View descriptions stored in `schema_description` table — seeded with built-in defaults, overridable via `--post-sql`; custom views can add their own descriptions the same way

## Non-Goals

- Validation (balance checks, lot tracking, inventory assertions) — beancount itself handles this
- Importing/writing back to `.bean` files — read-only analytics layer only
- Storing document binary data — file paths are sufficient
- Query interface or AI tooling — this package provides the data layer only; downstream tools consume the SQL views
