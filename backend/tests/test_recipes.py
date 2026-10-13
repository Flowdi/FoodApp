from datetime import date, timedelta

from sqlalchemy import select

from backend.app.models import Membership, Role
from backend.app.schemas import RecipeRecommendation
from backend.app.services.recipe_rankers import RankedRecipe, apply_llm_ranking


async def create_recipe(client, auth):
    headers, _, milk = auth
    oats_response = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Haferflocken", "default_unit": "g", "barcodes": []},
    )
    oats = oats_response.json()
    response = await client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "name": "Porridge",
            "servings": 2,
            "instructions": "Alles aufkochen.",
            "tags": ["Frühstück", "Vegetarisch"],
            "ingredients": [
                {"product_id": milk["id"], "quantity": 0.5, "unit": "l"},
                {"product_id": oats["id"], "quantity": 100, "unit": "g"},
            ],
        },
    )
    return response, oats


async def test_recipe_crud_is_household_scoped(client, auth):
    response, _ = await create_recipe(client, auth)
    assert response.status_code == 201
    recipe = response.json()
    assert {item["product_name"] for item in recipe["ingredients"]} == {"Milch", "Haferflocken"}
    recipes = (await client.get("/api/v1/recipes", headers=auth[0])).json()
    assert [item["name"] for item in recipes] == ["Porridge"]
    updated = await client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        headers=auth[0],
        json={"servings": 4, "tags": ["Schnell"]},
    )
    assert updated.status_code == 200
    assert updated.json()["servings"] == 4


async def test_recommendations_use_inventory_expiry_and_units(client, auth):
    recipe_response, _ = await create_recipe(client, auth)
    recipe = recipe_response.json()
    purchase = await client.post(
        "/api/v1/stock/purchase",
        headers=auth[0],
        json={
            "product_id": auth[2]["id"],
            "location_id": auth[1]["id"],
            "quantity": 500,
            "unit": "ml",
            "best_before": (date.today() + timedelta(days=1)).isoformat(),
            "idempotency_key": "12121212-1212-4212-8212-121212121212",
        },
    )
    assert purchase.status_code == 201
    response = await client.get("/api/v1/recipes/recommendations?tags=Frühstück", headers=auth[0])
    assert response.status_code == 200
    recommendation = response.json()[0]
    assert recommendation["recipe"]["id"] == recipe["id"]
    assert recommendation["availability_score"] == 0.5
    assert recommendation["expiry_score"] > 0
    assert recommendation["preference_score"] == 1
    assert recommendation["missing_ingredients"][0]["product_name"] == "Haferflocken"


async def test_missing_ingredients_can_be_added_to_shopping_list(client, auth):
    recipe_response, _ = await create_recipe(client, auth)
    response = await client.post(
        f"/api/v1/recipes/{recipe_response.json()['id']}/shopping-list", headers=auth[0]
    )
    assert response.status_code == 204
    shopping = (await client.get("/api/v1/shopping-list", headers=auth[0])).json()
    assert {item["product_name"] for item in shopping} == {"Haferflocken", "Milch"}
    assert all(item["source"] == "recipe" for item in shopping)


async def test_viewer_can_read_but_not_create_recipes(client, auth):
    with client.session_factory() as db:
        membership = db.scalar(
            select(Membership).where(Membership.household_id == auth[0]["X-Household-ID"])
        )
        membership.role = Role.viewer
        db.commit()
    assert (await client.get("/api/v1/recipes", headers=auth[0])).status_code == 200
    response = await client.post(
        "/api/v1/recipes",
        headers=auth[0],
        json={
            "name": "Nicht erlaubt",
            "ingredients": [{"product_id": auth[2]["id"], "quantity": 1, "unit": "l"}],
        },
    )
    assert response.status_code == 403


async def test_recipe_preferences_filter_and_score_recommendations(client, auth):
    await create_recipe(client, auth)
    preferences = await client.put(
        "/api/v1/recipes/preferences",
        headers=auth[0],
        json={"preferred_tags": ["Frühstück"], "excluded_tags": []},
    )
    assert preferences.status_code == 200
    result = (await client.get("/api/v1/recipes/recommendations", headers=auth[0])).json()
    assert result[0]["preference_score"] == 1
    await client.put(
        "/api/v1/recipes/preferences",
        headers=auth[0],
        json={"preferred_tags": [], "excluded_tags": ["Vegetarisch"]},
    )
    excluded = await client.get("/api/v1/recipes/recommendations", headers=auth[0])
    assert excluded.json() == []


def test_llm_ranking_rejects_unknown_and_duplicate_recipe_ids() -> None:
    first = RecipeRecommendation.model_validate(
        {
            "recipe": {
                "id": "first",
                "name": "Erstes",
                "servings": 2,
                "instructions": None,
                "tags": [],
                "ingredients": [],
            },
            "score": 0.8,
            "availability_score": 1,
            "expiry_score": 0,
            "preference_score": 0,
            "missing_ingredients": [],
            "explanation": "deterministisch",
        }
    )
    second = first.model_copy(
        update={"recipe": first.recipe.model_copy(update={"id": "second", "name": "Zweites"})}
    )
    result = apply_llm_ranking(
        [first, second],
        [
            RankedRecipe("second", "KI-Begründung"),
            RankedRecipe("unknown", "Ignorieren"),
            RankedRecipe("second", "Duplikat"),
        ],
        "openai",
    )
    assert [item.recipe.id for item in result] == ["second", "first"]
    assert result[0].ranking_source == "openai"
    assert result[1].ranking_source == "deterministic"
