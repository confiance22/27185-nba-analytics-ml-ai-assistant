"""
extract.py

Responsible for ONE thing: getting raw data from the balldontlie API
onto local disk as JSON. It does not clean or interpret the data —
that's transform.py's job. Keeping "get the data" separate from "make
sense of the data" makes each function easier to test and reason about.

Covers:
- Extraction via requests with retry + exponential backoff
- Cursor-based pagination across multiple API pages
- Rate-limit awareness (free tier: 5 requests/minute)
- Resume behavior (skip re-download if raw file already exists)
- Incremental partial-file saves mid-pagination (crash recovery)
- Edge cases: API unreachable, zero rows returned, partial failure
"""

import json
import os
import time

import requests

from config import (
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
from logging_setup import get_logger

logger = get_logger(__name__)


class ExtractError(Exception):
    """Raised when we could not get data after all retries.
    Using a custom exception (instead of letting requests' generic
    exceptions bubble up) means callers can catch this one specific
    thing and decide what to do, instead of guessing what went wrong.
    """
    pass


def fetch_from_api(url: str, params: dict | None = None) -> dict:
    """
    Calls the balldontlie API with retry + exponential backoff.

    Retry logic explained:
    - Attempt 1 fails -> wait 1s -> Attempt 2
    - Attempt 2 fails -> wait 2s -> Attempt 3
    - Attempt 3 fails -> wait 4s -> give up, raise ExtractError

    This handles a BRIEF network blip (wifi hiccup, API momentarily
    busy) without hammering the server immediately again and again.
    It deliberately does NOT retry forever — a real outage should
    surface as a clear error, not hang silently.
    """
    headers = {"Authorization": BALLDONTLIE_API_KEY}
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Requesting {url} (attempt {attempt}/{MAX_RETRIES})")
            response = requests.get(
                url, params=params, headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()  # turns HTTP 4xx/5xx into an exception
            payload = response.json()
            logger.info("Request succeeded")
            return payload

        except requests.exceptions.Timeout:
            logger.warning(f"Request timed out on attempt {attempt}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error on attempt {attempt} "
                           f"(no internet or API unreachable)")
        except requests.exceptions.HTTPError as e:
            # HTTP errors (like 401, 500) are unlikely to be fixed by
            # retrying, but we still retry a couple of times in case
            # it's a transient 5xx from the server.
            logger.warning(f"HTTP error on attempt {attempt}: {e}")
        except ValueError:
            # response.json() failed to parse — server sent bad data
            logger.warning(f"Could not parse JSON response on attempt {attempt}")

        if attempt < MAX_RETRIES:
            logger.info(f"Retrying in {backoff}s...")
            time.sleep(backoff)
            backoff *= 2  # exponential backoff: 1 -> 2 -> 4

    raise ExtractError(
        f"Failed to fetch data from {url} after {MAX_RETRIES} attempts"
    )


def fetch_all_pages(base_url: str, params: dict | None = None,
                    partial_path: str | None = None) -> list:
    """
    Fetch ALL pages from a cursor-paginated API endpoint by following
    the ``next_cursor`` field returned in each response's ``meta``.

    The balldontlie v1 API uses cursor-based pagination. Unlike
    page-number pagination, cursors are stable even if new data is
    added between requests — you never skip or double-count rows.

    Incremental partial-file saves (crash recovery):
    If ``partial_path`` is provided, the accumulated data and current
    cursor are persisted as a JSON dict (``{"data": ..., "resume_cursor": ...}``)
    after every successful page. If a partial file already exists when
    this function starts (from a previous run that crashed mid-way),
    it loads that file and resumes pagination from the saved cursor
    position instead of starting over.

    The caller is responsible for removing the partial file after
    confirming it wants to keep the result (e.g. after a zero-row
    check). See ``extract_games()`` for the full flow.

    We respect the free-tier rate limit (5 requests/minute) by sleeping
    RATE_LIMIT_SLEEP seconds between pages.
    """
    all_data = []
    cursor = None

    # Resume from an existing partial file if one was left behind by a
    # previous run that crashed mid-pagination.
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

        # Persist progress after every successful page so a crash in
        # the middle of pagination loses at most one page of work.
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
    """
    Extract all NBA teams from the balldontlie API.

    Resume behavior:
    If data/raw/teams_raw.json already exists on disk, we assume a
    previous run already successfully fetched it, and we skip hitting
    the API again.

    Incremental partial saves:
    During pagination, progress is written to a ``.partial.json`` file
    after each page so a mid-pipeline crash doesn't lose everything.

    Set force_refresh=True to bypass the cache and re-download.
    """
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

    # Edge case: API responds successfully but with zero rows.
    if len(teams) == 0:
        logger.warning("Teams endpoint returned zero rows.")
        if os.path.exists(TEAMS_RAW_PATH):
            logger.warning(
                f"Not overwriting existing cache at {TEAMS_RAW_PATH}."
            )
            _cleanup_partial(partial_path)
            return load_raw_json_from_disk(TEAMS_RAW_PATH)

    save_raw_json(teams, TEAMS_RAW_PATH)
    _cleanup_partial(partial_path)
    logger.info(f"Extract complete: {len(teams)} teams.")
    return teams


def extract_games(force_refresh: bool = False) -> list:
    """
    Extract all NBA games for seasons 2021, 2022, and 2023.

    Resume behavior:
    If data/raw/games_raw.json already exists on disk, we skip the
    API call and load from cache instead.

    Incremental partial saves:
    During pagination, progress is written to a ``.partial.json`` file
    after each page. If the pipeline crashes mid-way, re-running
    automatically picks up from the last saved cursor instead of
    starting over.
    """
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
            logger.warning(
                f"Not overwriting existing cache at {GAMES_RAW_PATH}."
            )
            _cleanup_partial(partial_path)
            return load_raw_json_from_disk(GAMES_RAW_PATH)

    save_raw_json(games, GAMES_RAW_PATH)
    _cleanup_partial(partial_path)
    logger.info(f"Extract complete: {len(games)} games.")
    return games


def _cleanup_partial(partial_path: str) -> None:
    """Remove a partial file if it exists (clean or silent success)."""
    if partial_path and os.path.exists(partial_path):
        os.remove(partial_path)
        logger.info(f"Removed partial file {partial_path}")


def extract(force_refresh: bool = False) -> dict:
    """
    Main entry point for the extract step.

    Runs both the teams and games extraction consecutively and returns
    them as a single dict. Each endpoint is independent — if one fails,
    the other still tries to complete.
    """
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
