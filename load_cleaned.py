"""
load_cleaned.py

Reads raw JSONB from the raw-layer tables, runs transform.py's
cleaning logic, and loads the results into the cleaned-layer tables
(cleaned_teams, cleaned_games).

Two different load strategies are used:

  Teams (full refresh via upsert)
    There are only 30 active NBA teams and they change rarely.
    We do INSERT ... ON CONFLICT DO UPDATE so re-running picks up
    any metadata changes (e.g. a team changes its name) and never
    errors on duplicate team_id.

  Games (incremental via season filter + ON CONFLICT DO NOTHING)
    Games accumulate across seasons. We check MAX(season) already
    in the cleaned table, then only process games with season >=
    that value. The ON CONFLICT DO NOTHING is a safety net for any
    individual game that slipped through the filter (e.g. because
    it was already loaded). This matches the Assignment 5 pattern.
"""

import sys

from psycopg2.extras import execute_values

from db import (
    get_connection,
    init_cleaned_tables,
    DatabaseError,
)
from logging_setup import get_logger
from transform import clean_teams, clean_games

logger = get_logger(__name__)


def get_latest_loaded_season(conn):
    """
    Check the highest season already present in cleaned_games.

    Returns None if the table is empty (first run ever), which tells
    the caller to load everything.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(season) FROM cleaned_games;")
        result = cur.fetchone()
        return result[0] if result else None


def load_cleaned_teams(conn, teams: list[dict]) -> int:
    """
    Upsert all cleaned teams into cleaned_teams.

    Because teams are few and mostly static, we always send the full
    cleaned set. ON CONFLICT DO UPDATE handles the cases where a team
    already exists (update its metadata) or is new (insert it).

    Returns the count of rows inserted (not updated).
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

        execute_values(
            cur,
            """
            INSERT INTO cleaned_teams
                (team_id, city, name, full_name, abbreviation,
                 conference, division)
            VALUES %s
            ON CONFLICT (team_id) DO UPDATE SET
                city         = EXCLUDED.city,
                name         = EXCLUDED.name,
                full_name    = EXCLUDED.full_name,
                abbreviation = EXCLUDED.abbreviation,
                conference   = EXCLUDED.conference,
                division     = EXCLUDED.division
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
    Incrementally load cleaned games into cleaned_games.

    Step 1 — Query MAX(season) already in the table.
    Step 2 — Filter incoming games to only those with season >=
             that max. This skips fully-loaded older seasons but
             re-processes the current max season in case the API
             added new games to it since the last extract.
    Step 3 — execute_values with ON CONFLICT (game_id) DO NOTHING
             as a final safety net against any individual duplicate.
    Step 4 — Count the table before and after (don't trust
             cur.rowcount from execute_values — it only reflects
             the last batch).

    Returns the count of rows actually inserted.
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

    rows = [
        (
            g["game_id"],
            g["date"],
            g["season"],
            g["postseason"],
            g["home_team_id"],
            g["visitor_team_id"],
            g["home_team_score"],
            g["visitor_team_score"],
            g["home_win"],
        )
        for g in games
    ]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM cleaned_games;")
        count_before = cur.fetchone()[0]

        execute_values(
            cur,
            """
            INSERT INTO cleaned_games
                (game_id, date, season, postseason,
                 home_team_id, visitor_team_id,
                 home_team_score, visitor_team_score, home_win)
            VALUES %s
            ON CONFLICT (game_id) DO NOTHING
            """,
            rows,
        )

        cur.execute("SELECT COUNT(*) FROM cleaned_games;")
        count_after = cur.fetchone()[0]

    conn.commit()
    inserted = count_after - count_before
    skipped = len(rows) - inserted
    logger.info(
        f"Games load complete: {inserted} new, "
        f"{skipped} already existed (skipped)"
    )
    return inserted


if __name__ == "__main__":
    # --- CONNECT & ENSURE SCHEMA ---
    try:
        conn = get_connection()
    except DatabaseError:
        logger.error("Load aborted — could not connect to database.")
        sys.exit(1)

    try:
        init_cleaned_tables(conn)

        # --- PULL RAW DATA ---
        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_teams;")
            raw_team_rows = [row[0] for row in cur.fetchall()]

        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_games;")
            raw_game_rows = [row[0] for row in cur.fetchall()]

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
