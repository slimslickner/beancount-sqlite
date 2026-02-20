# Roadmap

Enhancements to convert this from a SQL-file generator into a robust, installable Beancount → SQLite loader with full directive and metadata coverage.

The whole process should not execute if bean-check fails on the ledger - specifically because balances should be inherently true at all times. The assumption is that if data is being loaded to SQLite, then assertions are not needed.

## Phase 1: Core Infrastructure Rewrite

Replace the current SQL-file-generation approach with direct SQLite writing using the `sqlite3` stdlib module.

- [ ] Convert to a `uv` project: add `pyproject.toml`, remove `requirements.txt`, run `uv sync`
- [ ] Write directly to a `.db` file instead of generating a `.sql` text file
- [ ] Use parameterized queries throughout (eliminate string interpolation)
- [ ] Replace positional ID generation (`eid + 1`, `(eid+1)*1000+pid+1`) with proper `AUTOINCREMENT`
- [ ] Remove debug `print()` statements; add structured `logging`
- [ ] Upgrade from beancount v2 (`beancount==2.3.6`) to beancount v3
- [ ] Add `date` column to the `transaction` table (currently only exists on `posting`)
- [ ] Drop binary blob storage from `document` table — store relative file path only

**CLI target:**
```
beancount-sqlite load main.bean ledger.db
```

## Phase 2: Schema Enhancements — Missing Directives

Add tables for all Beancount directives not currently handled.

- [ ] `note` — account notes and annotations
- [ ] `event` — named life events (e.g. job changes, moves)
- [ ] `query` — named BQL queries defined in the ledger
- [ ] `custom` — catch-all for custom directives (Fava sidebar links, plugin config, etc.)

Each table follows the same pattern: `id`, `date`, foreign key to relevant entity, and directive-specific fields.

## Phase 3: Metadata Layer

Add queryable key/value metadata tables for all directive types. Currently, metadata is either lost entirely (transactions, postings) or stored as a non-queryable JSON blob (accounts, commodities).

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

**`value_type` column** encodes the original Python type so values can be deserialized correctly:

| value_type | Python type       | Example stored value         |
|------------|-------------------|------------------------------|
| `str`      | `str`             | `"Whole Foods"`              |
| `int`      | `int`             | `"42"`                       |
| `decimal`  | `Decimal`         | `"123.45"`                   |
| `bool`     | `bool`            | `"true"`                     |
| `date`     | `datetime.date`   | `"2024-01-15"`               |
| `amount`   | `Amount`          | `"123.45 USD"`               |

Remove the existing JSON `meta` blobs from `account` and `commodity` in favor of these normalized tables.

**Examples of metadata this captures from a real ledger:**
- `posting_metadata`: `matched_transfer_account`, `match_id`, `source_payee`, `narration`
- `transaction_metadata`: `source`, `importer`, `cleared_date`
- `open_metadata`: `institution`, `account_number`, `display_name`
- `commodity_metadata`: `name`, `asset-class`, `asset-subclass`, `quote`

## Phase 4: Packaging & Installation

Make the package installable as a proper Python package with a CLI entry point.

- [ ] Add `pyproject.toml` with package metadata, dependencies, and build config
- [ ] Expose `beancount-sqlite` CLI entry point
- [ ] Support installation as a path dependency from other projects:
  ```toml
  # In ../beancount/pyproject.toml
  beancount-sqlite = { path = "../beancount-sqlite" }
  ```
- [ ] Publish to PyPI for general Beancount community use

## Phase 5: Analytical Views

Add SQL views for common analytical queries, making it easier for both humans and LLMs to query the data without writing complex joins.

- [ ] `v_transactions` — transactions with date, payee, narration, tags (comma-separated), account names
- [ ] `v_postings` — postings joined with account name, transaction date, payee, narration
- [ ] `v_spending` — expense postings with amount, account hierarchy, payee, date
- [ ] `v_income` — income postings, similar to spending
- [ ] `v_net_worth` — asset and liability balances by account
- [ ] `v_transfers` — postings with `matched_transfer_account` metadata (from metadata layer)
- [ ] `v_posting_metadata_pivot` — wide-format posting metadata for common keys

## Phase 6: LLM Schema Documentation

Generate schema documentation suitable for inclusion in an LLM system prompt.

- [ ] Auto-generate a schema summary (tables, columns, example values) from the live `.db` file
- [ ] Include view definitions and their purpose
- [ ] Output as Markdown or plain text for embedding in Ollama/Claude prompts
- [ ] Used by downstream LLM query tools (e.g. a CLI that answers natural language questions)

## Non-Goals

- Validation (balance checks, lot tracking, inventory assertions) — beancount itself handles this
- Importing/writing back to `.bean` files — read-only analytics layer only
- Storing document binary data — file paths are sufficient
