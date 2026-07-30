-- Raw ingestion tables — store API JSON blobs verbatim in VARIANT columns.
-- These are created automatically by database/db.py::init_raw_tables().

CREATE TABLE IF NOT EXISTS raw_teams (
    id        INTEGER IDENTITY(1,1) PRIMARY KEY,
    raw_data  VARIANT      NOT NULL,
    loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS raw_games (
    id        INTEGER IDENTITY(1,1) PRIMARY KEY,
    raw_data  VARIANT      NOT NULL,
    loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
