"""
transform.py

Takes the raw list of dicts from raw_teams and raw_games and turns
them into clean, flat records ready to load into Postgres cleaned
tables.

Keeping validation separate from cleaning (is_valid_* vs clean_*)
means each function is easy to test and the rejection reasons are
transparent — nothing gets silently dropped.
"""

import json

from db import get_connection
from logging_setup import get_logger

logger = get_logger(__name__)


def is_valid_team(team: dict) -> tuple:
    """
    A team is valid only if it has a non-empty conference AND a
    non-empty division.

    The balldontlie API returns 45 teams. 30 current NBA teams have
    real conference/division values (e.g. "East" / "Southeast").
    The remaining 15 are defunct 1940s BAA-era franchises with
    whitespace-only or empty strings for both fields. We reject
    those here so downstream analysis only sees active NBA teams.
    """
    full_name = team.get("full_name", "?")
    conference = (team.get("conference") or "").strip()
    division = (team.get("division") or "").strip()

    if not conference or not division:
        return (
            False,
            f"Rejected {full_name}: no conference/division "
            f"(likely defunct franchise)",
        )

    return True, ""


def clean_teams(raw_rows: list[dict]) -> list[dict]:
    """
    Validate every team row through is_valid_team, keep only the
    survivors, flatten into clean column names, and log the tally.
    """
    kept = []
    rejected = 0

    for team in raw_rows:
        valid, reason = is_valid_team(team)
        if not valid:
            logger.info(reason)
            rejected += 1
            continue

        kept.append({
            "team_id": team["id"],
            "city": team.get("city", ""),
            "name": team["name"],
            "full_name": team["full_name"],
            "abbreviation": team.get("abbreviation", ""),
            "conference": team["conference"].strip(),
            "division": team["division"].strip(),
        })

    logger.info(
        f"clean_teams: {len(kept)} valid, {rejected} rejected "
        f"(out of {len(raw_rows)} raw)"
    )
    return kept


def is_valid_game(game: dict) -> tuple:
    """
    A game is valid only if all of the following hold:

    1. status == "Final"
       Pre-season, in-progress, or postponed-to-be-scheduled games
       should not appear in the cleaned set because their scores
       are either absent or temporary.

    2. postponed is False
       Explicit postponed flag from the API. (Some games have
       status="Final" but were later marked postponed — we check
       the boolean to catch those.)

    3. home_team_score and visitor_team_score are both present,
       non-null, non-negative integers.

    4. home_team_score and visitor_team_score are NOT both zero.
       A "0-0 final" means the game never actually started, not
       that the teams scored nothing. These are data artifacts
       and should be flagged rather than silently included.

    5. home_team.id and visitor_team.id both exist and are
       different from each other (self-play would be meaningless
       for analysis).
    """
    game_id = game.get("id", "?")

    # Check 1: status
    status = game.get("status")
    if status != "Final":
        return False, f"Game {game_id}: status is '{status}', not 'Final'"

    # Check 2: postponed flag
    postponed = game.get("postponed", False)
    if postponed is True:
        return False, f"Game {game_id}: marked as postponed"

    # Check 3: both scores present, non-null, non-negative
    home_score = game.get("home_team_score")
    visitor_score = game.get("visitor_team_score")

    if home_score is None or visitor_score is None:
        return (
            False,
            f"Game {game_id}: missing score "
            f"(home={home_score}, visitor={visitor_score})",
        )

    if not isinstance(home_score, int) or not isinstance(visitor_score, int):
        return (
            False,
            f"Game {game_id}: non-integer score "
            f"(home={home_score!r}, visitor={visitor_score!r})",
        )

    if home_score < 0 or visitor_score < 0:
        return (
            False,
            f"Game {game_id}: negative score "
            f"(home={home_score}, visitor={visitor_score})",
        )

    # Check 4: both scores zero
    if home_score == 0 and visitor_score == 0:
        logger.warning(
            f"Game {game_id}: both scores are 0 — "
            f"game likely never started, rejecting"
        )
        return False, f"Game {game_id}: both scores are 0 (never started)"

    # Check 5: team ids exist and differ
    home_team = game.get("home_team") or {}
    visitor_team = game.get("visitor_team") or {}
    home_team_id = home_team.get("id")
    visitor_team_id = visitor_team.get("id")

    if home_team_id is None or visitor_team_id is None:
        return (
            False,
            f"Game {game_id}: missing team id "
            f"(home_team_id={home_team_id}, "
            f"visitor_team_id={visitor_team_id})",
        )

    if home_team_id == visitor_team_id:
        return (
            False,
            f"Game {game_id}: home_team_id equals visitor_team_id "
            f"({home_team_id})",
        )

    return True, ""


def clean_games(raw_rows: list[dict]) -> list[dict]:
    """
    Validate every game row through is_valid_game, reject invalid,
    drop exact duplicate game_id values, and flatten the survivors
    into clean column names.
    """
    seen_ids = set()
    cleaned = []
    rejected_counts = {}
    duplicate_count = 0

    for game in raw_rows:
        valid, reason = is_valid_game(game)
        if not valid:
            rejected_counts[reason] = rejected_counts.get(reason, 0) + 1
            continue

        record = {
            "game_id": game["id"],
            "date": game.get("date", ""),
            "season": game.get("season"),
            "postseason": game.get("postseason", False),
            "home_team_id": game["home_team"]["id"],
            "visitor_team_id": game["visitor_team"]["id"],
            "home_team_score": game["home_team_score"],
            "visitor_team_score": game["visitor_team_score"],
            "home_win": 1 if game["home_team_score"] > game["visitor_team_score"] else 0,
        }

        # Duplicate check: same game_id should only appear once
        if record["game_id"] in seen_ids:
            duplicate_count += 1
            continue
        seen_ids.add(record["game_id"])

        cleaned.append(record)

    logger.info(
        f"clean_games: {len(cleaned)} valid, {duplicate_count} duplicates "
        f"rejected, {sum(rejected_counts.values())} invalid "
        f"(out of {len(raw_rows)} raw)"
    )
    for reason, count in sorted(rejected_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  rejected {count}: {reason}")
    if duplicate_count:
        logger.info(f"  rejected {duplicate_count} duplicate game_id(s)")

    return cleaned


if __name__ == "__main__":
    conn = get_connection()

    try:
        # --- Pull raw_teams ---
        # Snowflake VARIANT returns JSON strings, so we json.loads()
        # each row to get Python dicts for the validation functions.
        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_teams;")
            raw_team_rows = [json.loads(row[0]) for row in cur.fetchall()]
        logger.info(f"Loaded {len(raw_team_rows)} raw team rows from DB")

        # --- Pull raw_games ---
        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_games;")
            raw_game_rows = [json.loads(row[0]) for row in cur.fetchall()]
        logger.info(f"Loaded {len(raw_game_rows)} raw game rows from DB")

        # --- Transform ---
        clean_teams_result = clean_teams(raw_team_rows)
        clean_games_result = clean_games(raw_game_rows)

        # --- Summary ---
        team_rejected = len(raw_team_rows) - len(clean_teams_result)
        game_rejected = len(raw_game_rows) - len(clean_games_result)

        print("\n=== Transform Summary ===\n")
        print(f"Teams:  {len(clean_teams_result)} kept, "
              f"{team_rejected} rejected (out of {len(raw_team_rows)})")
        print(f"Games:  {len(clean_games_result)} kept, "
              f"{game_rejected} rejected (out of {len(raw_game_rows)})")
        print()

    finally:
        conn.close()
