"""Fires run_once() on the configured hours, then sleeps. Ctrl+C to stop."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import Settings
from .pipeline import run_once

logger = logging.getLogger(__name__)


def start(settings: Settings) -> None:
    # No timezone= kwarg: APScheduler auto-detects the system's local timezone
    # via tzlocal. The literal string "local" is not a valid IANA zone name
    # and raises ZoneInfoNotFoundError if passed explicitly.
    scheduler = BlockingScheduler()
    hours = ",".join(str(h) for h in settings.scheduler.run_hours)

    def job() -> None:
        logger.info("Scheduled run starting")
        try:
            stats = run_once(settings)
            logger.info("Scheduled run complete: %s", stats)
        except Exception:
            logger.exception("Scheduled run failed")

    scheduler.add_job(job, CronTrigger(hour=hours, minute=0))
    logger.info("Scheduler started - runs at hours [%s] local time. Ctrl+C to stop.", hours)
    scheduler.start()
