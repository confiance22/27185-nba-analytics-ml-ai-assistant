"""
models/predict.py

Exports two CSV files for Tableau:
  1. games_full.csv — every game with team names/conferences/divisions
  2. predictions_vs_actual.csv — LR predictions on every historical game

Day 8: exported the full games dataset and LR predictions to CSV for
the Tableau dashboard.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import joblib
import pandas as pd

from database.db import get_connection
from models.features import build_features
from etl.logging_setup import get_logger

logger = get_logger(__name__)

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "tableau_data")
GAMES_FULL_PATH = os.path.join(OUT_DIR, "games_full.csv")
PREDICTIONS_PATH = os.path.join(OUT_DIR, "predictions_vs_actual.csv")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "saved_models")


def export():
    os.makedirs(OUT_DIR, exist_ok=True)

    conn = get_connection()
    try:
        logger.info("Loading cleaned_teams...")
        teams = pd.read_sql("SELECT * FROM cleaned_teams;", conn)
        teams.columns = [c.lower() for c in teams.columns]

        logger.info("Loading cleaned_games with joined team names...")
        games = pd.read_sql("""
            SELECT g.game_id, g.date, g.season, g.postseason,
                   g.home_team_id, g.visitor_team_id,
                   g.home_team_score, g.visitor_team_score, g.home_win,
                   ht.full_name AS home_team_name,
                   ht.conference AS home_conference,
                   ht.division AS home_division,
                   vt.full_name AS visitor_team_name,
                   vt.conference AS visitor_conference,
                   vt.division AS visitor_division
            FROM cleaned_games g
            LEFT JOIN cleaned_teams ht ON g.home_team_id = ht.team_id
            LEFT JOIN cleaned_teams vt ON g.visitor_team_id = vt.team_id
            ORDER BY g.date;
        """, conn)
        games.columns = [c.lower() for c in games.columns]
    finally:
        conn.close()

    logger.info(f"Teams: {len(teams)} | Games: {len(games)}")
    games.to_csv(GAMES_FULL_PATH, index=False)
    logger.info(f"Saved games_full.csv ({len(games)} rows)")

    logger.info("Running LR predictions on full dataset...")
    feat_df = build_features()

    model_path = os.path.join(MODEL_DIR, "logistic_regression_model.pkl")
    lr = joblib.load(model_path)

    X = feat_df.drop(columns=["game_id", "home_win"])
    feat_df["predicted_home_win"] = lr.predict(X)
    feat_df["predicted_probability"] = lr.predict_proba(X)[:, 1]

    name_map = games[["game_id", "home_team_name", "visitor_team_name"]].drop_duplicates("game_id")
    preds = (
        feat_df[["game_id", "season", "home_win", "predicted_home_win", "predicted_probability"]]
        .merge(name_map, on="game_id", how="left")
        .rename(columns={"home_win": "actual_home_win"})
    )
    preds.to_csv(PREDICTIONS_PATH, index=False)
    logger.info(f"Saved predictions_vs_actual.csv ({len(preds)} rows)")
    logger.info("Export complete.")


if __name__ == "__main__":
    export()
