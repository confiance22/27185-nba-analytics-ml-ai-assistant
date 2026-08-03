"""
test_transform.py

Tests for etl/transform.py validation logic — no database needed.

Run:  pytest tests/test_transform.py -v

Day 11: added validation tests for team and game cleaning logic.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from etl.transform import is_valid_team, clean_teams, is_valid_game, clean_games


def test_valid_team_passes():
    team = {
        "id": 1, "conference": "East", "division": "Southeast",
        "city": "Atlanta", "name": "Hawks", "full_name": "Atlanta Hawks",
        "abbreviation": "ATL",
    }
    valid, reason = is_valid_team(team)
    assert valid is True
    assert reason == ""


def test_defunct_team_rejected():
    team = {
        "id": 28, "conference": "", "division": "  ",
        "city": "Chicago", "name": "Stags", "full_name": "Chicago Stags",
        "abbreviation": "CHS",
    }
    valid, reason = is_valid_team(team)
    assert valid is False
    assert "defunct" in reason.lower() or "conference" in reason.lower()


VALID_GAME = {
    "id": 473409, "date": "2021-10-19", "season": 2021,
    "status": "Final", "postponed": False,
    "home_team_score": 114, "visitor_team_score": 121,
    "home_team": {"id": 14, "full_name": "Los Angeles Lakers"},
    "visitor_team": {"id": 10, "full_name": "Golden State Warriors"},
}


def test_valid_game_passes():
    valid, reason = is_valid_game(VALID_GAME)
    assert valid is True
    assert reason == ""


def test_game_not_final_rejected():
    game = dict(VALID_GAME, status="In Progress")
    valid, reason = is_valid_game(game)
    assert valid is False
    assert "not 'Final'" in reason


def test_postponed_game_rejected():
    game = dict(VALID_GAME, postponed=True)
    valid, reason = is_valid_game(game)
    assert valid is False
    assert "postponed" in reason.lower()


def test_missing_score_rejected():
    game = dict(VALID_GAME, home_team_score=None)
    valid, reason = is_valid_game(game)
    assert valid is False
    assert "missing" in reason.lower()


def test_both_scores_zero_rejected():
    game = dict(VALID_GAME, home_team_score=0, visitor_team_score=0)
    valid, reason = is_valid_game(game)
    assert valid is False
    assert "0" in reason and "never started" in reason


def test_same_team_rejected():
    game = dict(VALID_GAME)
    game["home_team"] = {"id": 14}
    game["visitor_team"] = {"id": 14}
    valid, reason = is_valid_game(game)
    assert valid is False
    assert "same" in reason.lower() or "equal" in reason.lower()


def test_clean_teams_counts():
    raw = [
        {"id": 1, "conference": "East", "division": "Atlantic",
         "city": "Boston", "name": "Celtics", "full_name": "Boston Celtics", "abbreviation": "BOS"},
        {"id": 2, "conference": "", "division": "",
         "city": "Chicago", "name": "Stags", "full_name": "Chicago Stags", "abbreviation": "CHS"},
        {"id": 3, "conference": "West", "division": "Pacific",
         "city": "Los Angeles", "name": "Lakers", "full_name": "Los Angeles Lakers", "abbreviation": "LAL"},
        {"id": 4, "conference": "West", "division": "Southwest",
         "city": "Houston", "name": "Rockets", "full_name": "Houston Rockets", "abbreviation": "HOU"},
        {"id": 5, "conference": "  ", "division": None,
         "city": "Detroit", "name": "Falcons", "full_name": "Detroit Falcons", "abbreviation": "DFC"},
    ]
    result = clean_teams(raw)
    assert len(result) == 3


def test_clean_games_deduplicates():
    raw = [
        dict(VALID_GAME),
        dict(VALID_GAME, id=473410, home_team_score=99, visitor_team_score=88),
        dict(VALID_GAME, id=473409),
    ]
    result = clean_games(raw)
    assert len(result) == 2
    assert [g["game_id"] for g in result] == [473409, 473410]
