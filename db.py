"""
db.py

Handles the Snowflake connection and raw/cleaned table creation.

Snowflake differences from Postgres that affect this module:
  - VARIANT instead of JSONB for semi-structured data.
    VARIANT is Snowflake's native type for JSON/Parquet/XML and supports
    path traversal with colon notation (raw_data:field_name::STRING).
  - IDENTITY(1,1) instead of SERIAL for auto-increment columns.
  - CURRENT_TIMESTAMP() instead of NOW().
  - MERGE instead of INSERT ... ON CONFLICT for upserts (used in
    load_cleaned.py).

Proxy note:
  The Snowflake Python connector performs OCSP certificate checks on
  import and connect, which hang if HTTP_PROXY is set. We exclude
  Snowflake's OCSP endpoint from the proxy to avoid this.
"""

import os

# Bypass proxy for Snowflake (OCSP checks + the actual server connection)
# so the proxy doesn't interfere with Snowflake's SSL handshake.
_snowflake_hosts = "ocsp.snowflakecomputing.com,.snowflakecomputing.com"
_existing = os.environ.get("NO_PROXY", "")
if _existing:
    os.environ["NO_PROXY"] = f"{_existing},{_snowflake_hosts}"
else:
    os.environ["NO_PROXY"] = _snowflake_hosts

import snowflake.connector
from snowflake.connector.errors import Error as SnowflakeError

from config import (
    SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_USER,
    SNOWFLAKE_PASSWORD,
    SNOWFLAKE_WAREHOUSE,
    SNOWFLAKE_DATABASE,
    SNOWFLAKE_SCHEMA,
)
from logging_setup import get_logger

logger = get_logger(__name__)


class DatabaseError(Exception):
    """Raised for connection failures or table lock issues."""
    pass


def get_connection():
    if not all([SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD]):
        raise DatabaseError(
            "Missing Snowflake credentials. Check that your .env file has "
            "SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and SNOWFLAKE_PASSWORD set."
        )
    try:
        conn = snowflake.connector.connect(
            account=SNOWFLAKE_ACCOUNT,
            user=SNOWFLAKE_USER,
            password=SNOWFLAKE_PASSWORD,
            warehouse=SNOWFLAKE_WAREHOUSE,
            database=SNOWFLAKE_DATABASE,
            schema=SNOWFLAKE_SCHEMA,
            login_timeout=10,
        )
        return conn
    except SnowflakeError as e:
        logger.error(f"Could not connect to Snowflake: {e}")
        raise DatabaseError(f"Database connection failed: {e}") from e


def _ensure_database(conn):
    """Create the database and schema if they don't exist yet."""
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {SNOWFLAKE_DATABASE};")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA};")
    conn.commit()


def init_raw_tables(conn):
    """
    Creates raw_teams and raw_games tables if they don't exist.

    Uses VARIANT (Snowflake's semi-structured type) instead of Postgres's
    JSONB. IDENTITY(1,1) replaces SERIAL for auto-increment, and
    CURRENT_TIMESTAMP() replaces NOW().
    """
    _ensure_database(conn)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw_teams (
                id INTEGER IDENTITY(1,1) PRIMARY KEY,
                raw_data VARIANT NOT NULL,
                loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw_games (
                id INTEGER IDENTITY(1,1) PRIMARY KEY,
                raw_data VARIANT NOT NULL,
                loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            );
        """)
    conn.commit()
    logger.info("Ensured raw_teams and raw_games tables exist")


def init_cleaned_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cleaned_teams (
                team_id INTEGER PRIMARY KEY,
                city VARCHAR NOT NULL DEFAULT '',
                name VARCHAR NOT NULL,
                full_name VARCHAR NOT NULL,
                abbreviation VARCHAR NOT NULL DEFAULT '',
                conference VARCHAR NOT NULL,
                division VARCHAR NOT NULL
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS cleaned_games (
                game_id INTEGER PRIMARY KEY,
                date DATE NOT NULL,
                season INTEGER NOT NULL,
                postseason BOOLEAN NOT NULL DEFAULT FALSE,
                home_team_id INTEGER NOT NULL,
                visitor_team_id INTEGER NOT NULL,
                home_team_score INTEGER NOT NULL,
                visitor_team_score INTEGER NOT NULL,
                home_win INTEGER NOT NULL
                    CHECK (home_win IN (0, 1))
            );
        """)
    conn.commit()
    logger.info("Ensured cleaned_teams and cleaned_games tables exist")
