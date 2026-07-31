"""
models/features.py

Builds a no-leakage feature-engineered dataset for predicting home_win.
Features for a given game use ONLY information from games before that date.

Day 6: implemented rolling win-rate features for both home and visitor teams.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collections import defaultdict

import pandas as pd

from database.db import get_connection
from etl.logging_setup import get_logger

logger = get_logger(__name__)

FEATURE_COLUMNS = [
    "game_id", "season", "postseason",
    "home_season_win_rate_so_far", "home_last_5_win_rate",
    "visitor_season_win_rate_so_far", "visitor_last_5_win_rate",
    "home_win",
]


def _season_win_rate(history: list, season: int) -> float:
    season_games = [r for r in history if r[1] == season]
    if not season_games:
        return 0.5
    return sum(r[0] for r in season_games) / len(season_games)


def _last_n_win_rate(history: list, n: int = 5) -> float:
    window = history[-n:]
    if not window:
        return 0.5
    return sum(r[0] for r in window) / len(window)


def build_features() -> pd.DataFrame:
    conn = get_connection()
    try:
        logger.info("Loading cleaned_games sorted by date...")
        games = pd.read_sql(
            "SELECT * FROM cleaned_games ORDER BY date ASC;", conn
        )
        games.columns = [c.lower() for c in games.columns]
    finally:
        conn.close()

    logger.info(f"Loaded {len(games)} games.")
    team_history: dict[int, list] = defaultdict(list)
    rows = []
    default_count = 0

    for _, game in games.iterrows():
        home_id = int(game["home_team_id"])
        visitor_id = int(game["visitor_team_id"])
        season = int(game["season"])

        home_season = _season_win_rate(team_history[home_id], season)
        home_last_5 = _last_n_win_rate(team_history[home_id])
        if not team_history[home_id]:
            default_count += 1

        visitor_season = _season_win_rate(team_history[visitor_id], season)
        visitor_last_5 = _last_n_win_rate(team_history[visitor_id])
        if not team_history[visitor_id]:
            default_count += 1

        postseason = int(game["postseason"])
        rows.append({
            "game_id": int(game["game_id"]),
            "season": season,
            "postseason": postseason,
            "home_season_win_rate_so_far": home_season,
            "home_last_5_win_rate": home_last_5,
            "visitor_season_win_rate_so_far": visitor_season,
            "visitor_last_5_win_rate": visitor_last_5,
            "home_win": int(game["home_win"]),
        })

        team_history[home_id].append((int(game["home_win"]), season))
        team_history[visitor_id].append((1 - int(game["home_win"]), season))

    logger.info(f"Rows where at least one team had no prior data (used 0.5 default): {default_count}")
    df = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    logger.info(f"Feature DataFrame shape: {df.shape}")
    return df


def main():
    df = build_features()
    print("\nFirst 10 rows:")
    print("=" * 70)
    print(df.head(10).to_string(index=False))
    print("\nSummary statistics:")
    print("=" * 70)
    feature_cols = ["home_season_win_rate_so_far", "home_last_5_win_rate",
                    "visitor_season_win_rate_so_far", "visitor_last_5_win_rate"]
    print(df[feature_cols].describe().to_string())
    print(f"\nhome_win distribution:\n{df['home_win'].value_counts().to_string()}")


if __name__ == "__main__":
    main()
