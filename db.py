"""
db.py

Handles the PostgreSQL connection and raw-layer table creation.

Why a separate raw layer?
- raw_teams and raw_games store every JSON object exactly as the API
  returned it — no parsing, no renaming, no type coercion.
- If your cleaning logic has a bug or you change your transform rules
  later, you can re-derive everything from raw without calling the API
  again. This is your safety net.
"""

import psycopg2

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
from logging_setup import get_logger

logger = get_logger(__name__)


class DatabaseError(Exception):
    """Raised for connection failures or table lock issues."""
    pass


def get_connection():
    if not all([DB_NAME, DB_USER, DB_PASSWORD]):
        raise DatabaseError(
            "Missing DB credentials. Check that your .env file has "
            "DB_NAME, DB_USER, and DB_PASSWORD set."
        )
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=10,
        )
        return conn
    except psycopg2.OperationalError as e:
        # Covers: wrong password, DB not running, network unreachable,
        # or the target table/row is locked by another session.
        logger.error(f"Could not connect to the database: {e}")
        raise DatabaseError(f"Database connection failed: {e}") from e


def init_raw_tables(conn):
    """
    Creates raw_teams and raw_games tables if they don't already exist.

    Uses IF NOT EXISTS so running this repeatedly is safe (idempotent).
    Each row stores exactly one JSON object from the API as a JSONB
    column — no parsing or flattening happens at this layer.
    """
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw_teams (
                id SERIAL PRIMARY KEY,
                raw_data JSONB NOT NULL,
                loaded_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw_games (
                id SERIAL PRIMARY KEY,
                raw_data JSONB NOT NULL,
                loaded_at TIMESTAMP DEFAULT NOW()
            );
        """)
    conn.commit()
    logger.info("Ensured raw_teams and raw_games tables exist")


def init_cleaned_tables(conn):
    """
    Creates cleaned_teams and cleaned_games tables if they don't exist.

    cleaned_teams uses the team_id from the API as its PRIMARY KEY so
    that ON CONFLICT DO UPDATE / DO NOTHING works naturally.

    cleaned_games has foreign-key references to cleaned_teams.team_id
    so Postgres itself enforces that every game references a real team.
    The game_id is the PRIMARY KEY, which is what ON CONFLICT uses
    during the incremental game load.
    """
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cleaned_teams (
                team_id INTEGER PRIMARY KEY,
                city TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                abbreviation TEXT NOT NULL DEFAULT '',
                conference TEXT NOT NULL,
                division TEXT NOT NULL
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS cleaned_games (
                game_id INTEGER PRIMARY KEY,
                date DATE NOT NULL,
                season INTEGER NOT NULL,
                postseason BOOLEAN NOT NULL DEFAULT FALSE,
                home_team_id INTEGER NOT NULL
                    REFERENCES cleaned_teams(team_id),
                visitor_team_id INTEGER NOT NULL
                    REFERENCES cleaned_teams(team_id),
                home_team_score INTEGER NOT NULL,
                visitor_team_score INTEGER NOT NULL,
                home_win INTEGER NOT NULL
                    CHECK (home_win IN (0, 1))
            );
        """)
    conn.commit()
    logger.info("Ensured cleaned_teams and cleaned_games tables exist")
