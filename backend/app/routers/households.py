import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import HouseholdContext, current_user, require_admin
from ..models import Household, HouseholdInvitation, Membership, Role, User
from ..schemas import InvitationAccept, InvitationAccepted, InvitationCreate, InvitationRead
from ..security import hash_token
from ..services.email import send_email

router = APIRouter(prefix="/households", tags=["households"])


def is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= datetime.now(UTC)


@router.post("/invitations", response_model=InvitationRead, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationCreate,
    context: HouseholdContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> InvitationRead:
    if payload.role == Role.owner:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Owner kann nicht eingeladen werden"
        )
    raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    invitation = HouseholdInvitation(
        household_id=context.membership.household_id,
        created_by_id=context.user.id,
        invited_email=payload.email.lower() if payload.email else None,
        role=payload.role,
        token_hash=hash_token(raw),
        expires_at=expires_at,
    )
    db.add(invitation)
    db.commit()
    url = f"{get_settings().public_url.rstrip('/')}?invite={raw}"
    if payload.email:
        household = db.get(Household, context.membership.household_id)
        household_name = household.name if household else "einem Haushalt"
        send_email(
            payload.email,
            "Einladung zu Vorrat",
            f"Du wurdest zu {household_name} eingeladen:\n\n{url}",
        )
    return InvitationRead(token=raw, invitation_url=url, expires_at=expires_at)


@router.post("/invitations/accept", response_model=InvitationAccepted)
def accept_invitation(
    payload: InvitationAccept,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> InvitationAccepted:
    invitation = db.scalar(
        select(HouseholdInvitation)
        .where(HouseholdInvitation.token_hash == hash_token(payload.token))
        .with_for_update()
    )
    if invitation is None or invitation.accepted_at or is_expired(invitation.expires_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Einladung ist ungültig oder abgelaufen")
    if invitation.invited_email and invitation.invited_email.lower() != user.email.lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Einladung gehört zu einer anderen E-Mail")
    existing = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.household_id == invitation.household_id,
        )
    )
    if existing is None:
        db.add(
            Membership(
                user_id=user.id,
                household_id=invitation.household_id,
                role=invitation.role,
            )
        )
    invitation.accepted_at = datetime.now(UTC)
    db.commit()
    return InvitationAccepted(household_id=invitation.household_id, role=invitation.role)
