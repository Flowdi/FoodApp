import asyncio

from sqlalchemy import select

from backend.app.models import Membership, Role, StockMovement


async def create_item(client, auth, key="21212121-2121-4121-8121-212121212121"):
    return await client.post(
        "/api/v1/shopping-list",
        headers=auth[0],
        json={
            "product_id": auth[2]["id"],
            "quantity": 2,
            "unit": "l",
            "note": "Für das Wochenende",
            "source": "manual",
            "idempotency_key": key,
        },
    )


async def test_create_item_is_idempotent(client, auth):
    first = await create_item(client, auth)
    replay = await create_item(client, auth)
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert len((await client.get("/api/v1/shopping-list", headers=auth[0])).json()) == 1


async def test_two_clients_can_only_check_once(client, auth):
    item = (await create_item(client, auth)).json()

    async def check(key: str):
        return await client.post(
            f"/api/v1/shopping-list/{item['id']}/check",
            headers=auth[0],
            json={
                "expected_version": item["version"],
                "idempotency_key": key,
                "client_info": "shopping-test",
            },
        )

    responses = await asyncio.gather(
        check("22222222-2222-4222-8222-222222222221"),
        check("22222222-2222-4222-8222-222222222222"),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["detail"]["code"] == "shopping_item_conflict"
    with client.session_factory() as db:
        purchases = list(
            db.scalars(
                select(StockMovement).where(StockMovement.household_id == auth[0]["X-Household-ID"])
            )
        )
        assert len(purchases) == 1


async def test_instant_check_can_be_undone(client, auth):
    item = (await create_item(client, auth)).json()
    path = f"/api/v1/shopping-list/{item['id']}/check"
    payload = {
        "expected_version": item["version"],
        "idempotency_key": "23232323-2323-4232-8232-232323232323",
    }
    checked = (await client.post(path, headers=auth[0], json=payload)).json()
    replay = (await client.post(path, headers=auth[0], json=payload)).json()
    assert replay["movement"]["replayed"] is True
    assert replay["movement"]["movement"]["id"] == checked["movement"]["movement"]["id"]
    undone = await client.post(
        f"/api/v1/shopping-list/{item['id']}/undo",
        headers=auth[0],
        json={
            "expected_version": checked["item"]["version"],
            "expected_batch_version": checked["movement"]["batch"]["version"],
            "idempotency_key": "24242424-2424-4242-8242-242424242424",
        },
    )
    assert undone.status_code == 200
    assert undone.json()["item"]["status"] == "open"
    assert undone.json()["movement"]["movement"]["movement_type"] == "reversal"
    assert (await client.get("/api/v1/stock", headers=auth[0])).json() == []


async def test_minimum_item_is_added_and_removed_after_restock(client, auth):
    await client.put(
        f"/api/v1/products/{auth[2]['id']}/min-stock",
        headers=auth[0],
        json={"minimum_quantity": 2, "unit": "l", "active": True},
    )
    first = (await client.get("/api/v1/shopping-list", headers=auth[0])).json()
    assert len(first) == 1
    assert first[0]["source"] == "min_stock"
    await client.post(
        "/api/v1/stock/purchase",
        headers=auth[0],
        json={
            "product_id": auth[2]["id"],
            "location_id": auth[1]["id"],
            "quantity": 2,
            "unit": "l",
            "idempotency_key": "25252525-2525-4252-8252-252525252525",
        },
    )
    assert (await client.get("/api/v1/shopping-list", headers=auth[0])).json() == []


async def test_finish_trip_books_checked_items(client, auth):
    mode = await client.patch(
        "/api/v1/households/current",
        headers=auth[0],
        json={"shopping_check_mode": "finish_trip"},
    )
    assert mode.status_code == 200
    item = (await create_item(client, auth)).json()
    checked = (
        await client.post(
            f"/api/v1/shopping-list/{item['id']}/check",
            headers=auth[0],
            json={
                "expected_version": item["version"],
                "idempotency_key": "26262626-2626-4262-8262-262626262626",
                "book_to_stock": False,
            },
        )
    ).json()["item"]
    assert (await client.get("/api/v1/stock", headers=auth[0])).json() == []
    payload = {
        "lines": [
            {
                "item_id": item["id"],
                "expected_version": checked["version"],
                "location_id": auth[1]["id"],
                "idempotency_key": "27272727-2727-4272-8272-272727272727",
            }
        ]
    }
    finished = await client.post("/api/v1/shopping-list/finish", headers=auth[0], json=payload)
    replay = await client.post("/api/v1/shopping-list/finish", headers=auth[0], json=payload)
    assert finished.status_code == replay.status_code == 200
    assert (
        finished.json()[0]["movement"]["movement"]["id"]
        == replay.json()[0]["movement"]["movement"]["id"]
    )
    assert replay.json()[0]["movement"]["replayed"] is True


async def test_viewer_cannot_change_shopping_list(client, auth):
    with client.session_factory() as db:
        membership = db.scalar(
            select(Membership).where(Membership.household_id == auth[0]["X-Household-ID"])
        )
        membership.role = Role.viewer
        db.commit()
    assert (await create_item(client, auth)).status_code == 403
