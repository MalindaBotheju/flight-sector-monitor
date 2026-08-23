"""
Pipeline entry point — this is what cron actually runs.

One call to main() = one full cycle:
  extract (ingestion.py) -> transform (cleaning.py) -> load (database.py)
  -> enforce 7-day retention

Designed to be safe to run unattended: every failure is logged with
enough context to debug later, and a failure in one run never corrupts
data from previous runs (we only ever INSERT + DELETE-by-age, never UPDATE).
"""

import logging
import os
import sys
import time

import config
import ingestion
import cleaning
import database


def setup_logging():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run() -> None:
    logger = logging.getLogger("main")
    run_start = time.monotonic()
    logger.info("=" * 60)
    logger.info("Pipeline run started.")

    try:
        raw_records = ingestion.fetch_state_vectors()
    except ingestion.OpenSkyRequestError as e:
        # Don't crash the whole scheduled job on a transient API failure —
        # log it clearly so it's visible, but exit gracefully. Cron will just
        # try again on the next scheduled run in 15 minutes.
        logger.error("Extraction failed, skipping this run: %s", e)
        return

    if not raw_records:
        logger.warning("No aircraft returned for the bounding box this run (empty response).")
        return

    cleaned_records = cleaning.clean_records(raw_records)

    try:
        inserted = database.insert_records(cleaned_records)
        deleted = database.enforce_retention()
    except Exception as e:
        logger.exception("Database step failed: %s", e)
        return

    elapsed = time.monotonic() - run_start
    logger.info(
        "Pipeline run complete in %.2fs — inserted=%d, retention_deleted=%d",
        elapsed, inserted, deleted,
    )


if __name__ == "__main__":
    setup_logging()
    run()
