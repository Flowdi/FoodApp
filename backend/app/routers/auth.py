from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..models import Household, Membership, RefreshToken, Role, StorageLocation, User
from ..schemas import LoginRequest, MembershipRead, RegisterRequest, TokenPair, UserRead
from ..security import create_access_token, create_refresh_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def token_pair(db: Session, user: User) -> TokenPair:
    raw, digest, expires = create_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=digest, expires_at=expires))
    db.commit()
    return TokenPair(access_token=create_access_token(user.id), refresh_token=raw)


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "E-Mail ist bereits registriert")
    user = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    household = Household(name=payload.household_name)
    db.add_all([user, household])
    db.flush()
    db.add(Membership(user_id=user.id, household_id=household.id, role=Role.owner))
    db.add_all(
        [
            StorageLocation(household_id=household.id, name="Kühlschrank"),
            StorageLocation(household_id=household.id, name="Gefrierschrank"),
            StorageLocation(household_id=household.id, name="Vorratsschrank"),
        ]
    )
    db.commit()
    return token_pair(db, user)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-Mail oder Passwort ist falsch")
    return token_pair(db, user)


@router.get("/bootstrap")
def bootstrap(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, object]:
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    return {
        "user": UserRead.model_validate(user),
        "memberships": [MembershipRead.model_validate(item) for item in memberships],
    }
