"""
etl/extract.py

Fetches raw data from the balldontlie API onto local disk as JSON.
No cleaning or interpretation — that is etl/transform.py's job.
"""

import json
import os
import time

import requests

from config.settings import (
    BALLDONTLIE_API_BASE_URL,
    BALLDONTLIE_API_KEY,
    MAX_RETRIES,
    INITIAL_BACKOFF_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    RAW_DATA_DIR,
    TEAMS_RAW_PATH,
    GAMES_RAW_PATH,
    RATE_LIMIT_SLEEP,
)
from etl.logging_setup import get_logger

logger = get_logger(__name__)


class ExtractError(Exception):
    pass


def fetch_from_api(url: str, params: dict | None = None) -> dict:
    headers = {"Authorization": BALLDONTLIE_API_KEY}
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Requesting {url} (attempt {attempt}/{MAX_RETRIES})")
            response = requests.get(
                url, params=params, headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            logger.info("Request succeeded")
            return payload

        except requests.exceptions.Timeout:
            logger.warning(f"Request timed out on attempt {attempt}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error on attempt {attempt}")
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                retry_after = e.response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        wait = int(retry_after) + 1
                    except (ValueError, TypeError):
                        wait = 60
                else:
                    wait = 60
                logger.warning(
                    f"Rate limited (429). Waiting {wait}s "
                    f"(attempt {attempt}/{MAX_RETRIES})..."
                )
                time.sleep(wait)
                continue
            else:
                logger.warning(f"HTTP error on attempt {attempt}: {e}")
        except ValueError:
            logger.warning(f"Could not parse JSON response on attempt {attempt}")

        if attempt < MAX_RETRIES:
            logger.info(f"Retrying in {backoff}s...")
            time.sleep(backoff)
            backoff *= 2

    raise ExtractError(
        f"Failed to fetch data from {url} after {MAX_RETRIES} attempts"
    )


def fetch_all_pages(base_url: str, params: dict | None = None,
                    partial_path: str | None = None) -> list:
    all_data = []
    cursor = None

    if partial_path and os.path.exists(partial_path):
        partial = load_raw_json_from_disk(partial_path)
        all_data = partial.get("data", [])
        cursor = partial.get("resume_cursor")
        logger.info(
            f"Found partial file at {partial_path} — "
            f"resuming from cursor={cursor} "
            f"({len(all_data)} items already fetched)."
        )

    while True:
        request_params = dict(params or {})
        request_params["per_page"] = 100
        if cursor is not None:
            request_params["cursor"] = cursor

        payload = fetch_from_api(base_url, params=request_params)
        data = payload.get("data", [])
        all_data.extend(data)

        next_cursor = payload.get("meta", {}).get("next_cursor")

        if partial_path:
            partial = {"data": all_data, "resume_cursor": next_cursor}
            with open(partial_path, "w", encoding="utf-8") as f:
                json.dump(partial, f)

        if next_cursor is None:
            break

        cursor = next_cursor
        logger.info(
            f"Fetched {len(data)} items this page ({len(all_data)} total). "
            f"Rate limit pause: sleeping {RATE_LIMIT_SLEEP}s..."
        )
        time.sleep(RATE_LIMIT_SLEEP)

    return all_data


def save_raw_json(data: list, path: str) -> None:
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    logger.info(f"Saved raw API response to {path}")


def load_raw_json_from_disk(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_teams(force_refresh: bool = False) -> list:
    if not force_refresh and os.path.exists(TEAMS_RAW_PATH):
        logger.info(
            f"Found existing file at {TEAMS_RAW_PATH}, "
            f"skipping API call (resume behavior)."
        )
        return load_raw_json_from_disk(TEAMS_RAW_PATH)

    partial_path = TEAMS_RAW_PATH.replace(".json", ".partial.json")
    teams = fetch_all_pages(
        f"{BALLDONTLIE_API_BASE_URL}/teams",
        partial_path=partial_path,
    )

    if len(teams) == 0:
        logger.warning("Teams endpoint returned zero rows.")
        if os.path.exists(TEAMS_RAW_PATH):
            logger.warning(f"Not overwriting existing cache at {TEAMS_RAW_PATH}.")
            _cleanup_partial(partial_path)
            return load_raw_json_from_disk(TEAMS_RAW_PATH)

    save_raw_json(teams, TEAMS_RAW_PATH)
    _cleanup_partial(partial_path)
    logger.info(f"Extract complete: {len(teams)} teams.")
    return teams


def extract_games(force_refresh: bool = False) -> list:
    if not force_refresh and os.path.exists(GAMES_RAW_PATH):
        logger.info(
            f"Found existing file at {GAMES_RAW_PATH}, "
            f"skipping API call (resume behavior)."
        )
        return load_raw_json_from_disk(GAMES_RAW_PATH)

    partial_path = GAMES_RAW_PATH.replace(".json", ".partial.json")
    params = {"seasons[]": [2021, 2022, 2023]}
    games = fetch_all_pages(
        f"{BALLDONTLIE_API_BASE_URL}/games",
        params=params,
        partial_path=partial_path,
    )

    if len(games) == 0:
        logger.warning("Games endpoint returned zero rows.")
        if os.path.exists(GAMES_RAW_PATH):
            logger.warning(f"Not overwriting existing cache at {GAMES_RAW_PATH}.")
            _cleanup_partial(partial_path)
            return load_raw_json_from_disk(GAMES_RAW_PATH)

    save_raw_json(games, GAMES_RAW_PATH)
    _cleanup_partial(partial_path)
    logger.info(f"Extract complete: {len(games)} games.")
    return games


def _cleanup_partial(partial_path: str) -> None:
    if partial_path and os.path.exists(partial_path):
        os.remove(partial_path)
        logger.info(f"Removed partial file {partial_path}")


def extract(force_refresh: bool = False) -> dict:
    teams = extract_teams(force_refresh)
    games = extract_games(force_refresh)
    return {"teams": teams, "games": games}


if __name__ == "__main__":
    data = extract()
    print(
        f"Extracted {len(data['teams'])} teams "
        f"and {len(data['games'])} games. "
        f"Raw files: {TEAMS_RAW_PATH}, {GAMES_RAW_PATH}"
    )
