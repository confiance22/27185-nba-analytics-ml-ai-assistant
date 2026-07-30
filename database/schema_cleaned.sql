-- Cleaned analytics tables — typed, validated, flattened data.
-- Created automatically by database/db.py::init_cleaned_tables().

CREATE TABLE IF NOT EXISTS cleaned_teams (
    team_id      INTEGER PRIMARY KEY,
    city         VARCHAR NOT NULL DEFAULT '',
    name         VARCHAR NOT NULL,
    full_name    VARCHAR NOT NULL,
    abbreviation VARCHAR NOT NULL DEFAULT '',
    conference   VARCHAR NOT NULL,
    division     VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS cleaned_games (
    game_id            INTEGER PRIMARY KEY,
    date               DATE    NOT NULL,
    season             INTEGER NOT NULL,
    postseason         BOOLEAN NOT NULL DEFAULT FALSE,
    home_team_id       INTEGER NOT NULL,
    visitor_team_id    INTEGER NOT NULL,
    home_team_score    INTEGER NOT NULL,
    visitor_team_score INTEGER NOT NULL,
    home_win           INTEGER NOT NULL CHECK (home_win IN (0, 1))
);
