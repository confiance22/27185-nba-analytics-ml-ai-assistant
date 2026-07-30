"""
etl/pipeline.py

Orchestrator that runs the full ETL pipeline in order:
  1. extract  — fetch data from balldontlie API
  2. load_raw — insert JSON blobs into Snowflake raw tables
  3. load_cleaned — validate, flatten, and insert into cleaned tables

Usage:
  python -m etl.pipeline              # run full pipeline
  python -m etl.pipeline --extract    # extract only
  python -m etl.pipeline --load-raw   # raw load only (from cached JSON)
  python -m etl.pipeline --load-clean # cleaned load only (from raw tables)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from etl.extract import extract
from etl.load import load_raw, load_cleaned
from etl.logging_setup import get_logger

logger = get_logger(__name__)


def run_pipeline():
    logger.info("=== Pipeline start ===")

    logger.info("Step 1/3: Extract")
    extract()
    logger.info("Extract complete")

    logger.info("Step 2/3: Load raw")
    raw_result = load_raw()
    logger.info(f"Raw load complete: {raw_result}")

    logger.info("Step 3/3: Load cleaned")
    clean_result = load_cleaned()
    logger.info(f"Clean load complete: {clean_result}")

    logger.info("=== Pipeline complete ===")
    return raw_result, clean_result


def main():
    args = set(sys.argv[1:])
    if not args or "--all" in args:
        run_pipeline()
    elif "--extract" in args:
        extract()
    elif "--load-raw" in args:
        load_raw()
    elif "--load-clean" in args:
        load_cleaned()
    else:
        print("Usage: python -m etl.pipeline [--extract|--load-raw|--load-clean|--all]")


if __name__ == "__main__":
    main()
