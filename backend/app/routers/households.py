import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import HouseholdContext, current_user, household_context, require_admin
from ..models import Household, HouseholdInvitation, Membership, Role, User
from ..schemas import (
    HouseholdRead,
    HouseholdUpdate,
    InvitationAccept,
    InvitationAccepted,
    InvitationCreate,
    InvitationRead,
    MemberRead,
    MemberRoleUpdate,
)
from ..security import hash_token
from ..services.email import send_email

router = APIRouter(prefix="/households", tags=["households"])


def is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= datetime.now(UTC)


@router.get("/current", response_model=HouseholdRead)
def current_household(
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> Household:
    household = db.get(Household, context.membership.household_id)
    assert household is not None
    return household


@router.patch("/current", response_model=HouseholdRead)
def update_household(
    payload: HouseholdUpdate,
    context: HouseholdContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Household:
    household = db.get(Household, context.membership.household_id)
    assert household is not None
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(household, field, value)
    db.commit()
    db.refresh(household)
    return household


@router.get("/members", response_model=list[MemberRead])
def members(
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> list[MemberRead]:
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.household_id == context.membership.household_id)
        .order_by(User.display_name)
    )
    return [
        MemberRead(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=membership.role,
        )
        for membership, user in rows
    ]


def manageable_membership(db: Session, context: HouseholdContext, user_id: str) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.household_id == context.membership.household_id,
            Membership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mitglied nicht gefunden")
    if membership.role == Role.owner:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "owner_role_locked", "message": "Owner kann hier nicht geändert werden"},
        )
    if context.membership.role == Role.admin and membership.role == Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins können keine Admins verwalten")
    return membership


@router.patch("/members/{user_id}", response_model=MemberRead)
def update_member(
    user_id: str,
    payload: MemberRoleUpdate,
    context: HouseholdContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MemberRead:
    if payload.role == Role.owner:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Owner-Rolle ist nicht übertragbar"
        )
    if context.membership.role == Role.admin and payload.role == Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur Owner können Admins ernennen")
    membership = manageable_membership(db, context, user_id)
    membership.role = payload.role
    user = db.get(User, user_id)
    assert user is not None
    db.commit()
    return MemberRead(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
    )


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: str,
    context: HouseholdContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    membership = manageable_membership(db, context, user_id)
    db.delete(membership)
    db.commit()


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
