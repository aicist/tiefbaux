"""Background-Scheduler für tägliche Ausschreibungssuche."""

from __future__ import annotations

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import settings
from ..database import SessionLocal
from .inbound_email_service import sync_inbound_mailbox
from .tender_crawler import refresh_tenders

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _daily_tender_crawl():
    """Job: Holt neue Ausschreibungen von TED."""
    logger.info("Scheduled tender crawl starting...")
    db = SessionLocal()
    try:
        result = refresh_tenders(db)
        logger.info("Scheduled crawl done: %s", result)
    except Exception as e:
        logger.error("Scheduled crawl failed: %s", e)
    finally:
        db.close()


def _poll_inbound_mailbox():
    """Job: Pollt Demo-Postfach und verarbeitet neue Mails."""
    db = SessionLocal()
    try:
        result = sync_inbound_mailbox(db, max_messages=25)
        logger.info("Inbound mailbox sync done: %s", result)
    except Exception as exc:
        logger.error("Inbound mailbox sync failed: %s", exc)
    finally:
        db.close()


def start_scheduler():
    """Startet den Background-Scheduler mit täglichem Crawl um 6:00."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _daily_tender_crawl,
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_tender_crawl",
        name="Tägliche Ausschreibungssuche",
        replace_existing=True,
    )

    if settings.inbound_email_enabled:
        _scheduler.add_job(
            _poll_inbound_mailbox,
            trigger=IntervalTrigger(minutes=settings.inbound_email_poll_minutes),
            id="inbound_mailbox_poll",
            name="Demo-Postfach Polling",
            replace_existing=True,
        )
    _scheduler.start()
    logger.info(
        "Scheduler started — tender crawl 06:00, inbox polling=%s (alle %d min)",
        "on" if settings.inbound_email_enabled else "off",
        settings.inbound_email_poll_minutes,
    )


def stop_scheduler():
    """Stoppt den Scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
