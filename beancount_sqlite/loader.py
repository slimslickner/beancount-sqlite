"""Core Beancount → SQLite loader."""

from __future__ import annotations

import json
import logging
import sqlite3
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

from beancount import loader as bean_loader
from beancount.core import data

log = logging.getLogger(__name__)

# Deletion order: children before parents to satisfy FK constraints.
# account_category is self-referential, so FK checks are disabled during clear.
_CLEAR_ORDER = [
    '"custom"',
    '"query"',
    "event",
    "note",
    "document",
    "assertion",
    "price",
    "commodity",
    "posting",
    "transaction_link",
    "transaction_tag",
    "link",
    "tag",
    '"transaction"',
    "account_currency",
    "account",
    "account_category",
]


class _MetaEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and date objects from beancount metadata."""

    def default(self, o: object) -> object:
        if isinstance(o, Decimal):
            return str(o)
        import datetime

        if isinstance(o, datetime.date):
            return o.isoformat()
        return super().default(o)


def _meta_to_json(meta: dict[str, Any]) -> str:
    """Serialize beancount metadata to JSON, stripping parser-internal keys."""
    filtered = {k: v for k, v in meta.items() if k not in {"filename", "lineno"}}
    return json.dumps(filtered, cls=_MetaEncoder)


class BeanSQLiteLoader:
    """Loads a Beancount ledger into a SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._account_map: dict[str, int] = {}
        self._category_map: dict[str, int] = {}

    def load(self, bean_file: Path) -> None:
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

        log.info("Loading into %s", self.db_path)
        conn = sqlite3.connect(self.db_path)
        self._conn = conn
        try:
            self._init_schema()
            self._clear_tables()
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
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            self._conn = None
        log.info("Done.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        assert self._conn is not None
        schema = (files("beancount_sqlite") / "schema.sql").read_text()
        self._conn.executescript(schema)

    def _clear_tables(self) -> None:
        assert self._conn is not None
        self._conn.execute("PRAGMA foreign_keys = OFF")
        for table in _CLEAR_ORDER:
            self._conn.execute(f"DELETE FROM {table}")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._account_map = {}
        self._category_map = {}

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
                    " (name, account_type, account_category_id, open_date, meta)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        entry.account,
                        account_type,
                        cat_id,
                        entry.date.isoformat(),
                        _meta_to_json(entry.meta),
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

            elif isinstance(entry, data.Close):
                self._conn.execute(
                    "UPDATE account SET close_date = ? WHERE name = ?",
                    (entry.date.isoformat(), entry.account),
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

                self._conn.execute(
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
            self._conn.execute(
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

    def _import_prices(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Price):
                continue
            self._conn.execute(
                "INSERT INTO price (date, currency, amount_number, amount_currency)"
                " VALUES (?, ?, ?, ?)",
                (
                    entry.date.isoformat(),
                    entry.currency,
                    str(entry.amount.number),
                    entry.amount.currency,
                ),
            )

    def _import_commodities(self, entries: list[Any]) -> None:
        assert self._conn is not None
        for entry in entries:
            if not isinstance(entry, data.Commodity):
                continue
            decimal_places = int(entry.meta.get("decimal_places", 0))
            self._conn.execute(
                "INSERT OR IGNORE INTO commodity"
                " (date, currency, decimal_places, meta)"
                " VALUES (?, ?, ?, ?)",
                (
                    entry.date.isoformat(),
                    entry.currency,
                    decimal_places,
                    _meta_to_json(entry.meta),
                ),
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
            self._conn.execute(
                "INSERT INTO document (date, account_id, filename) VALUES (?, ?, ?)",
                (entry.date.isoformat(), account_id, filename),
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
            self._conn.execute(
                "INSERT INTO note (date, account_id, comment) VALUES (?, ?, ?)",
                (entry.date.isoformat(), account_id, entry.comment),
            )

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
