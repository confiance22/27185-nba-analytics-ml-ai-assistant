"""
config.py

Central place for settings. Nothing sensitive is hardcoded here —
DB credentials and API keys come from environment variables (loaded
from a local .env file that is NOT committed to git — see .gitignore).
"""

import os

from dotenv import load_dotenv

# Loads variables from a .env file in the project root into the
# process environment. If .env doesn't exist, this just does nothing
# (no crash) — useful because on a CI server env vars might be set
# a different way.
load_dotenv()

# --- balldontlie API settings ---
BALLDONTLIE_API_BASE_URL = "https://api.balldontlie.io/v1"
BALLDONTLIE_API_KEY = os.getenv("BALLDONTLIE_API_KEY")

# --- Local file paths (used for the "resume" requirement) ---
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
TEAMS_RAW_PATH = os.path.join(RAW_DATA_DIR, "teams_raw.json")
GAMES_RAW_PATH = os.path.join(RAW_DATA_DIR, "games_raw.json")

# --- Retry/backoff settings for the Extract step ---
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1  # doubles each retry: 1s, 2s, 4s
REQUEST_TIMEOUT_SECONDS = 15

# --- Rate limit (free tier: 5 requests/minute) ---
# 60 seconds / 5 requests = 12s minimum between requests.
# We add extra margin to reduce 429s during normal pagination.
RATE_LIMIT_SLEEP = 15

# --- PostgreSQL connection settings ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
