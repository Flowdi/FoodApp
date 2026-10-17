from sqlalchemy import select

from backend.app.models import AuditLog, Membership, ProductLookupCache, Role


async def purchase(client, auth):
    headers, location, product = auth
    return await client.post(
        "/api/v1/stock/purchase",
        headers=headers,
        json={
            "product_id": product["id"],
            "location_id": location["id"],
            "quantity": 1,
            "unit": "package",
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
        json={"minimum_quantity": 2, "unit": "package", "active": True},
    )
    assert response.status_code == 200
    shopping = (await client.get("/api/v1/shopping-list", headers=auth[0])).json()
    assert shopping[0]["product_name"] == "Milch"
    assert shopping[0]["quantity"] == 2
    assert shopping[0]["source"] == "min_stock"


async def test_minimum_stock_uses_package_counts(client, auth):
    headers, location, product = auth
    await client.post(
        "/api/v1/stock/purchase",
        headers=headers,
        json={
            "product_id": product["id"],
            "location_id": location["id"],
            "quantity": 1,
            "unit": "package",
            "idempotency_key": "12121212-1212-4121-8121-121212121212",
        },
    )
    await client.put(
        f"/api/v1/products/{product['id']}/min-stock",
        headers=headers,
        json={"minimum_quantity": 2, "unit": "package", "active": True},
    )
    shopping = (await client.get("/api/v1/shopping-list", headers=headers)).json()
    assert shopping[0]["quantity"] == 1


async def test_inventory_confirmation_creates_adjustment(client, auth):
    batch = (await purchase(client, auth)).json()["batch"]
    inventory = (await client.post("/api/v1/inventory-sessions", headers=auth[0], json={})).json()
    assert inventory["counts"][0]["expected_quantity"] == 1
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
    replay = await client.post(
        f"/api/v1/inventory-sessions/{inventory['session']['id']}/confirm",
        headers=auth[0],
        json={"idempotency_key": "66666666-6666-4666-8666-666666666666"},
    )
    assert replay.status_code == 200
    assert replay.json()[0]["replayed"] is True
    assert replay.json()[0]["movement"]["id"] == confirmed.json()[0]["movement"]["id"]
    stock = (await client.get("/api/v1/stock", headers=auth[0])).json()
    assert stock == []


async def test_inventory_confirmation_rejects_changed_batch_atomically(client, auth):
    batch = (await purchase(client, auth)).json()["batch"]
    inventory = (await client.post("/api/v1/inventory-sessions", headers=auth[0], json={})).json()
    await client.put(
        f"/api/v1/inventory-sessions/{inventory['session']['id']}/counts",
        headers=auth[0],
        json={"batch_id": batch["id"], "counted_quantity": 0},
    )
    consumed = await client.post(
        f"/api/v1/stock/{batch['id']}/consume",
        headers=auth[0],
        json={
            "quantity": 1,
            "expected_version": batch["version"],
            "idempotency_key": "13131313-1313-4131-8131-131313131313",
        },
    )
    assert consumed.status_code == 200
    confirmed = await client.post(
        f"/api/v1/inventory-sessions/{inventory['session']['id']}/confirm",
        headers=auth[0],
        json={"idempotency_key": "14141414-1414-4141-8141-141414141414"},
    )
    assert confirmed.status_code == 409
    assert confirmed.json()["detail"]["code"] == "inventory_conflict"
    stock = (await client.get("/api/v1/stock", headers=auth[0])).json()
    assert stock == []


async def test_empty_inventory_confirmation_is_idempotent(client, auth):
    inventory = (await client.post("/api/v1/inventory-sessions", headers=auth[0], json={})).json()
    path = f"/api/v1/inventory-sessions/{inventory['session']['id']}/confirm"
    payload = {"idempotency_key": "15151515-1515-4151-8151-151515151515"}
    first = await client.post(path, headers=auth[0], json=payload)
    replay = await client.post(path, headers=auth[0], json=payload)
    conflict = await client.post(
        path,
        headers=auth[0],
        json={"idempotency_key": "16161616-1616-4161-8161-161616161616"},
    )
    assert first.json() == replay.json() == []
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "inventory_completed"


async def test_product_keeps_package_quantity(client, auth):
    response = await client.patch(
        f"/api/v1/products/{auth[2]['id']}",
        headers=auth[0],
        json={"package_quantity": "1 l"},
    )
    assert response.status_code == 200
    assert response.json()["package_quantity"] == "1 l"


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
    household_update = await client.patch(
        "/api/v1/households/current",
        headers=auth[0],
        json={"name": "Nicht erlaubt"},
    )
    assert household_update.status_code == 403


async def test_history_csv_contains_product(client, auth):
    await purchase(client, auth)
    response = await client.get("/api/v1/movements/export.csv", headers=auth[0])
    assert response.status_code == 200
    assert "Milch" in response.content.decode("utf-8-sig")


async def test_transfer_moves_the_single_product_row(client, auth):
    batch = (await purchase(client, auth)).json()["batch"]
    locations = (await client.get("/api/v1/locations", headers=auth[0])).json()
    target = next(item for item in locations if item["id"] != batch["location_id"])
    response = await client.post(
        "/api/v1/stock/transfer",
        headers=auth[0],
        json={
            "batch_id": batch["id"],
            "target_location_id": target["id"],
            "quantity": 1,
            "expected_version": batch["version"],
            "idempotency_key": "88888888-8888-4888-8888-888888888888",
        },
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert float(response.json()[0]["movement"]["quantity_delta"]) == 0
    assert response.json()[0]["batch"]["location_id"] == target["id"]
    replay = await client.post(
        "/api/v1/stock/transfer",
        headers=auth[0],
        json={
            "batch_id": batch["id"],
            "target_location_id": target["id"],
            "quantity": 1,
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


async def test_product_lookup_uses_household_cache(client, auth):
    with client.session_factory() as db:
        db.add(
            ProductLookupCache(
                household_id=auth[0]["X-Household-ID"],
                barcode="12345678",
                payload={
                    "barcode": "12345678",
                    "name": "Cached Product",
                    "brand": "Local",
                    "quantity": "1 Packung",
                    "image_url": None,
                    "found": True,
                },
            )
        )
        db.commit()
    response = await client.get("/api/v1/lookup/12345678", headers=auth[0])
    assert response.status_code == 200
    assert response.json()["name"] == "Cached Product"


async def test_notification_preferences_are_per_membership(client, auth):
    response = await client.put(
        "/api/v1/notifications/preferences",
        headers=auth[0],
        json={"channels": ["in_app", "email"]},
    )
    assert response.status_code == 200
    assert response.json() == {"channels": ["in_app", "email"]}
    current = await client.get("/api/v1/notifications/preferences", headers=auth[0])
    assert current.json() == {"channels": ["in_app", "email"]}
    invalid = await client.put(
        "/api/v1/notifications/preferences",
        headers=auth[0],
        json={"channels": ["sms"]},
    )
    assert invalid.status_code == 422


async def test_event_stream_requires_authentication(client):
    response = await client.get("/api/v1/events")
    assert response.status_code == 401
