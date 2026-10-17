import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from ..database import SessionLocal
from ..dependencies import HouseholdContext, household_context
from ..models import AuditLog, Notification, ShoppingListItem, StockMovement

router = APIRouter(tags=["events"])


def household_revision(household_id: str) -> tuple[int, int, int, int]:
    with SessionLocal() as db:
        movement_count = db.scalar(
            select(func.count(StockMovement.id)).where(StockMovement.household_id == household_id)
        )
        audit_count = db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.household_id == household_id)
        )
        notification_count = db.scalar(
            select(func.count(Notification.id)).where(Notification.household_id == household_id)
        )
        shopping_revision = db.scalar(
            select(func.coalesce(func.sum(ShoppingListItem.version), 0)).where(
                ShoppingListItem.household_id == household_id
            )
        )
    return (
        int(movement_count or 0),
        int(audit_count or 0),
        int(notification_count or 0),
        int(shopping_revision or 0),
    )


async def event_stream(request: Request, household_id: str) -> AsyncIterator[str]:
    revision = household_revision(household_id)
    yield "event: ready\ndata: {}\n\n"
    elapsed = 0
    while not await request.is_disconnected():
        await asyncio.sleep(2)
        elapsed += 2
        current = household_revision(household_id)
        if current != revision:
            revision = current
            yield f"event: changed\ndata: {json.dumps({'revision': current})}\n\n"
            elapsed = 0
        elif elapsed >= 20:
            yield ": keepalive\n\n"
            elapsed = 0


@router.get("/events")
def events(
    request: Request,
    context: HouseholdContext = Depends(household_context),
) -> StreamingResponse:
    return StreamingResponse(
        event_stream(request, context.membership.household_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
