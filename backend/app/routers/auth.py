import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import current_user
from ..models import (
    Household,
    HouseholdInvitation,
    Membership,
    PasswordResetToken,
    RefreshToken,
    Role,
    StorageLocation,
    User,
)
from ..rate_limit import LoginRateLimiter
from ..schemas import (
    LoginRequest,
    LogoutRequest,
    MembershipRead,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserRead,
)
from ..security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from ..services.email import send_email

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
login_limiter = LoginRateLimiter(
    settings.login_rate_limit_attempts,
    settings.login_rate_limit_window_seconds,
)


def is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= datetime.now(UTC)


def token_pair(db: Session, user: User) -> TokenPair:
    raw, digest, expires = create_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=digest, expires_at=expires))
    db.commit()
    return TokenPair(access_token=create_access_token(user.id), refresh_token=raw)


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "email_registered", "message": "E-Mail ist bereits registriert"},
        )
    user = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    invitation = None
    if payload.invitation_token:
        invitation = db.scalar(
            select(HouseholdInvitation)
            .where(HouseholdInvitation.token_hash == hash_token(payload.invitation_token))
            .with_for_update()
        )
        if invitation is None or invitation.accepted_at or is_expired(invitation.expires_at):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Einladung ist ungültig oder abgelaufen"
            )
        if invitation.invited_email and invitation.invited_email.lower() != email:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Einladung gehört zu einer anderen E-Mail"
            )
    db.add(user)
    db.flush()
    if invitation:
        db.add(
            Membership(
                user_id=user.id,
                household_id=invitation.household_id,
                role=invitation.role,
            )
        )
        invitation.accepted_at = datetime.now(UTC)
    else:
        household = Household(name=payload.household_name or "Mein Haushalt")
        db.add(household)
        db.flush()
        db.add(Membership(user_id=user.id, household_id=household.id, role=Role.owner))
        db.add_all(
            [
                StorageLocation(household_id=household.id, name="Kühlschrank"),
                StorageLocation(household_id=household.id, name="Gefrierschrank"),
                StorageLocation(household_id=household.id, name="Vorratsschrank"),
            ]
        )
    return token_pair(db, user)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    client_host = request.client.host if request.client else "unknown"
    key = f"{client_host}:{payload.email.lower()}"
    retry_after = login_limiter.retry_after(key)
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Zu viele Anmeldeversuche. Bitte später erneut versuchen.",
            headers={"Retry-After": str(retry_after)},
        )
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        login_limiter.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-Mail oder Passwort ist falsch")
    login_limiter.reset(key)
    return token_pair(db, user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    stored = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(payload.refresh_token))
        .with_for_update()
    )
    if stored is None or stored.revoked or is_expired(stored.expires_at):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh-Token ist ungültig")
    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Benutzer ist nicht aktiv")
    stored.revoked = True
    return token_pair(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> None:
    stored = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(payload.refresh_token))
    )
    if stored:
        stored.revoked = True
        db.commit()


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    payload: PasswordResetRequest, db: Session = Depends(get_db)
) -> dict[str, str]:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user:
        raw = secrets.token_urlsafe(48)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()
        link = f"{settings.public_url.rstrip('/')}?reset_token={raw}"
        send_email(
            user.email,
            "Vorrat: Passwort zurücksetzen",
            f"Über diesen Link kannst du dein Passwort innerhalb einer Stunde ändern:\n\n{link}",
        )
    return {"message": "Falls die E-Mail registriert ist, wurde ein Link versendet."}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)) -> None:
    reset = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(payload.token))
        .with_for_update()
    )
    if reset is None or reset.used_at or is_expired(reset.expires_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reset-Link ist ungültig oder abgelaufen")
    user = db.get(User, reset.user_id)
    assert user is not None
    user.password_hash = hash_password(payload.password)
    reset.used_at = datetime.now(UTC)
    for token in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id)):
        token.revoked = True
    db.commit()


@router.get("/bootstrap")
def bootstrap(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, object]:
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    return {
        "user": UserRead.model_validate(user),
        "memberships": [MembershipRead.model_validate(item) for item in memberships],
    }
