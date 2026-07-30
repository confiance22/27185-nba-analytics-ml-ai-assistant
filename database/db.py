"""
database/db.py

Snowflake connection and table creation. Excludes Snowflake hosts from
the proxy so OCSP checks and the actual connection don't get blocked.
"""

import os

_snowflake_hosts = "ocsp.snowflakecomputing.com,.snowflakecomputing.com"
_existing = os.environ.get("NO_PROXY", "")
if _existing:
    os.environ["NO_PROXY"] = f"{_existing},{_snowflake_hosts}"
else:
    os.environ["NO_PROXY"] = _snowflake_hosts

import snowflake.connector
from snowflake.connector.errors import Error as SnowflakeError

from config.settings import (
    SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_USER,
    SNOWFLAKE_PASSWORD,
    SNOWFLAKE_WAREHOUSE,
    SNOWFLAKE_DATABASE,
    SNOWFLAKE_SCHEMA,
)
from etl.logging_setup import get_logger

logger = get_logger(__name__)


class DatabaseError(Exception):
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
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {SNOWFLAKE_DATABASE};")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA};")
    conn.commit()


def init_raw_tables(conn):
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
