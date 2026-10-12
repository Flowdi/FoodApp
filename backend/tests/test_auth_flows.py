from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from backend.app.models import PasswordResetToken, User
from backend.app.security import hash_token


async def register(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "Test User",
            "password": "strong-password",
            "household_name": "Test Household",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_refresh_tokens_rotate_and_logout_revokes(client: httpx.AsyncClient) -> None:
    tokens = await register(client, "rotation@example.com")

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    replay = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401

    logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_tokens["refresh_token"]},
    )
    assert logout.status_code == 204
    after_logout = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_tokens["refresh_token"]},
    )
    assert after_logout.status_code == 401


@pytest.mark.asyncio
async def test_password_reset_changes_password_and_is_single_use(
    client: httpx.AsyncClient,
) -> None:
    await register(client, "reset@example.com")
    raw_token = "known-reset-token"
    with client.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "reset@example.com"))
        assert user is not None
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()

    response = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "password": "new-strong-password"},
    )
    assert response.status_code == 204

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "strong-password"},
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "new-strong-password"},
    )
    assert new_login.status_code == 200

    reused = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "password": "another-password"},
    )
    assert reused.status_code == 400


@pytest.mark.asyncio
async def test_password_reset_request_does_not_reveal_accounts(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "unknown@example.com"},
    )
    assert response.status_code == 202
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_repeated_failures(client: httpx.AsyncClient) -> None:
    credentials = {"email": "blocked@example.com", "password": "wrong-password"}
    for _ in range(5):
        response = await client.post("/api/v1/auth/login", json=credentials)
        assert response.status_code == 401

    blocked = await client.post("/api/v1/auth/login", json=credentials)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_invitation_adds_user_to_household(client: httpx.AsyncClient, auth) -> None:
    owner_headers, _, _ = auth
    invitation = await client.post(
        "/api/v1/households/invitations",
        headers=owner_headers,
        json={"email": "invitee@example.com", "role": "member"},
    )
    assert invitation.status_code == 201
    raw_token = invitation.json()["token"]

    invitee = await register(client, "invitee@example.com")
    accepted = await client.post(
        "/api/v1/households/invitations/accept",
        headers={"Authorization": f"Bearer {invitee['access_token']}"},
        json={"token": raw_token},
    )
    assert accepted.status_code == 200
    assert accepted.json()["household_id"] == owner_headers["X-Household-ID"]

    shared_headers = {
        "Authorization": f"Bearer {invitee['access_token']}",
        "X-Household-ID": owner_headers["X-Household-ID"],
    }
    products = await client.get("/api/v1/products", headers=shared_headers)
    assert products.status_code == 200
    assert products.json()[0]["name"] == "Milch"

    reused = await client.post(
        "/api/v1/households/invitations/accept",
        headers=shared_headers,
        json={"token": raw_token},
    )
    assert reused.status_code == 400


@pytest.mark.asyncio
async def test_invited_user_can_register_directly(client: httpx.AsyncClient, auth) -> None:
    owner_headers, _, _ = auth
    invitation = await client.post(
        "/api/v1/households/invitations",
        headers=owner_headers,
        json={"email": "new-user@example.com", "role": "viewer"},
    )
    raw_token = invitation.json()["token"]

    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new-user@example.com",
            "display_name": "New User",
            "password": "strong-password",
            "invitation_token": raw_token,
        },
    )
    assert registration.status_code == 201
    access_token = registration.json()["access_token"]
    bootstrap = await client.get(
        "/api/v1/auth/bootstrap",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert bootstrap.json()["memberships"] == [
        {"household_id": owner_headers["X-Household-ID"], "role": "viewer"}
    ]
