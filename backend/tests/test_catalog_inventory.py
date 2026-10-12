from sqlalchemy import select

from backend.app.models import AuditLog, Membership, Role


async def purchase(client, auth):
    headers, location, product = auth
    return await client.post(
        "/api/v1/stock/purchase",
        headers=headers,
        json={
            "product_id": product["id"],
            "location_id": location["id"],
            "quantity": 1,
            "unit": "l",
            "idempotency_key": "77777777-7777-4777-8777-777777777777",
        },
    )


async def test_product_update_creates_audit_log(client, auth):
    product = auth[2]
    response = await client.patch(
        f"/api/v1/products/{product['id']}",
        headers=auth[0],
        json={"name": "Hafermilch", "barcodes": ["4000000000016", "4000000000023"]},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Hafermilch"
    with client.session_factory() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.entity_id == product["id"]))
        assert audit is not None
        assert audit.changes["name"]["to"] == "Hafermilch"


async def test_minimum_stock_generates_shopping_list(client, auth):
    product = auth[2]
    response = await client.put(
        f"/api/v1/products/{product['id']}/min-stock",
        headers=auth[0],
        json={"minimum_quantity": 2, "unit": "l", "active": True},
    )
    assert response.status_code == 200
    shopping = (await client.get("/api/v1/shopping-list", headers=auth[0])).json()
    assert shopping[0]["product_name"] == "Milch"
    assert shopping[0]["missing_quantity"] == "2.000"


async def test_inventory_confirmation_creates_adjustment(client, auth):
    batch = (await purchase(client, auth)).json()["batch"]
    inventory = (await client.post("/api/v1/inventory-sessions", headers=auth[0], json={})).json()
    assert inventory["counts"][0]["expected_quantity"] == "1.000"
    await client.put(
        f"/api/v1/inventory-sessions/{inventory['session']['id']}/counts",
        headers=auth[0],
        json={"batch_id": batch["id"], "counted_quantity": 0},
    )
    confirmed = await client.post(
        f"/api/v1/inventory-sessions/{inventory['session']['id']}/confirm",
        headers=auth[0],
        json={"idempotency_key": "66666666-6666-4666-8666-666666666666"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()[0]["movement"]["movement_type"] == "adjust"
    stock = (await client.get("/api/v1/stock", headers=auth[0])).json()
    assert stock == []


async def test_viewer_cannot_modify_catalog(client, auth):
    with client.session_factory() as db:
        membership = db.scalar(
            select(Membership).where(Membership.household_id == auth[0]["X-Household-ID"])
        )
        membership.role = Role.viewer
        db.commit()
    response = await client.patch(
        f"/api/v1/products/{auth[2]['id']}",
        headers=auth[0],
        json={"name": "Nicht erlaubt"},
    )
    assert response.status_code == 403


async def test_history_csv_contains_product(client, auth):
    await purchase(client, auth)
    response = await client.get("/api/v1/movements/export.csv", headers=auth[0])
    assert response.status_code == 200
    assert "Milch" in response.content.decode("utf-8-sig")


async def test_transfer_creates_balanced_movements(client, auth):
    batch = (await purchase(client, auth)).json()["batch"]
    locations = (await client.get("/api/v1/locations", headers=auth[0])).json()
    target = next(item for item in locations if item["id"] != batch["location_id"])
    response = await client.post(
        "/api/v1/stock/transfer",
        headers=auth[0],
        json={
            "batch_id": batch["id"],
            "target_location_id": target["id"],
            "quantity": 0.4,
            "expected_version": batch["version"],
            "idempotency_key": "88888888-8888-4888-8888-888888888888",
        },
    )
    assert response.status_code == 200
    deltas = sorted(float(item["movement"]["quantity_delta"]) for item in response.json())
    assert deltas == [-0.4, 0.4]
    replay = await client.post(
        "/api/v1/stock/transfer",
        headers=auth[0],
        json={
            "batch_id": batch["id"],
            "target_location_id": target["id"],
            "quantity": 0.4,
            "expected_version": batch["version"],
            "idempotency_key": "88888888-8888-4888-8888-888888888888",
        },
    )
    assert replay.status_code == 200
    assert all(item["replayed"] for item in replay.json())


async def test_low_stock_notification_is_debounced_and_resolved(client, auth):
    product = auth[2]
    await client.put(
        f"/api/v1/products/{product['id']}/min-stock",
        headers=auth[0],
        json={"minimum_quantity": 1, "unit": "l", "active": True},
    )
    first = await client.post("/api/v1/notifications/check", headers=auth[0])
    second = await client.post("/api/v1/notifications/check", headers=auth[0])
    assert first.json() == {"created": 1}
    assert second.json() == {"created": 0}
    await purchase(client, auth)
    await client.post("/api/v1/notifications/check", headers=auth[0])
    notifications = (await client.get("/api/v1/notifications", headers=auth[0])).json()
    assert len(notifications) == 1
    assert notifications[0]["resolved_at"] is not None
