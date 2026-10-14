from collections.abc import Sequence
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import generate_structured
from ..ai.speech import configured_speech
from ..database import get_db
from ..dependencies import HouseholdContext, household_context, require_writer
from ..models import MovementType, Product, ShoppingListItem, StockBatch, VoiceExecution
from ..schemas import MovementResult
from ..services.shopping import claim_open_item, create_purchase
from ..services.stock import consume_fefo
from ..services.voice import find_shopping_item, parse_voice_command
from ..voice_schemas import (
    LLMActions,
    VoiceExecuteRequest,
    VoiceExecuteResponse,
    VoiceInterpretRequest,
    VoiceInterpretResponse,
    VoicePreferences,
    VoiceTranscription,
)

router = APIRouter(prefix="/voice", tags=["voice"])


def _finish(
    db: Session,
    household_id: str,
    key: str,
    message: str,
    result_type: str,
    movements: Sequence[MovementResult] | None = None,
) -> VoiceExecuteResponse:
    response = VoiceExecuteResponse.model_validate(
        {"message": message, "result_type": result_type, "movements": movements or []}
    )
    db.add(
        VoiceExecution(
            household_id=household_id,
            idempotency_key=key,
            response=response.model_dump(mode="json"),
        )
    )
    db.commit()
    return response


def _scoped_product(db: Session, household_id: str, product_id: str | None) -> Product | None:
    if not product_id:
        return None
    product = db.scalar(
        select(Product).where(Product.id == product_id, Product.household_id == household_id)
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt nicht gefunden")
    return product


@router.get("/preferences", response_model=VoicePreferences)
def get_voice_preferences(
    context: HouseholdContext = Depends(household_context),
) -> VoicePreferences:
    return VoicePreferences.model_validate(context.membership.voice_preferences or {})


@router.put("/preferences", response_model=VoicePreferences)
def set_voice_preferences(
    payload: VoicePreferences,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> VoicePreferences:
    context.membership.voice_preferences = payload.model_dump()
    db.commit()
    return payload


@router.post("/transcribe", response_model=VoiceTranscription)
async def transcribe_audio(
    audio: UploadFile = File(),
    context: HouseholdContext = Depends(household_context),
) -> VoiceTranscription:
    del context
    content = await audio.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Audiodatei ist zu groß")
    speech = configured_speech()
    if speech is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "stt_unavailable", "message": "Spracherkennung ist nicht konfiguriert"},
        )
    text = speech.transcribe(
        content,
        audio.filename or "voice.webm",
        audio.content_type or "audio/webm",
    )
    if not text:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "speech_not_understood", "message": "Sprache wurde nicht erkannt"},
        )
    return VoiceTranscription(text=text)


