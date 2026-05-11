from __future__ import annotations

import logging

from app.logging_setup import setup_logging
from app.workers.run_once import run_dev_tick_sequential

if __name__ == "__main__":
    setup_logging()
    try:
        run_dev_tick_sequential()
    except Exception:
        logging.getLogger("contexthub.workers").error("worker process exiting after failure (ERROR)")
        raise
