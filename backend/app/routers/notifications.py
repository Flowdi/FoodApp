from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import HouseholdContext, household_context, require_admin
from ..models import Household, Notification, PushSubscription
from ..schemas import NotificationRead, PushSubscriptionWrite
from ..services.notifications import evaluate_household

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/push-subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def subscribe_push(
    payload: PushSubscriptionWrite,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> None:
    subscription = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if subscription is None:
        subscription = PushSubscription(user_id=context.user.id, **payload.model_dump())
        db.add(subscription)
    else:
        subscription.user_id = context.user.id
        subscription.p256dh = payload.p256dh
        subscription.auth = payload.auth
    db.commit()


@router.get("", response_model=list[NotificationRead])
def notifications(
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.household_id == context.membership.household_id)
            .order_by(Notification.created_at.desc())
            .limit(100)
        )
    )


@router.post("/check")
def run_check(
    context: HouseholdContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    household = db.get(Household, context.membership.household_id)
    assert household is not None
    return {"created": evaluate_household(db, household)}


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: str,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> Notification:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.household_id == context.membership.household_id,
        )
    )
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Warnung nicht gefunden")
    notification.read_at = datetime.now(UTC)
    db.commit()
    db.refresh(notification)
    return notification
