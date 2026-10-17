from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Membership, Role, User
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class HouseholdContext:
    user: User
    membership: Membership


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Anmeldung erforderlich")
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ungültige Anmeldung") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Benutzer ist nicht aktiv")
    return user


def household_context(
    x_household_id: str | None = Header(default=None, alias="X-Household-ID"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HouseholdContext:
    household_id = (x_household_id or "").strip()
    if household_id:
        membership = db.scalar(
            select(Membership).where(
                Membership.household_id == household_id,
                Membership.user_id == user.id,
            )
        )
    else:
        membership = db.scalar(
            select(Membership)
            .where(Membership.user_id == user.id)
            .order_by(Membership.household_id)
        )
    if membership is None:
        if household_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {
                    "code": "household_not_found",
                    "message": (
                        "Der ausgewählte Haushalt wurde nicht gefunden oder ist nicht zugänglich."
                    ),
                },
            )
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {
                "code": "no_household",
                "message": "Für dieses Konto ist noch kein Haushalt eingerichtet.",
            },
        )
    return HouseholdContext(user, membership)


def require_writer(
    context: HouseholdContext = Depends(household_context),
) -> HouseholdContext:
    if context.membership.role == Role.viewer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur Lesezugriff")
    return context


def require_admin(
    context: HouseholdContext = Depends(household_context),
) -> HouseholdContext:
    if context.membership.role not in {Role.owner, Role.admin}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administratorrechte erforderlich")
    return context
