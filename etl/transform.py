"""
etl/transform.py

Validation and flattening logic for raw teams and games.
is_valid_* / clean_* pairs keep validation transparent and testable.
"""

import json

from database.db import get_connection
from etl.logging_setup import get_logger

logger = get_logger(__name__)


def is_valid_team(team: dict) -> tuple:
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
    game_id = game.get("id", "?")

    status = game.get("status")
    if status != "Final":
        return False, f"Game {game_id}: status is '{status}', not 'Final'"

    postponed = game.get("postponed", False)
    if postponed is True:
        return False, f"Game {game_id}: marked as postponed"

    home_score = game.get("home_team_score")
    visitor_score = game.get("visitor_team_score")
    if home_score is None or visitor_score is None:
        return (False, f"Game {game_id}: missing score "
                       f"(home={home_score}, visitor={visitor_score})")
    if not isinstance(home_score, int) or not isinstance(visitor_score, int):
        return (False, f"Game {game_id}: non-integer score "
                       f"(home={home_score!r}, visitor={visitor_score!r})")
    if home_score < 0 or visitor_score < 0:
        return (False, f"Game {game_id}: negative score "
                       f"(home={home_score}, visitor={visitor_score})")
    if home_score == 0 and visitor_score == 0:
        logger.warning(f"Game {game_id}: both scores are 0 — rejecting")
        return False, f"Game {game_id}: both scores are 0 (never started)"

    home_team = game.get("home_team") or {}
    visitor_team = game.get("visitor_team") or {}
    home_team_id = home_team.get("id")
    visitor_team_id = visitor_team.get("id")
    if home_team_id is None or visitor_team_id is None:
        return (False, f"Game {game_id}: missing team id "
                       f"(home_team_id={home_team_id}, "
                       f"visitor_team_id={visitor_team_id})")
    if home_team_id == visitor_team_id:
        return (False, f"Game {game_id}: home_team_id equals visitor_team_id "
                       f"({home_team_id})")

    return True, ""


def clean_games(raw_rows: list[dict]) -> list[dict]:
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
        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_teams;")
            raw_team_rows = [json.loads(row[0]) for row in cur.fetchall()]
        with conn.cursor() as cur:
            cur.execute("SELECT raw_data FROM raw_games;")
            raw_game_rows = [json.loads(row[0]) for row in cur.fetchall()]
        logger.info(f"Loaded {len(raw_team_rows)} raw teams, {len(raw_game_rows)} raw games")

        clean_teams_result = clean_teams(raw_team_rows)
        clean_games_result = clean_games(raw_game_rows)

        team_rejected = len(raw_team_rows) - len(clean_teams_result)
        game_rejected = len(raw_game_rows) - len(clean_games_result)

        print("\n=== Transform Summary ===\n")
        print(f"Teams:  {len(clean_teams_result)} kept, {team_rejected} rejected")
        print(f"Games:  {len(clean_games_result)} kept, {game_rejected} rejected\n")
    finally:
        conn.close()
