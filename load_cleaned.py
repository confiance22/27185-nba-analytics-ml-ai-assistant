"""
load_cleaned.py

Reads raw VARIANT from the raw-layer tables, runs transform.py's
cleaning logic, and loads the results into the cleaned-layer tables
(cleaned_teams, cleaned_games).

Snowflake differences from Postgres:
  - MERGE INTO instead of INSERT ... ON CONFLICT.
    Snowflake does not support ON CONFLICT. MERGE checks whether a
    row with the same key exists and either updates (teams) or skips
    (games) accordingly.
  - executemany() instead of psycopg2's execute_values.
  - Raw VARIANT data comes back as a JSON string from Snowflake
    (not auto-parsed like psycopg2's JSONB), so we json.loads() it.
"""

import json
import sys

from db import (
    get_connection,
    init_cleaned_tables,
    DatabaseError,
)
from logging_setup import get_logger
from transform import clean_teams, clean_games

logger = get_logger(__name__)


def get_latest_loaded_season(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(season) FROM cleaned_games;")
        result = cur.fetchone()
        return result[0] if result else None


def load_cleaned_teams(conn, teams: list[dict]) -> int:
    """
    Upsert all cleaned teams using MERGE INTO.
    Snowflake doesn't support ON CONFLICT, so we use MERGE:
      - WHEN MATCHED THEN UPDATE updates existing rows.
      - WHEN NOT MATCHED THEN INSERT adds new rows.
    """
    if not teams:
        logger.info("No cleaned teams to load.")
        return 0

    rows = [
        (
            t["team_id"],
            t["city"],
            t["name"],
            t["full_name"],
            t["abbreviation"],
            t["conference"],
            t["division"],
        )
        for t in teams
    ]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM cleaned_teams;")
        count_before = cur.fetchone()[0]

        cur.executemany(
            """
            MERGE INTO cleaned_teams AS target
            USING (SELECT %s AS team_id, %s AS city, %s AS name,
                          %s AS full_name, %s AS abbreviation,
                          %s AS conference, %s AS division) AS source
            ON target.team_id = source.team_id
            WHEN MATCHED THEN UPDATE SET
                city         = source.city,
                name         = source.name,
                full_name    = source.full_name,
                abbreviation = source.abbreviation,
                conference   = source.conference,
                division     = source.division
            WHEN NOT MATCHED THEN INSERT
                (team_id, city, name, full_name, abbreviation,
                 conference, division)
            VALUES (source.team_id, source.city, source.name,
                    source.full_name, source.abbreviation,
                    source.conference, source.division)
            """,
            rows,
        )

        cur.execute("SELECT COUNT(*) FROM cleaned_teams;")
        count_after = cur.fetchone()[0]

    conn.commit()
    inserted = count_after - count_before
    skipped = len(teams) - inserted
    logger.info(
        f"Teams load complete: {inserted} new, "
        f"{skipped} existing (upserted)"
    )
    return inserted


def load_cleaned_games(conn, games: list[dict]) -> int:
    """
    Incrementally load cleaned games using MERGE INTO with only
    WHEN NOT MATCHED (skip existing rows, no update needed).

    Uses a batched UNION ALL source so Snowflake processes many rows
    per statement, avoiding slow individual executemany calls.
    """
    if not games:
        logger.info("No cleaned games to load.")
        return 0

    latest_season = get_latest_loaded_season(conn)

    if latest_season is not None:
        before_filter = len(games)
        games = [g for g in games if g["season"] >= latest_season]
        logger.info(
            f"Incremental load: latest season already in DB is "
            f"{latest_season}. Filtered {before_filter} -> "
            f"{len(games)} rows (seasons >= {latest_season})."
        )
    else:
        logger.info(
            "No existing data found — this is the first load. "
            "Loading all valid seasons."
        )

    if not games:
        logger.info("No new games to insert after incremental filter.")
        return 0

    def _escape(val):
        """Format a Python value for inline SQL."""
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "TRUE" if val else "FALSE"
        if isinstance(val, int):
            return str(val)
        # string / date — escape single quotes
        s = str(val).replace("'", "''")
        return f"'{s}'"

    BATCH_SIZE = 500

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM cleaned_games;")
        count_before = cur.fetchone()[0]

        for i in range(0, len(games), BATCH_SIZE):
            batch = games[i:i + BATCH_SIZE]
            selects = " UNION ALL ".join(
                f"SELECT {_escape(g['game_id'])}, {_escape(g['date'])}, "
                f"{_escape(g['season'])}, {_escape(g['postseason'])}, "
                f"{_escape(g['home_team_id'])}, {_escape(g['visitor_team_id'])}, "
                f"{_escape(g['home_team_score'])}, {_escape(g['visitor_team_score'])}, "
                f"{_escape(g['home_win'])}"
                for g in batch
            )
            cur.execute(
                f"""
                MERGE INTO cleaned_games AS target
                USING ({selects}) AS source(
                    game_id, date, season, postseason,
                    home_team_id, visitor_team_id,
                    home_team_score, visitor_team_score, home_win
                )
                ON target.game_id = source.game_id
                WHEN NOT MATCHED THEN INSERT
                    (game_id, date, season, postseason,
                     home_team_id, visitor_team_id,
                     home_team_score, visitor_team_score, home_win)
                VALUES (source.game_id, source.date, source.season,
                        source.postseason, source.home_team_id,
                        source.visitor_team_id, source.home_team_score,
                        source.visitor_team_score, source.home_win)
                """
            )

        cur.execute("SELECT COUNT(*) FROM cleaned_games;")
        count_after = cur.fetchone()[0]

    conn.commit()
    inserted = count_after - count_before
    skipped = len(games) - inserted
    logger.info(
        f"Games load complete: {inserted} new, "
        f"{skipped} already existed (skipped)"
    )
    return inserted


if __name__ == "__main__":
    try:
        conn = get_connection()
    except DatabaseError:
        logger.error("Load aborted — could not connect to database.")
        sys.exit(1)

    try:
        init_cleaned_tables(conn)

        # Fresh start: truncate cleaned_games so the incremental
        # filter doesn't skip older seasons from a partial earlier load.
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE cleaned_games;")
        conn.commit()
        logger.info("Truncated cleaned_games for full reload")

        # --- PULL RAW DATA ---
        # Snowflake VARIANT columns return as JSON strings, so we
        # json.loads() each row to get Python dicts for the transformer.
        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_teams;")
            raw_team_rows = [json.loads(row[0]) for row in cur.fetchall()]

        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_games;")
            raw_game_rows = [json.loads(row[0]) for row in cur.fetchall()]

        logger.info(
            f"Loaded {len(raw_team_rows)} raw teams, "
            f"{len(raw_game_rows)} raw games from DB"
        )

        # --- TRANSFORM ---
        clean_team_rows = clean_teams(raw_team_rows)
        clean_game_rows = clean_games(raw_game_rows)

        # --- LOAD ---
        load_cleaned_teams(conn, clean_team_rows)
        load_cleaned_games(conn, clean_game_rows)

        # --- FINAL SUMMARY ---
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM cleaned_teams;")
            team_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM cleaned_games;")
            game_count = cur.fetchone()[0]

        print(f"\n=== Load Complete ===")
        print(f"  cleaned_teams:  {team_count} rows")
        print(f"  cleaned_games:  {game_count} rows\n")

    finally:
        conn.close()
        logger.info("Database connection closed.")
