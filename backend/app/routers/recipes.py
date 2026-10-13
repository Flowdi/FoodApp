from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import HouseholdContext, household_context, require_writer
from ..models import (
    AuditLog,
    Household,
    Product,
    Recipe,
    RecipeIngredient,
    ShoppingListEntry,
)
from ..schemas import (
    RecipeCreate,
    RecipeIngredientWrite,
    RecipeRead,
    RecipeRecommendation,
    RecipeUpdate,
)
from ..services.recipes import recipe_query, recipe_read, recommend_recipes

router = APIRouter(prefix="/recipes", tags=["recipes"])


def load_recipe(db: Session, household_id: str, recipe_id: str) -> Recipe:
    recipe = db.scalar(recipe_query(household_id).where(Recipe.id == recipe_id))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rezept nicht gefunden")
    return recipe


def validated_ingredients(
    db: Session, household_id: str, ingredients: Sequence[RecipeIngredientWrite]
) -> list[RecipeIngredient]:
    product_ids = [item.product_id for item in ingredients]
    if len(product_ids) != len(set(product_ids)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ein Produkt darf pro Rezept nur einmal vorkommen",
        )
    products = set(
        db.scalars(
            select(Product.id).where(
                Product.household_id == household_id, Product.id.in_(product_ids)
            )
        )
    )
    if products != set(product_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zutat nicht gefunden")
    return [
        RecipeIngredient(
            product_id=item.product_id,
            quantity=item.quantity,
            unit=item.unit,
        )
        for item in ingredients
    ]


@router.get("", response_model=list[RecipeRead])
def list_recipes(
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> list[RecipeRead]:
    recipes = db.scalars(recipe_query(context.membership.household_id).order_by(Recipe.name))
    return [recipe_read(recipe) for recipe in recipes]


@router.post("", response_model=RecipeRead, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeCreate,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> RecipeRead:
    household_id = context.membership.household_id
    recipe = Recipe(
        household_id=household_id,
        name=payload.name,
        servings=payload.servings,
        instructions=payload.instructions,
        tags=sorted(set(payload.tags)),
        ingredients=validated_ingredients(db, household_id, payload.ingredients),
    )
    db.add(recipe)
    db.flush()
    db.add(
        AuditLog(
            household_id=household_id,
            user_id=context.user.id,
            entity_type="recipe",
            entity_id=recipe.id,
            action="create",
            changes={"name": recipe.name},
        )
    )
    db.commit()
    return recipe_read(load_recipe(db, household_id, recipe.id))


@router.get("/recommendations", response_model=list[RecipeRecommendation])
def recommendations(
    tags: list[str] = Query(default=[]),
    servings: int | None = Query(default=None, ge=1, le=100),
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> list[RecipeRecommendation]:
    household_id = context.membership.household_id
    household = db.get(Household, household_id)
    warning_days = household.expiry_warning_days if household else 3
    return recommend_recipes(
        db,
        household_id,
        {tag.casefold() for tag in tags},
        servings,
        warning_days,
    )


@router.get("/{recipe_id}", response_model=RecipeRead)
def get_recipe(
    recipe_id: str,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> RecipeRead:
    return recipe_read(load_recipe(db, context.membership.household_id, recipe_id))


@router.patch("/{recipe_id}", response_model=RecipeRead)
def update_recipe(
    recipe_id: str,
    payload: RecipeUpdate,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> RecipeRead:
    household_id = context.membership.household_id
    recipe = load_recipe(db, household_id, recipe_id)
    changes: dict[str, object] = {}
    for field in ("name", "servings", "instructions", "tags"):
        if field not in payload.model_fields_set:
            continue
        value = getattr(payload, field)
        if field == "tags" and value is not None:
            value = sorted(set(value))
        if getattr(recipe, field) != value:
            changes[field] = {"from": getattr(recipe, field), "to": value}
            setattr(recipe, field, value)
    if payload.ingredients is not None:
        recipe.ingredients = validated_ingredients(db, household_id, payload.ingredients)
        changes["ingredients"] = "updated"
    if changes:
        db.add(
            AuditLog(
                household_id=household_id,
                user_id=context.user.id,
                entity_type="recipe",
                entity_id=recipe.id,
                action="update",
                changes=changes,
            )
        )
        db.commit()
    return recipe_read(load_recipe(db, household_id, recipe.id))


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    recipe_id: str,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> None:
    household_id = context.membership.household_id
    recipe = load_recipe(db, household_id, recipe_id)
    db.add(
        AuditLog(
            household_id=household_id,
            user_id=context.user.id,
            entity_type="recipe",
            entity_id=recipe.id,
            action="delete",
            changes={"name": recipe.name},
        )
    )
    db.delete(recipe)
    db.commit()


@router.post("/{recipe_id}/shopping-list", status_code=status.HTTP_204_NO_CONTENT)
def add_missing_to_shopping_list(
    recipe_id: str,
    servings: int | None = Query(default=None, ge=1, le=100),
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> None:
    household_id = context.membership.household_id
    recipe = load_recipe(db, household_id, recipe_id)
    household = db.get(Household, household_id)
    recommendation = recommend_recipes(
        db,
        household_id,
        set(),
        servings,
        household.expiry_warning_days if household else 3,
    )
    selected = next(item for item in recommendation if item.recipe.id == recipe.id)
    db.execute(
        delete(ShoppingListEntry).where(
            ShoppingListEntry.household_id == household_id,
            ShoppingListEntry.recipe_id == recipe.id,
        )
    )
    db.add_all(
        [
            ShoppingListEntry(
                household_id=household_id,
                product_id=item.product_id,
                recipe_id=recipe.id,
                quantity=item.missing_quantity,
                unit=item.unit,
            )
            for item in selected.missing_ingredients
        ]
    )
    db.commit()
