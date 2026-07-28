"""
load_raw.py

Reads the raw JSON files produced by extract.py and loads every row
into Postgres raw-layer tables (raw_teams, raw_games) as JSONB.

This is a destructive-reload pattern: every run TRUNCATEs both tables
before inserting, because raw tables always reflect the latest full
extract. Mixing stale rows from a previous run with fresh rows would
break the guarantee that "raw is whatever the API returned last time
we extracted."
"""

import json
import os

from psycopg2.extras import execute_values

from config import TEAMS_RAW_PATH, GAMES_RAW_PATH
from db import get_connection, init_raw_tables, DatabaseError
from extract import load_raw_json_from_disk
from logging_setup import get_logger

logger = get_logger(__name__)


def _check_files_exist() -> None:
    """
    Verify both raw JSON files exist before attempting to load.

    Failing early with a clear message (rather than crashing with a
    FileNotFoundError deep in a loop) makes it obvious that the user
    needs to run extract.py first.
    """
    missing = []
    if not os.path.exists(TEAMS_RAW_PATH):
        missing.append(TEAMS_RAW_PATH)
    if not os.path.exists(GAMES_RAW_PATH):
        missing.append(GAMES_RAW_PATH)

    if missing:
        paths = "\n  ".join(str(p) for p in missing)
        logger.error(
            f"Cannot load raw data — the following file(s) do not exist:\n"
            f"  {paths}\n"
            f"Run extract.py first to fetch and cache the API responses."
        )
        raise FileNotFoundError(
            f"Missing raw data files. Run extract.py first.\n"
            f"  {paths}"
        )


def _truncate_tables(conn) -> None:
    """TRUNCATE both raw tables before inserting fresh data."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE raw_teams, raw_games;")
    conn.commit()
    logger.info("Truncated raw_teams and raw_games")


def _load_table(conn, table_name: str, records: list, file_path: str) -> int:
    """
    Bulk-insert a list of dicts into a raw table.

    Each dict is stored as one JSONB row. Uses ``execute_values`` for
    efficiency — same pattern as Assignment 5's ``upsert_cleaned_rows``.
    """
    if not records:
        logger.warning(f"{table_name}: zero rows to insert.")
        return 0

    rows = [(json.dumps(rec),) for rec in records]

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name};")
        count_before = cur.fetchone()[0]

        execute_values(
            cur,
            f"INSERT INTO {table_name} (raw_data) VALUES %s",
            rows,
        )

        cur.execute(f"SELECT COUNT(*) FROM {table_name};")
        count_after = cur.fetchone()[0]

    conn.commit()
    inserted = count_after - count_before
    logger.info(
        f"Loaded {inserted} row(s) into {table_name} "
        f"from {file_path}"
    )
    return inserted


def load_raw() -> dict:
    """
    Main entry point for the raw load step.

    Flow:
      1. Verify JSON files exist (fail early with a helpful message).
      2. Connect to Postgres and ensure raw tables exist.
      3. TRUNCATE both tables (destructive-reload pattern).
      4. Read JSON files from disk and bulk-insert into Postgres.
      5. Return a summary dict with row counts.
    """
    _check_files_exist()

    try:
        conn = get_connection()
    except DatabaseError:
        logger.error("Raw load aborted — could not connect to database.")
        raise

    try:
        init_raw_tables(conn)
        _truncate_tables(conn)

        teams_data = load_raw_json_from_disk(TEAMS_RAW_PATH)
        games_data = load_raw_json_from_disk(GAMES_RAW_PATH)

        teams_count = _load_table(conn, "raw_teams", teams_data, TEAMS_RAW_PATH)
        games_count = _load_table(conn, "raw_games", games_data, GAMES_RAW_PATH)

        summary = {"raw_teams": teams_count, "raw_games": games_count}
        logger.info(
            f"Raw load complete — "
            f"{teams_count} teams, {games_count} games."
        )
        return summary

    finally:
        conn.close()
        logger.info("Database connection closed.")


if __name__ == "__main__":
    result = load_raw()
    print(
        f"Loaded {result['raw_teams']} teams into raw_teams, "
        f"{result['raw_games']} games into raw_games."
    )
