import json
import logging
import smtplib
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage

from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Household,
    Membership,
    MinStockRule,
    Notification,
    Product,
    PushSubscription,
    StockBatch,
    User,
)
from ..units import sum_converted

logger = logging.getLogger(__name__)


def dispatch_notification(db: Session, notification: Notification) -> None:
    settings = get_settings()
    channels = list(notification.sent_channels)
    member_rows = list(
        db.execute(
            select(User, Membership)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.household_id == notification.household_id,
                User.is_active.is_(True),
            )
        )
    )
    if settings.smtp_host and "email" not in channels:
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                for member, membership in member_rows:
                    if "email" not in membership.notification_channels:
                        continue
                    message = EmailMessage()
                    message["Subject"] = "Vorrat: Neue Warnung"
                    message["From"] = settings.smtp_from
                    message["To"] = member.email
                    message.set_content(notification.message)
                    smtp.send_message(message)
                    if "email" not in channels:
                        channels.append("email")
        except (OSError, smtplib.SMTPException):
            logger.exception("Could not send notification email")
    if settings.vapid_private_key and "push" not in channels:
        push_user_ids = [
            member.id
            for member, membership in member_rows
            if "push" in membership.notification_channels
        ]
        subscriptions = list(
            db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(push_user_ids)))
        )
        delivered = False
        for subscription in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                    },
                    data=json.dumps({"title": "Vorrat", "body": notification.message}),
                    vapid_private_key=settings.vapid_private_key,
                    vapid_claims={"sub": settings.vapid_subject},
                )
                delivered = True
            except WebPushException:
                logger.exception("Could not send web push")
        if delivered:
            channels.append("push")
    notification.sent_channels = channels


def create_notification(
    db: Session,
    *,
    household_id: str,
    kind: str,
    dedupe_key: str,
    message: str,
) -> Notification | None:
    existing = db.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
    if existing:
        return None
    notification = Notification(
        household_id=household_id,
        kind=kind,
        dedupe_key=dedupe_key,
        message=message,
    )
    db.add(notification)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None
    dispatch_notification(db, notification)
    return notification


def evaluate_household(db: Session, household: Household) -> int:
    created = 0
    rules = list(
        db.scalars(
            select(MinStockRule).where(
                MinStockRule.household_id == household.id,
                MinStockRule.active.is_(True),
            )
        )
    )
    for rule in rules:
        product = db.get(Product, rule.product_id)
        batches = db.scalars(
            select(StockBatch).where(
                StockBatch.household_id == household.id,
                StockBatch.product_id == rule.product_id,
                StockBatch.quantity > 0,
            )
        )
        current_quantity = sum_converted(
            ((batch.quantity, batch.unit) for batch in batches), rule.unit
        )
        dedupe_key = f"low-stock:{rule.id}"
        existing = db.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
        if current_quantity < rule.minimum_quantity and existing is None:
            if create_notification(
                db,
                household_id=household.id,
                kind="low_stock",
                dedupe_key=dedupe_key,
                message=(
                    f"{product.name if product else 'Produkt'}: Bestand {current_quantity} "
                    f"{rule.unit}, Mindestbestand {rule.minimum_quantity} {rule.unit}"
                ),
            ):
                created += 1
        elif current_quantity >= rule.minimum_quantity and existing and not existing.resolved_at:
            existing.resolved_at = datetime.now(UTC)
            existing.dedupe_key = f"resolved:{existing.id}"

    threshold = date.today() + timedelta(days=household.expiry_warning_days)
    batches = db.scalars(
        select(StockBatch).where(
            StockBatch.household_id == household.id,
            StockBatch.quantity > 0,
            StockBatch.best_before.is_not(None),
            StockBatch.best_before <= threshold,
        )
    )
    for batch in batches:
        product = db.get(Product, batch.product_id)
        if create_notification(
            db,
            household_id=household.id,
            kind="expiry",
            dedupe_key=f"expiry:{batch.id}:{batch.best_before}",
            message=(
                f"{product.name if product else 'Produkt'} läuft am "
                f"{batch.best_before:%d.%m.%Y} ab."
            ),
        ):
            created += 1
    db.commit()
    return created
