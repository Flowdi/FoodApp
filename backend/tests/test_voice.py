import json
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

from backend.app.models import Household, Membership, Product, ProductAlias, Role

COMMANDS = json.loads(
    (Path(__file__).parent / "fixtures" / "voice_commands.json").read_text(encoding="utf-8")
)


async def test_german_voice_fixture(
    client: httpx.AsyncClient, auth: tuple[dict[str, str], dict, dict]
) -> None:
    headers, _, _ = auth
    for text, intent in COMMANDS:
        response = await client.post(
            "/api/v1/voice/interpret", headers=headers, json={"text": text}
        )
        assert response.status_code == 200, (text, response.text)
        assert response.json()["parser"] == "rules", text
        assert response.json()["actions"][0]["intent"] == intent, text


async def test_confirmed_voice_actions_are_idempotent(
    client: httpx.AsyncClient, auth: tuple[dict[str, str], dict, dict]
) -> None:
    headers, location, product = auth
    draft = (
        await client.post(
            "/api/v1/voice/interpret",
            headers=headers,
            json={"text": "Ich habe zwei Liter Milch gekauft"},
        )
    ).json()["actions"][0]
    key = str(uuid.uuid4())
    body = {"action": draft, "idempotency_key": key, "location_id": location["id"]}
    first = await client.post("/api/v1/voice/execute", headers=headers, json=body)
    second = await client.post("/api/v1/voice/execute", headers=headers, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(first.json()["movements"]) == 1
    assert first.json()["movements"][0]["movement"]["client_info"] == "voice"

    stock = await client.get("/api/v1/stock", headers=headers)
    batches = [item for item in stock.json() if item["product_id"] == product["id"]]
    assert sum(float(item["quantity"]) for item in batches) == 2


async def test_voice_stock_response_can_be_reversed(
    client: httpx.AsyncClient, auth: tuple[dict[str, str], dict, dict]
) -> None:
    headers, location, product = auth
    response = await client.post(
        "/api/v1/voice/execute",
        headers=headers,
        json={
            "action": {
                "intent": "add_to_stock",
                "product_id": product["id"],
                "product_name": product["name"],
                "quantity": 1,
                "unit": "l",
                "confidence": 1,
            },
            "location_id": location["id"],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    movement = response.json()["movements"][0]
    reversed_response = await client.post(
        f"/api/v1/movements/{movement['movement']['id']}/reverse",
        headers=headers,
        json={
            "expected_version": movement["batch"]["version"],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert reversed_response.status_code == 200
    assert (await client.get("/api/v1/stock", headers=headers)).json() == []


async def test_voice_shopping_free_text_and_query(
    client: httpx.AsyncClient, auth: tuple[dict[str, str], dict, dict]
) -> None:
    headers, _, _ = auth
    draft = (
        await client.post(
            "/api/v1/voice/interpret",
            headers=headers,
            json={"text": "Setze zwei Mangos auf die Einkaufsliste"},
        )
    ).json()["actions"][0]
    response = await client.post(
        "/api/v1/voice/execute",
        headers=headers,
        json={"action": draft, "idempotency_key": str(uuid.uuid4())},
    )
    assert response.status_code == 200
    shopping = await client.get("/api/v1/shopping-list", headers=headers)
    assert any(item["source"] == "voice" for item in shopping.json())


async def test_audio_is_rejected_when_stt_is_not_configured(
    client: httpx.AsyncClient, auth: tuple[dict[str, str], dict, dict]
) -> None:
    headers, _, _ = auth
    response = await client.post(
        "/api/v1/voice/transcribe",
        headers=headers,
        files={"audio": ("voice.webm", b"audio", "audio/webm")},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "stt_unavailable"


async def test_alias_fraction_tenant_boundary_and_role_check(
    client: httpx.AsyncClient, auth: tuple[dict[str, str], dict, dict]
) -> None:
    headers, _, milk = auth
    household_id = headers["X-Household-ID"]
    with client.session_factory() as db:
        apples = Product(household_id=household_id, name="Äpfel", default_unit="kg")
        db.add(apples)
        db.flush()
        db.add(
            ProductAlias(
                household_id=household_id,
                product_id=milk["id"],
                alias="Kuh",
                normalized_alias="kuh",
                source="voice",
            )
        )
        other_household = Household(name="Fremd")
        db.add(other_household)
        db.flush()
        foreign_product = Product(
            household_id=other_household.id, name="Geheim", default_unit="piece"
        )
        db.add(foreign_product)
        db.commit()
        foreign_product_id = foreign_product.id

    alias = await client.post(
        "/api/v1/voice/interpret", headers=headers, json={"text": "Die Kuh ist leer"}
    )
    assert alias.json()["actions"][0]["product_id"] == milk["id"]
    fraction = await client.post(
        "/api/v1/voice/interpret",
        headers=headers,
        json={"text": "Ein halbes Kilo Äpfel verbraucht"},
    )
    assert fraction.json()["actions"][0]["quantity"] == "0.5"
    preferences = await client.put(
        "/api/v1/voice/preferences",
        headers=headers,
        json={
            "auto_confirm_shopping": True,
            "speech_output": True,
            "start_listening_on_launch": True,
        },
    )
    assert preferences.json() == {
        "auto_confirm_shopping": True,
        "speech_output": True,
        "start_listening_on_launch": True,
    }

    forged = await client.post(
        "/api/v1/voice/execute",
        headers=headers,
        json={
            "action": {
                "intent": "query_stock",
                "product_id": foreign_product_id,
                "product_name": "Geheim",
                "confidence": 1,
            },
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert forged.status_code == 404

    with client.session_factory() as db:
        membership = db.scalar(select(Membership).where(Membership.household_id == household_id))
        assert membership is not None
        membership.role = Role.viewer
        db.commit()
    forbidden = await client.post(
        "/api/v1/voice/execute",
        headers=headers,
        json={
            "action": {
                "intent": "add_to_shopping",
                "product_name": "Bananen",
                "quantity": "2",
                "unit": "piece",
                "confidence": 0.9,
            },
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert forbidden.status_code == 403
