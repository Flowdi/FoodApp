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
    x_household_id: str = Header(alias="X-Household-ID"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HouseholdContext:
    membership = db.scalar(
        select(Membership).where(
            Membership.household_id == x_household_id,
            Membership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kein Zugriff auf diesen Haushalt")
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
