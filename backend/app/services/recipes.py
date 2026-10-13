from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from ..models import Recipe, RecipeIngredient, StockBatch
from ..schemas import (
    MissingIngredient,
    RecipeIngredientRead,
    RecipeRead,
    RecipeRecommendation,
)
from ..units import convert_quantity


def recipe_read(recipe: Recipe) -> RecipeRead:
    return RecipeRead(
        id=recipe.id,
        name=recipe.name,
        servings=recipe.servings,
        instructions=recipe.instructions,
        tags=recipe.tags,
        ingredients=[
            RecipeIngredientRead(
                id=ingredient.id,
                product_id=ingredient.product_id,
                product_name=ingredient.product.name,
                quantity=ingredient.quantity,
                unit=ingredient.unit,
            )
            for ingredient in recipe.ingredients
        ],
    )


def recipe_query(household_id: str) -> Select[tuple[Recipe]]:
    return (
        select(Recipe)
        .options(selectinload(Recipe.ingredients).selectinload(RecipeIngredient.product))
        .where(Recipe.household_id == household_id)
    )


def recommend_recipes(
    db: Session,
    household_id: str,
    preferred_tags: set[str],
    excluded_tags: set[str],
    servings: int | None,
    expiry_warning_days: int,
) -> list[RecipeRecommendation]:
    recipes = list(db.scalars(recipe_query(household_id).order_by(Recipe.name)))
    batches = list(
        db.scalars(
            select(StockBatch).where(
                StockBatch.household_id == household_id, StockBatch.quantity > 0
            )
        )
    )
    by_product: dict[str, list[StockBatch]] = defaultdict(list)
    for batch in batches:
        by_product[batch.product_id].append(batch)

    recommendations: list[RecipeRecommendation] = []
    today = date.today()
    for recipe in recipes:
        normalized_tags = {tag.casefold() for tag in recipe.tags}
        if normalized_tags & excluded_tags:
            continue
        scale = Decimal(servings or recipe.servings) / Decimal(recipe.servings)
        ingredient_ratios: list[Decimal] = []
        expiry_values: list[float] = []
        missing: list[MissingIngredient] = []
        for ingredient in recipe.ingredients:
            required = ingredient.quantity * scale
            available = Decimal("0")
            for batch in by_product[ingredient.product_id]:
                try:
                    converted = convert_quantity(batch.quantity, batch.unit, ingredient.unit)
                except ValueError:
                    continue
                available += converted
                if batch.best_before and expiry_warning_days > 0:
                    days_left = (batch.best_before - today).days
                    if days_left <= expiry_warning_days:
                        expiry_values.append(
                            max(0.0, min(1.0, 1 - days_left / expiry_warning_days))
                        )
            ingredient_ratios.append(min(Decimal("1"), available / required))
            if available < required:
                missing.append(
                    MissingIngredient(
                        product_id=ingredient.product_id,
                        product_name=ingredient.product.name,
                        required_quantity=required,
                        available_quantity=available,
                        missing_quantity=required - available,
                        unit=ingredient.unit,
                    )
                )

        availability = float(sum(ingredient_ratios) / len(ingredient_ratios))
        expiry = max(expiry_values, default=0.0)
        preference = (
            len(normalized_tags & preferred_tags) / len(preferred_tags) if preferred_tags else 0.0
        )
        score = round(availability * 0.6 + expiry * 0.25 + preference * 0.15, 4)
        available_count = len(recipe.ingredients) - len(missing)
        explanation = (
            f"{available_count} von {len(recipe.ingredients)} Zutaten vollständig vorrätig"
        )
        if expiry > 0:
            explanation += "; nutzt bald fällige Vorräte"
        if preference > 0:
            explanation += "; passt zu deinen Tags"
        recommendations.append(
            RecipeRecommendation(
                recipe=recipe_read(recipe),
                score=score,
                availability_score=round(availability, 4),
                expiry_score=round(expiry, 4),
                preference_score=round(preference, 4),
                missing_ingredients=missing,
                explanation=explanation,
            )
        )
    return sorted(recommendations, key=lambda item: (-item.score, item.recipe.name.casefold()))
