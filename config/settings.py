"""
settings.py

Central place for settings. Nothing sensitive is hardcoded here —
DB credentials and API keys come from environment variables (loaded
from a local .env file that is NOT committed to git — see .gitignore).
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- balldontlie API settings ---
BALLDONTLIE_API_BASE_URL = "https://api.balldontlie.io/v1"
BALLDONTLIE_API_KEY = os.getenv("BALLDONTLIE_API_KEY")

# --- Local file paths ---
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
TEAMS_RAW_PATH = os.path.join(RAW_DATA_DIR, "teams_raw.json")
GAMES_RAW_PATH = os.path.join(RAW_DATA_DIR, "games_raw.json")

# --- Retry/backoff settings for the Extract step ---
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1
REQUEST_TIMEOUT_SECONDS = 15

# --- Rate limit (free tier: 5 requests/minute) ---
RATE_LIMIT_SLEEP = 15

# --- Snowflake connection settings ---
SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT")
SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER")
SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PASSWORD")
SNOWFLAKE_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE")
SNOWFLAKE_DATABASE = os.getenv("SNOWFLAKE_DATABASE", "NBA_PROJECT")
SNOWFLAKE_SCHEMA = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")

# --- Groq (AI Assistant) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
