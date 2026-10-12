import os
from collections.abc import AsyncIterator

os.environ.setdefault("DATABASE_URL", "sqlite:///./test-vorrat.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough")

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if test_database_url:
        engine = create_engine(test_database_url)
    else:
        engine = create_engine(
            f"sqlite:///{tmp_path / 'test.db'}",
            connect_args={"check_same_thread": False},
        )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    async def override_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        test_client.session_factory = testing_session
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture
async def auth(client: httpx.AsyncClient):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": "strong-password",
            "household_name": "Test",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    boot = (
        await client.get(
            "/api/v1/auth/bootstrap",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Household-ID": boot["memberships"][0]["household_id"],
    }
    locations = (await client.get("/api/v1/locations", headers=headers)).json()
    product = (
        await client.post(
            "/api/v1/products",
            headers=headers,
            json={
                "name": "Milch",
                "default_unit": "l",
                "barcodes": ["4000000000016"],
            },
        )
    ).json()
    return headers, locations[0], product
