"""CLI entry point for beancount-sqlite."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from beancount_sqlite.loader import BeanSQLiteLoader


def resolve_db_path(explicit: Path | None) -> Path:
    """Resolve the SQLite database path.

    Precedence (lowest → highest):
      1. ``ledger.db`` in the current working directory (default)
      2. ``BEANCOUNT_DB`` environment variable
      3. Explicit CLI argument
    """
    if explicit is not None:
        return explicit
    env = os.environ.get("BEANCOUNT_DB")
    if env:
        return Path(env)
    return Path("ledger.db")


def _cmd_load(args: argparse.Namespace) -> None:
    db_path = resolve_db_path(args.db_file)
    loader = BeanSQLiteLoader(db_path)
    loader.load(args.beancount_file)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="beancount-sqlite",
        description="Load a Beancount ledger into a SQLite database.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    load_parser = subparsers.add_parser(
        "load",
        help="Parse a Beancount file and write it to SQLite.",
    )
    load_parser.add_argument(
        "beancount_file",
        type=Path,
        help="Path to the .bean ledger file.",
    )
    load_parser.add_argument(
        "db_file",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Path for the output .db file. "
            "Defaults to BEANCOUNT_DB env var, then ledger.db in the current directory."
        ),
    )
    load_parser.set_defaults(func=_cmd_load)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    args.func(args)


if __name__ == "__main__":
    main()
