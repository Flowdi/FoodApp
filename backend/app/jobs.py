import logging

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
from sqlalchemy import select

from .database import SessionLocal
from .models import Household
from .services.notifications import evaluate_household

logger = logging.getLogger(__name__)


def run_daily_checks() -> None:
    with SessionLocal() as db:
        for household in db.scalars(select(Household)):
            try:
                evaluate_household(db, household)
            except Exception:
                db.rollback()
                logger.exception("Daily checks failed for household %s", household.id)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_daily_checks,
        "cron",
        hour=4,
        minute=0,
        id="daily-inventory-checks",
        replace_existing=True,
    )
    return scheduler
