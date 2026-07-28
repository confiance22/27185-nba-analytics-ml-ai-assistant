"""
logging_setup.py

One function that every module calls to get a properly configured
logger. Centralizing this means every log line has a consistent
format: timestamp, severity level, module name, message.

Why logging instead of print()?
- print() output disappears once the terminal closes.
- logging can write to a file AND the console at the same time.
- logging has severity levels (INFO/WARNING/ERROR) so you can filter
  ("show me only warnings and errors from last night's run").
- Each line is timestamped automatically, which matters when you're
  debugging "why did the run at 2am fail?" after the fact.
"""

import logging
import os

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "pipeline.log")


def get_logger(name: str) -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)

    # Guard against adding duplicate handlers if get_logger() is
    # called more than once for the same module (e.g. re-imports).
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler - so you still see what's happening live
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler - so there's a record after the terminal is gone
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
