import asyncio

import httpx


async def purchase(
    client: httpx.AsyncClient,
    auth,
    key: str = "11111111-1111-4111-8111-111111111111",
) -> httpx.Response:
    headers, location, product = auth
    return await client.post(
        "/api/v1/stock/purchase",
        headers=headers,
        json={
            "product_id": product["id"],
            "location_id": location["id"],
            "quantity": 1,
            "unit": "l",
            "idempotency_key": key,
        },
    )


async def test_idempotent_purchase(client, auth):
    first = await purchase(client, auth)
    second = await purchase(client, auth)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["movement"]["id"] == second.json()["movement"]["id"]
    assert second.json()["replayed"] is True
    assert len((await client.get("/api/v1/movements", headers=auth[0])).json()) == 1


async def test_reversal_only_once(client, auth):
    result = (await purchase(client, auth)).json()
    movement_id = result["movement"]["id"]
    first = await client.post(
        f"/api/v1/movements/{movement_id}/reverse",
        headers=auth[0],
        json={
            "expected_version": result["batch"]["version"],
            "idempotency_key": "22222222-2222-4222-8222-222222222222",
        },
    )
    second = await client.post(
        f"/api/v1/movements/{movement_id}/reverse",
        headers=auth[0],
        json={
            "expected_version": first.json()["batch"]["version"],
            "idempotency_key": "33333333-3333-4333-8333-333333333333",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "already_reversed"


async def test_mutation_rejects_non_uuid_idempotency_key(client, auth):
    response = await purchase(client, auth, "not-a-uuid")
    assert response.status_code == 422


async def test_two_clients_cannot_consume_last_stock(client, auth):
    batch = (await purchase(client, auth)).json()["batch"]

    async def consume(key: str) -> httpx.Response:
        return await client.post(
            f"/api/v1/stock/{batch['id']}/consume",
            headers=auth[0],
            json={
                "quantity": 1,
                "expected_version": batch["version"],
                "idempotency_key": key,
            },
        )

    responses = await asyncio.gather(
        consume("44444444-4444-4444-8444-444444444444"),
        consume("55555555-5555-4555-8555-555555555555"),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]


async def test_non_member_cannot_read(client, auth):
    alien = dict(auth[0])
    alien["X-Household-ID"] = "00000000-0000-0000-0000-000000000000"
    assert (await client.get("/api/v1/products", headers=alien)).status_code == 403


async def test_fefo_consumes_earliest_batches_and_replays(client, auth):
    headers, location, product = auth

    async def dated_purchase(key: str, quantity: float, best_before: str):
        response = await client.post(
            "/api/v1/stock/purchase",
            headers=headers,
            json={
                "product_id": product["id"],
                "location_id": location["id"],
                "quantity": quantity,
                "unit": "l",
                "best_before": best_before,
                "idempotency_key": key,
            },
        )
        assert response.status_code == 201
        return response.json()["batch"]

    later = await dated_purchase("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 2, "2027-02-01")
    earlier = await dated_purchase("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", 1, "2027-01-01")
    payload = {
        "product_id": product["id"],
        "quantity": 2,
        "unit": "l",
        "expected_versions": {
            earlier["id"]: earlier["version"],
            later["id"]: later["version"],
        },
        "idempotency_key": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }
    first = await client.post("/api/v1/stock/consume-fefo", headers=headers, json=payload)
    assert first.status_code == 200
    assert [item["batch"]["id"] for item in first.json()] == [earlier["id"], later["id"]]
    assert [item["movement"]["quantity_delta"] for item in first.json()] == ["-1.000", "-1.000"]

    replay = await client.post("/api/v1/stock/consume-fefo", headers=headers, json=payload)
    assert replay.status_code == 200
    assert all(item["replayed"] for item in replay.json())
    assert [item["movement"]["id"] for item in replay.json()] == [
        item["movement"]["id"] for item in first.json()
    ]


async def test_fefo_rejects_stale_batch_version(client, auth):
    batch = (await purchase(client, auth)).json()["batch"]
    response = await client.post(
        "/api/v1/stock/consume-fefo",
        headers=auth[0],
        json={
            "product_id": auth[2]["id"],
            "quantity": 1,
            "unit": "l",
            "expected_versions": {batch["id"]: batch["version"] + 1},
            "idempotency_key": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "version_conflict"


async def test_fefo_discard_uses_discard_movements(client, auth):
    batch = (await purchase(client, auth)).json()["batch"]
    response = await client.post(
        "/api/v1/stock/discard-fefo",
        headers=auth[0],
        json={
            "product_id": auth[2]["id"],
            "quantity": 1,
            "unit": "l",
            "expected_versions": {batch["id"]: batch["version"]},
            "idempotency_key": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        },
    )
    assert response.status_code == 200
    assert response.json()[0]["movement"]["movement_type"] == "discard"
