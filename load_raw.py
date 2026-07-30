"""
load_raw.py

Reads the raw JSON files produced by extract.py and loads every row
into Snowflake raw-layer tables (raw_teams, raw_games) as VARIANT.

Snowflake differences from Postgres:
  - executemany() + PARSE_JSON(%s) instead of psycopg2's execute_values.
    PARSE_JSON converts a JSON string into a VARIANT value.
  - TRUNCATE TABLE syntax is the same.

This is a destructive-reload pattern: every run TRUNCATEs both tables
before inserting, because raw tables always reflect the latest full
extract.
"""

import json
import os

from config import TEAMS_RAW_PATH, GAMES_RAW_PATH
from db import get_connection, init_raw_tables, DatabaseError
from extract import load_raw_json_from_disk
from logging_setup import get_logger

logger = get_logger(__name__)


def _check_files_exist() -> None:
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
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE raw_teams;")
        cur.execute("TRUNCATE TABLE raw_games;")
    conn.commit()
    logger.info("Truncated raw_teams and raw_games")


def _load_table(conn, table_name: str, records: list, file_path: str) -> int:
    if not records:
        logger.warning(f"{table_name}: zero rows to insert.")
        return 0

    BATCH_SIZE = 500

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name};")
        count_before = cur.fetchone()[0]

        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            selects = " UNION ALL ".join(
                f"SELECT PARSE_JSON('{json.dumps(r).replace("'", "''")}')"
                for r in batch
            )
            cur.execute(
                f"INSERT INTO {table_name} (raw_data) {selects}"
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
