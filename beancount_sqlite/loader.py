"""Core Beancount → SQLite loader."""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from beancount import loader as bean_loader
from beancount.core import amount as bean_amount
from beancount.core import data

log = logging.getLogger(__name__)

# Keys always stripped from metadata before storing.
_META_SKIP = frozenset({"filename", "lineno"})

# Default descriptions for built-in views, seeded into schema_description.
_BUILTIN_DESCRIPTIONS: list[tuple[str, str, str]] = [
    ("view", "v_accounts", "Accounts with `label` and `group` from open_metadata."),
    (
        "view",
        "v_commodities",
        "Commodities with common metadata keys pivoted as columns: `name`, `asset_class`, `asset_subclass`, `quote`.",
    ),
    ("view", "v_tags", "Tags with `label` and `group`."),
    ("view", "v_transactions", "Transactions with comma-separated `tags` and `links`."),
    ("view", "v_events", "Life events (job changes, moves, etc.)."),
    ("view", "v_queries", "Named BQL queries defined in the ledger."),
    ("view", "v_custom", "Custom directives (Fava config, plugin settings, etc.)."),
    (
        "view",
        "v_postings",
        "All postings joined with account and transaction context. "
        "Includes `account_label` and `account_group` from `v_accounts`.",
    ),
    (
        "view",
        "v_prices",
        "Price entries with commodity display name from `v_commodities`.",
    ),
    ("view", "v_assertions", "Balance assertions with account name, label, and group."),
    ("view", "v_documents", "Document directives with account name, label, and group."),
    ("view", "v_notes", "Note directives with account name, label, and group."),
    (
        "view",
        "v_spending",
        "Expense postings (`account_type = 'Expenses'`). "
        "Filtered subset of `v_postings`.",
    ),
    (
        "view",
        "v_income",
        "Income postings (`account_type = 'Income'`). "
        "Filtered subset of `v_postings`. "
        "Note: `amount_number` is typically negative — use `ABS()` for magnitudes.",
    ),
]


def _encode_meta_value(value: Any) -> tuple[str | None, str] | None:
    """Encode a beancount metadata value as (string_repr, value_type).

    Returns None if the value type is not supported and should be skipped.
    value_type matches the beancount grammar token types:
      str, bool, date, decimal, amount, null
    """
    if value is None:
        return (None, "null")
    if isinstance(value, bool):
        return ("true" if value else "false", "bool")
    if isinstance(value, str):
        return (value, "str")
    if isinstance(value, Decimal):
        return (str(value), "decimal")
    if isinstance(value, datetime.date):
        return (value.isoformat(), "date")
    if isinstance(value, bean_amount.Amount):
        return (f"{value.number} {value.currency}", "amount")
    return None


