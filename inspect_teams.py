"""
inspect_teams.py

Quick diagnostic script that connects to Postgres and prints every row
from raw_teams in a readable table so we can visually assess which
entries are real NBA teams versus G-League, All-Star, defunct, or
other non-NBA entities.

No filtering — the whole point is to see everything the API returned.
"""

from db import get_connection
from logging_setup import get_logger

logger = get_logger(__name__)


def inspect_teams():
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    raw_data->>'id'           AS team_id,
                    raw_data->>'abbreviation'  AS abbreviation,
                    raw_data->>'city'          AS city,
                    raw_data->>'name'          AS name,
                    raw_data->>'full_name'     AS full_name,
                    raw_data->>'conference'    AS conference,
                    raw_data->>'division'      AS division
                FROM raw_teams
                ORDER BY (raw_data->>'id')::int;
            """)

            rows = cur.fetchall()

        if not rows:
            print("No rows found in raw_teams.")
            return

        # Column widths for alignment
        id_w = max(len(r[0]) for r in rows)
        abb_w = max(len(r[1]) for r in rows)
        city_w = max(len(r[2]) for r in rows)
        name_w = max(len(r[3]) for r in rows)
        full_w = max(len(r[4]) for r in rows)
        conf_w = max(len(r[5]) for r in rows)

        # Header
        header = (
            f"{'ID':>{id_w}}  "
            f"{'Abr':>{abb_w}}  "
            f"{'City':<{city_w}}  "
            f"{'Name':<{name_w}}  "
            f"{'Full Name':<{full_w}}  "
            f"{'Conf':<{conf_w}}  "
            f"Division"
        )
        sep = "-" * len(header)
        print(f"\nRaw teams table ({len(rows)} rows):\n")
        print(header)
        print(sep)

        for r in rows:
            print(
                f"{r[0]:>{id_w}}  "
                f"{r[1]:>{abb_w}}  "
                f"{r[2]:<{city_w}}  "
                f"{r[3]:<{name_w}}  "
                f"{r[4]:<{full_w}}  "
                f"{r[5]:<{conf_w}}  "
                f"{r[6]}"
            )

        print(f"\n{len(rows)} rows total.\n")

    finally:
        conn.close()


if __name__ == "__main__":
    inspect_teams()