@router.post("/interpret", response_model=VoiceInterpretResponse)
def interpret_voice(
    payload: VoiceInterpretRequest,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> VoiceInterpretResponse:
    household_id = context.membership.household_id
    actions = parse_voice_command(db, household_id, payload.text)
    if actions:
        return VoiceInterpretResponse(transcript=payload.text, actions=actions, parser="rules")
    products = list(
        db.scalars(
            select(Product).where(Product.household_id == household_id).order_by(Product.name)
        )
    )
    catalog = [
        {"id": product.id, "name": product.name, "unit": product.default_unit}
        for product in products
    ]
    prompt = (
        "Interpretiere den deutschen Sprachbefehl für eine Vorrats-App. Erlaubte Intents: "
        "add_to_stock, consume, discard, add_to_shopping, remove_from_shopping, "
        "check_shopping, query_stock. Bestandsaktionen dürfen nur Produkt-IDs aus dem Katalog "
        f"verwenden. Befehl: {payload.text!r}. Katalog: "
        f"{catalog}"
    )
    result = generate_structured(
        db,
        household_id=household_id,
        feature="voice_intent",
        prompt=prompt,
        response_model=LLMActions,
    )
    return VoiceInterpretResponse(transcript=payload.text, actions=result.actions, parser="llm")


@router.post("/execute", response_model=VoiceExecuteResponse)
def execute_voice(
    payload: VoiceExecuteRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> VoiceExecuteResponse:
    action = payload.action
    household_id = context.membership.household_id
    replay = db.scalar(
        select(VoiceExecution).where(
            VoiceExecution.household_id == household_id,
            VoiceExecution.idempotency_key == payload.idempotency_key,
        )
    )
    if replay:
        return VoiceExecuteResponse.model_validate(replay.response)
    product = _scoped_product(db, household_id, action.product_id)

    if action.intent == "add_to_shopping":
        item = db.scalar(
            select(ShoppingListItem).where(
                ShoppingListItem.household_id == household_id,
                ShoppingListItem.create_key == payload.idempotency_key,
            )
        )
        if item is None:
            item = ShoppingListItem(
                household_id=household_id,
                product_id=product.id if product else None,
                free_text=None if product else action.product_name,
                quantity=action.quantity or Decimal("1"),
                unit=action.unit or (product.default_unit if product else "piece"),
                source="voice",
                created_by_id=context.user.id,
                create_key=payload.idempotency_key,
            )
            db.add(item)
            db.flush()
        return _finish(
            db,
            household_id,
            payload.idempotency_key,
            f"{action.product_name} steht auf der Einkaufsliste",
            "shopping",
        )

    if action.intent in {"remove_from_shopping", "check_shopping"}:
        item = find_shopping_item(db, household_id, action.product_id, action.product_name)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Eintrag nicht auf der Einkaufsliste")
        if action.intent == "remove_from_shopping":
            item.status = "removed"
            item.version += 1
        else:
            claim_open_item(db, household_id, item.id, item.version, context.user.id)
        return _finish(
            db,
            household_id,
            payload.idempotency_key,
            f"{action.product_name} wurde auf der Einkaufsliste aktualisiert",
            "shopping",
        )

    if action.intent == "query_stock":
        if product is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bitte Produkt auswählen")
        batches = list(
            db.scalars(
                select(StockBatch).where(
                    StockBatch.household_id == household_id,
                    StockBatch.product_id == product.id,
                    StockBatch.quantity > 0,
                )
            )
        )
        totals: dict[str, Decimal] = {}
        for batch in batches:
            totals[batch.unit] = totals.get(batch.unit, Decimal("0")) + batch.quantity
        summary = ", ".join(f"{quantity:g} {unit}" for unit, quantity in totals.items()) or "nichts"
        return _finish(
            db,
            household_id,
            payload.idempotency_key,
            f"Von {product.name} sind {summary} vorhanden",
            "query",
        )

    if action.intent == "add_to_stock":
        if product is None or action.quantity is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Produkt und Menge sind erforderlich"
            )
        movement = create_purchase(
            db,
            household_id=household_id,
            product=product,
            quantity=action.quantity,
            unit=action.unit or product.default_unit,
            location_id=payload.location_id,
            best_before=None,
            user_id=context.user.id,
            idempotency_key=payload.idempotency_key,
            client_info="voice",
            note="Spracheingabe",
        )
        return _finish(
            db,
            household_id,
            payload.idempotency_key,
            f"{action.quantity:g} {action.unit or product.default_unit} {product.name} hinzugefügt",
            "stock",
            [movement],
        )

    if action.intent in {"consume", "discard"}:
        if product is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bitte Produkt auswählen")
        unit = action.unit or product.default_unit
        quantity = action.quantity
        if quantity is None:
            matching_batches = db.scalars(
                select(StockBatch).where(
                    StockBatch.household_id == household_id,
                    StockBatch.product_id == product.id,
                    StockBatch.unit == unit,
                    StockBatch.quantity > 0,
                )
            )
            quantity = sum((batch.quantity for batch in matching_batches), Decimal("0"))
        if quantity is None or quantity <= 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "Kein passender Bestand vorhanden")
        movements = consume_fefo(
            db,
            household_id=household_id,
            product_id=product.id,
            quantity=quantity,
            unit=unit,
            expected_versions=action.expected_versions,
            idempotency_key=payload.idempotency_key,
            user_id=context.user.id,
            note="Spracheingabe",
            client_info="voice",
            movement_type=(
                MovementType.discard if action.intent == "discard" else MovementType.consume
            ),
        )
        verb = "entsorgt" if action.intent == "discard" else "verbraucht"
        return _finish(
            db,
            household_id,
            payload.idempotency_key,
            f"{quantity:g} {unit} {product.name} {verb}",
            "stock",
            movements,
        )

    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unbekannte Sprachaktion")