class BeanSQLiteLoader:
    """Loads a Beancount ledger into a SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._account_map: dict[str, int] = {}
        self._category_map: dict[str, int] = {}

    def load(
        self,
        bean_file: Path,
        post_sql_files: list[Path] | None = None,
        tags_yaml: Path | None = None,
    ) -> None:
        """Parse *bean_file* and write all directives into the SQLite database."""
        log.info("Parsing %s", bean_file)
        entries, errors, _ = bean_loader.load_file(str(bean_file))
        if errors:
            for err in errors:
                src = err.source or {}
                log.error(
                    "%s:%s: %s",
                    src.get("filename", "?"),
                    src.get("lineno", "?"),
                    err.message,
                )
            raise SystemExit(1)

        # Write to a temp file; rename atomically on success so a failed
        # load never leaves the existing database in a partial state.
        tmp_path = self.db_path.with_suffix(".db.tmp")
        log.info("Loading into %s", self.db_path)
        conn = sqlite3.connect(tmp_path)
        self._conn = conn
        success = False
        try:
            self._init_schema()
            self._import_accounts(entries)
            self._import_transactions(entries)
            self._import_balances(entries)
            self._import_prices(entries)
            self._import_commodities(entries)
            self._import_documents(entries, bean_file.parent)
            self._import_notes(entries)
            self._import_events(entries)
            self._import_queries(entries)
            self._import_customs(entries)
            if tags_yaml is not None:
                self._import_tags_yaml(tags_yaml)
            self._init_views()
            self._seed_schema_descriptions()
            conn.commit()
            for sql_file in post_sql_files or []:
                self._exec_post_sql(sql_file)
            success = True
        finally:
            conn.close()
            self._conn = None
            if not success:
                tmp_path.unlink(missing_ok=True)
        tmp_path.rename(self.db_path)
        self._write_schema_doc()
        log.info("Done.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        assert self._conn is not None
        schema = (files("beancount_sqlite") / "schema.sql").read_text()
        self._conn.executescript(schema)

    def _init_views(self) -> None:
        assert self._conn is not None
        views = (files("beancount_sqlite") / "views.sql").read_text()
        self._conn.executescript(views)

    def _seed_schema_descriptions(self) -> None:
        assert self._conn is not None
        self._conn.executemany(
            "INSERT OR IGNORE INTO schema_description"
            " (object_type, name, description) VALUES (?, ?, ?)",
            _BUILTIN_DESCRIPTIONS,
        )

    def _exec_post_sql(self, sql_file: Path) -> None:
        """Execute a user-provided SQL file in its own transaction."""
        assert self._conn is not None
        log.info("Running post-sql: %s", sql_file)
        sql = sql_file.read_text()
        try:
            self._conn.executescript(sql)
        except Exception:
            log.error("post-sql failed: %s", sql_file)
            raise

    def _write_schema_doc(self) -> None:
        """Write a schema summary markdown file alongside the database.

        Output: ``{db_stem}.schema.md`` in the same directory as the database.
        Suitable for embedding in an LLM system prompt.
        """
        doc_path = self.db_path.with_suffix(".schema.md")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            lines: list[str] = [
                "# beancount-sqlite schema",
                "",
                f"Database: `{self.db_path.name}`",
                "",
                "Query using the **views** below — they expose clean, named columns "
                "without requiring knowledge of the underlying joins.",
                "",
                "**Conventions:**",
                "- Dates: `TEXT` in ISO 8601 format (`YYYY-MM-DD`)",
                "- Amounts: `TEXT` — cast for arithmetic: `CAST(amount_number AS REAL)`",
                "- Tags/links: `TEXT` as comma-separated string, e.g. `'vacation,2024'`",
                "",
            ]

            desc_rows = conn.execute(
                "SELECT object_type, name, description FROM schema_description"
            ).fetchall()
            descriptions: dict[tuple[str, str], str] = {
                (row["object_type"], row["name"]): row["description"]
                for row in desc_rows
            }

            views = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name"
            ).fetchall()

            if views:
                lines += ["## Views", ""]
                for row in views:
                    name = row["name"]
                    desc = descriptions.get(("view", name), "")
                    lines.append(f"### `{name}`")
                    if desc:
                        lines += [desc, ""]
                    cols = conn.execute(
                        f'PRAGMA table_info("{name}")'  # noqa: S608
                    ).fetchall()
                    lines += ["| column | type |", "|---|---|"]
                    for col in cols:
                        col_type = col["type"] or "TEXT"
                        lines.append(f"| `{col['name']}` | {col_type} |")
                    lines.append("")

            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()

            if tables:
                lines += ["## Tables", ""]
                for row in tables:
                    name = row["name"]
                    lines.append(f"### `{name}`")
                    lines.append("")
                    cols = conn.execute(
                        f'PRAGMA table_info("{name}")'  # noqa: S608
                    ).fetchall()
                    lines += ["| column | type | not null |", "|---|---|---|"]
                    for col in cols:
                        col_type = col["type"] or "TEXT"
                        nn = "yes" if col["notnull"] else ""
                        lines.append(f"| `{col['name']}` | {col_type} | {nn} |")
                    lines.append("")
        finally:
            conn.close()

        doc_path.write_text("\n".join(lines))
        log.info("Schema doc written to %s", doc_path)

    def _import_tags_yaml(self, tags_yaml: Path) -> None:
        """Populate tag label/group from a tags YAML file.

        Expected format:
          tags:
            tag-name:
              description: "Human-readable label"
              group: "optional group"
        """
        assert self._conn is not None
        log.info("Loading tags from %s", tags_yaml)
        raw = yaml.safe_load(tags_yaml.read_text())
        tags = raw.get("tags") if isinstance(raw, dict) else None
        if not tags:
            log.warning("No 'tags' key found in %s — skipping", tags_yaml)
            return
        for name, attrs in tags.items():
            if not isinstance(attrs, dict):
                continue
            label = attrs.get("description")
            group = attrs.get("group")
            self._conn.execute(
                'INSERT INTO tag (name, label, "group") VALUES (?, ?, ?)'
                " ON CONFLICT (name) DO UPDATE SET"
                "   label = excluded.label,"
                '   "group" = excluded."group"',
                (name, label, group),
            )

    def _ensure_category(self, account_type: str, categories: list[str]) -> int:
        """Return the leaf category ID, creating any missing hierarchy nodes."""
        assert self._conn is not None
        parent_id: int | None = None
        for name in categories:
            key = f"{account_type}:{name}:{parent_id}"
            if key in self._category_map:
                parent_id = self._category_map[key]
                continue
            self._conn.execute(
                "INSERT OR IGNORE INTO account_category (name, parent_id, account_type)"
                " VALUES (?, ?, ?)",
                (name, parent_id, account_type),
            )
            row = self._conn.execute(
                "SELECT id FROM account_category"
                " WHERE name = ? AND parent_id IS ? AND account_type = ?",
                (name, parent_id, account_type),
            ).fetchone()
            assert row is not None, f"Failed to find/insert category {name!r}"
            self._category_map[key] = row[0]
            parent_id = row[0]
        assert parent_id is not None
        return parent_id

    def _insert_meta(
        self,
        table: str,
        fk_col: str,
        fk_id: int,
        meta: dict[str, Any],
        skip_keys: frozenset[str] = frozenset(),
    ) -> None:
        """Insert normalized metadata rows for one directive."""
        assert self._conn is not None
        rows = []
        for key, value in meta.items():
            if key in _META_SKIP or key.startswith("__") or key in skip_keys:
                continue
            encoded = _encode_meta_value(value)
            if encoded is None:
                log.debug(
                    "Skipping metadata key %r: unsupported type %s",
                    key,
                    type(value).__name__,
                )
                continue
            value_str, value_type = encoded
            rows.append((fk_id, key, value_str, value_type))
        if rows:
            self._conn.executemany(
                f'INSERT INTO {table} ({fk_col}, "key", "value", value_type)'  # noqa: S608
                " VALUES (?, ?, ?, ?)",
                rows,
            )

    # ------------------------------------------------------------------
    # Directive importers
    # ------------------------------------------------------------------

    def _import_accounts(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if isinstance(entry, data.Open):
                parts = entry.account.split(":")
                account_type = parts[0]
                categories = parts[1:]
                cat_id = self._ensure_category(account_type, categories)
                cur = self._conn.execute(
                    "INSERT INTO account"
                    " (name, account_type, account_category_id, open_date)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        entry.account,
                        account_type,
                        cat_id,
                        entry.date.isoformat(),
                    ),
                )
                assert cur.lastrowid is not None
                account_id = cur.lastrowid
                self._account_map[entry.account] = account_id
                if entry.currencies:
                    for currency in entry.currencies:
                        self._conn.execute(
                            "INSERT OR IGNORE INTO account_currency"
                            " (account_id, currency) VALUES (?, ?)",
                            (account_id, currency),
                        )
                self._insert_meta("open_metadata", "account_id", account_id, entry.meta)

            elif isinstance(entry, data.Close):
                self._conn.execute(
                    "UPDATE account SET close_date = ? WHERE name = ?",
                    (entry.date.isoformat(), entry.account),
                )
                account_id = self._account_map.get(entry.account)
                if account_id is not None:
                    self._insert_meta(
                        "close_metadata", "account_id", account_id, entry.meta
                    )

    def _import_transactions(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Transaction):
                continue

            cur = self._conn.execute(
                'INSERT INTO "transaction" (date, flag, payee, narration)'
                " VALUES (?, ?, ?, ?)",
                (
                    entry.date.isoformat(),
                    entry.flag,
                    entry.payee or "",
                    entry.narration,
                ),
            )
            assert cur.lastrowid is not None
            txn_id = cur.lastrowid
            self._insert_meta(
                "transaction_metadata", "transaction_id", txn_id, entry.meta
            )

            for tag in entry.tags:
                self._conn.execute(
                    "INSERT OR IGNORE INTO tag (name) VALUES (?)", (tag,)
                )
                row = self._conn.execute(
                    "SELECT id FROM tag WHERE name = ?", (tag,)
                ).fetchone()
                assert row is not None
                self._conn.execute(
                    "INSERT OR IGNORE INTO transaction_tag"
                    " (transaction_id, tag_id) VALUES (?, ?)",
                    (txn_id, row[0]),
                )

            for link in entry.links:
                self._conn.execute(
                    "INSERT OR IGNORE INTO link (name) VALUES (?)", (link,)
                )
                row = self._conn.execute(
                    "SELECT id FROM link WHERE name = ?", (link,)
                ).fetchone()
                assert row is not None
                self._conn.execute(
                    "INSERT OR IGNORE INTO transaction_link"
                    " (transaction_id, link_id) VALUES (?, ?)",
                    (txn_id, row[0]),
                )

            for posting in entry.postings:
                account_id = self._account_map.get(posting.account)
                if account_id is None:
                    log.warning(
                        "Unknown account %r in transaction on %s — skipping posting",
                        posting.account,
                        entry.date,
                    )
                    continue

                units = posting.units
                price = posting.price
                cost = posting.cost

                pcur = self._conn.execute(
                    "INSERT INTO posting ("
                    " date, account_id, transaction_id, flag,"
                    " amount_number, amount_currency,"
                    " price_number, price_currency,"
                    " cost_number, cost_currency, cost_date, cost_label"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.date.isoformat(),
                        account_id,
                        txn_id,
                        posting.flag,
                        str(units.number),
                        units.currency,
                        str(price.number) if price is not None else None,
                        price.currency if price is not None else None,
                        str(cost.number)
                        if cost is not None and cost.number is not None
                        else None,
                        cost.currency if cost is not None else None,
                        cost.date.isoformat()
                        if cost is not None and cost.date is not None
                        else None,
                        cost.label if cost is not None else None,
                    ),
                )
                assert pcur.lastrowid is not None
                self._insert_meta(
                    "posting_metadata", "posting_id", pcur.lastrowid, posting.meta
                )

    def _import_balances(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Balance):
                continue
            account_id = self._account_map.get(entry.account)
            if account_id is None:
                log.warning(
                    "Unknown account %r in balance on %s — skipping",
                    entry.account,
                    entry.date,
                )
                continue
            acur = self._conn.execute(
                "INSERT INTO assertion"
                " (date, account_id, amount_number, amount_currency)"
                " VALUES (?, ?, ?, ?)",
                (
                    entry.date.isoformat(),
                    account_id,
                    str(entry.amount.number),
                    entry.amount.currency,
                ),
            )
            assert acur.lastrowid is not None
            self._insert_meta(
                "balance_metadata", "assertion_id", acur.lastrowid, entry.meta
            )

    def _import_prices(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Price):
                continue
            pricecur = self._conn.execute(
                "INSERT INTO price (date, currency, amount_number, amount_currency)"
                " VALUES (?, ?, ?, ?)",
                (
                    entry.date.isoformat(),
                    entry.currency,
                    str(entry.amount.number),
                    entry.amount.currency,
                ),
            )
            assert pricecur.lastrowid is not None
            self._insert_meta(
                "price_metadata", "price_id", pricecur.lastrowid, entry.meta
            )

    def _import_commodities(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Commodity):
                continue
            decimal_places = int(entry.meta.get("decimal_places", 0))
            commcur = self._conn.execute(
                "INSERT OR IGNORE INTO commodity"
                " (date, currency, decimal_places)"
                " VALUES (?, ?, ?)",
                (
                    entry.date.isoformat(),
                    entry.currency,
                    decimal_places,
                ),
            )
            if commcur.lastrowid:
                self._insert_meta(
                    "commodity_metadata",
                    "commodity_id",
                    commcur.lastrowid,
                    entry.meta,
                    skip_keys=frozenset({"decimal_places"}),
                )

    def _import_documents(self, entries: list[Any], base_path: Path) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Document):
                continue
            account_id = self._account_map.get(entry.account)
            if account_id is None:
                log.warning(
                    "Unknown account %r in document on %s — skipping",
                    entry.account,
                    entry.date,
                )
                continue
            try:
                filename = str(Path(entry.filename).relative_to(base_path))
            except ValueError:
                filename = entry.filename
            doccur = self._conn.execute(
                "INSERT INTO document (date, account_id, filename) VALUES (?, ?, ?)",
                (entry.date.isoformat(), account_id, filename),
            )
            assert doccur.lastrowid is not None
            self._insert_meta(
                "document_metadata", "document_id", doccur.lastrowid, entry.meta
            )

    def _import_notes(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Note):
                continue
            account_id = self._account_map.get(entry.account)
            if account_id is None:
                log.warning(
                    "Unknown account %r in note on %s — skipping",
                    entry.account,
                    entry.date,
                )
                continue
            notecur = self._conn.execute(
                "INSERT INTO note (date, account_id, comment) VALUES (?, ?, ?)",
                (entry.date.isoformat(), account_id, entry.comment),
            )
            assert notecur.lastrowid is not None
            self._insert_meta("note_metadata", "note_id", notecur.lastrowid, entry.meta)

    def _import_events(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Event):
                continue
            self._conn.execute(
                "INSERT INTO event (date, type, description) VALUES (?, ?, ?)",
                (entry.date.isoformat(), entry.type, entry.description),
            )

    def _import_queries(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Query):
                continue
            self._conn.execute(
                'INSERT INTO "query" (date, name, query_string) VALUES (?, ?, ?)',
                (entry.date.isoformat(), entry.name, entry.query_string),
            )

    def _import_customs(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Custom):
                continue
            self._conn.execute(
                'INSERT INTO "custom" (date, type, values) VALUES (?, ?, ?)',
                (
                    entry.date.isoformat(),
                    entry.type,
                    json.dumps(
                        [
                            str(v.value) if hasattr(v, "value") else str(v)
                            for v in entry.values
                        ]
                    ),
                ),
            )
