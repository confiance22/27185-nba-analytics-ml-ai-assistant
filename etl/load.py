"""
etl/load.py

Load raw JSON → Snowflake raw tables (VARIANT), then transform →
Snowflake cleaned tables. Handles both the raw-load and cleaned-load
steps that load_raw.py and load_cleaned.py previously did separately.
"""

import json
import os
import sys

from config.settings import TEAMS_RAW_PATH, GAMES_RAW_PATH
from database.db import (
    get_connection,
    init_raw_tables,
    init_cleaned_tables,
    DatabaseError,
)
from etl.extract import load_raw_json_from_disk
from etl.transform import clean_teams, clean_games
from etl.logging_setup import get_logger

logger = get_logger(__name__)


# =========================== Raw load ===========================

def _check_files_exist() -> None:
    missing = []
    if not os.path.exists(TEAMS_RAW_PATH):
        missing.append(TEAMS_RAW_PATH)
    if not os.path.exists(GAMES_RAW_PATH):
        missing.append(GAMES_RAW_PATH)
    if missing:
        paths = "\n  ".join(str(p) for p in missing)
        logger.error(f"Cannot load raw data — missing file(s):\n  {paths}")
        raise FileNotFoundError(f"Missing raw data files. Run extract first.\n  {paths}")


def _truncate_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE raw_teams;")
        cur.execute("TRUNCATE TABLE raw_games;")
    conn.commit()
    logger.info("Truncated raw_teams and raw_games")


def _load_raw_table(conn, table_name: str, records: list, file_path: str) -> int:
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
            cur.execute(f"INSERT INTO {table_name} (raw_data) {selects}")

        cur.execute(f"SELECT COUNT(*) FROM {table_name};")
        count_after = cur.fetchone()[0]

    conn.commit()
    inserted = count_after - count_before
    logger.info(f"Loaded {inserted} row(s) into {table_name} from {file_path}")
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

        teams_count = _load_raw_table(conn, "raw_teams", teams_data, TEAMS_RAW_PATH)
        games_count = _load_raw_table(conn, "raw_games", games_data, GAMES_RAW_PATH)

        summary = {"raw_teams": teams_count, "raw_games": games_count}
        logger.info(f"Raw load complete — {teams_count} teams, {games_count} games.")
        return summary
    finally:
        conn.close()
        logger.info("Database connection closed.")


# =========================== Cleaned load ===========================

def get_latest_loaded_season(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(season) FROM cleaned_games;")
        result = cur.fetchone()
        return result[0] if result else None


def load_cleaned_teams(conn, teams: list[dict]) -> int:
    if not teams:
        logger.info("No cleaned teams to load.")
        return 0

    rows = [(t["team_id"], t["city"], t["name"], t["full_name"],
             t["abbreviation"], t["conference"], t["division"]) for t in teams]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM cleaned_teams;")
        count_before = cur.fetchone()[0]
        cur.executemany("""
            MERGE INTO cleaned_teams AS target
            USING (SELECT %s AS team_id, %s AS city, %s AS name,
                          %s AS full_name, %s AS abbreviation,
                          %s AS conference, %s AS division) AS source
            ON target.team_id = source.team_id
            WHEN MATCHED THEN UPDATE SET
                city = source.city, name = source.name,
                full_name = source.full_name, abbreviation = source.abbreviation,
                conference = source.conference, division = source.division
            WHEN NOT MATCHED THEN INSERT
                (team_id, city, name, full_name, abbreviation, conference, division)
            VALUES (source.team_id, source.city, source.name,
                    source.full_name, source.abbreviation,
                    source.conference, source.division)
        """, rows)
        cur.execute("SELECT COUNT(*) FROM cleaned_teams;")
        count_after = cur.fetchone()[0]

    conn.commit()
    inserted = count_after - count_before
    skipped = len(teams) - inserted
    logger.info(f"Teams load complete: {inserted} new, {skipped} existing (upserted)")
    return inserted


def load_cleaned_games(conn, games: list[dict]) -> int:
    if not games:
        logger.info("No cleaned games to load.")
        return 0

    latest_season = get_latest_loaded_season(conn)
    if latest_season is not None:
        before_filter = len(games)
        games = [g for g in games if g["season"] >= latest_season]
        logger.info(f"Incremental: filtered {before_filter} -> {len(games)} rows (season >= {latest_season})")
    else:
        logger.info("No existing data — first load. Loading all valid seasons.")

    if not games:
        logger.info("No new games to insert.")
        return 0

    def _escape(val):
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "TRUE" if val else "FALSE"
        if isinstance(val, int):
            return str(val)
        return f"'{str(val).replace("'", "''")}'"

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
            cur.execute(f"""
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
            """)

        cur.execute("SELECT COUNT(*) FROM cleaned_games;")
        count_after = cur.fetchone()[0]

    conn.commit()
    inserted = count_after - count_before
    skipped = len(games) - inserted
    logger.info(f"Games load complete: {inserted} new, {skipped} skipped")
    return inserted


def load_cleaned() -> dict:
    try:
        conn = get_connection()
    except DatabaseError:
        logger.error("Clean load aborted — could not connect to database.")
        raise

    try:
        init_cleaned_tables(conn)

        # truncate for full reload
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE cleaned_games;")
        conn.commit()
        logger.info("Truncated cleaned_games for full reload")

        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_teams;")
            raw_team_rows = [json.loads(row[0]) for row in cur.fetchall()]
        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_games;")
            raw_game_rows = [json.loads(row[0]) for row in cur.fetchall()]
        logger.info(f"Loaded {len(raw_team_rows)} raw teams, {len(raw_game_rows)} raw games")

        clean_team_rows = clean_teams(raw_team_rows)
        clean_game_rows = clean_games(raw_game_rows)

        load_cleaned_teams(conn, clean_team_rows)
        load_cleaned_games(conn, clean_game_rows)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM cleaned_teams;")
            team_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM cleaned_games;")
            game_count = cur.fetchone()[0]

        print(f"\n=== Load Complete ===")
        print(f"  cleaned_teams:  {team_count} rows")
        print(f"  cleaned_games:  {game_count} rows\n")
        return {"cleaned_teams": team_count, "cleaned_games": game_count}
    finally:
        conn.close()
        logger.info("Database connection closed.")


if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "all"
    if action in ("raw", "all"):
        print(load_raw())
    if action in ("cleaned", "all"):
        print(load_cleaned())
