import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, ProductAlias, ShoppingListItem, StockBatch
from ..voice_schemas import VoiceAction, VoiceProductChoice

NUMBER_WORDS = {
    "ein": Decimal("1"),
    "eine": Decimal("1"),
    "einen": Decimal("1"),
    "eins": Decimal("1"),
    "zwei": Decimal("2"),
    "drei": Decimal("3"),
    "vier": Decimal("4"),
    "fünf": Decimal("5"),
    "sechs": Decimal("6"),
    "sieben": Decimal("7"),
    "acht": Decimal("8"),
    "neun": Decimal("9"),
    "zehn": Decimal("10"),
    "halb": Decimal("0.5"),
    "halbe": Decimal("0.5"),
    "halben": Decimal("0.5"),
}
UNITS = {
    "stück": "piece",
    "stueck": "piece",
    "packung": "pack",
    "packungen": "pack",
    "liter": "l",
    "l": "l",
    "milliliter": "ml",
    "ml": "ml",
    "kilo": "kg",
    "kilogramm": "kg",
    "kg": "kg",
    "gramm": "g",
    "g": "g",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\wäöüß,.]", " ", value).split())


def detect_intent(text: str) -> str:
    if any(word in text for word in ("wie viel", "wieviel", "haben wir", "ist noch", "vorrat von")):
        return "query_stock"
    if any(word in text for word in ("entsorg", "weggeworf", "wegwerfen", "schlecht geworden")):
        return "discard"
    if "einkauf" in text or "liste" in text:
        if any(word in text for word in ("streich", "entfern", "lösche", "loesche")):
            return "remove_from_shopping"
        if any(word in text for word in ("hak", "abhak", "erledigt")):
            return "check_shopping"
        return "add_to_shopping"
    if any(
        word in text
        for word in (
            "verbraucht",
            "verbrauche",
            "getrunken",
            "gegessen",
            "entnommen",
            "ist leer",
            "aufgebraucht",
        )
    ):
        return "consume"
    if any(
        word in text
        for word in (
            "gekauft",
            "zum vorrat",
            "in den vorrat",
            "zum bestand",
            "in den bestand",
            "eingelagert",
        )
    ):
        return "add_to_stock"
    return "unknown"


def _extract_quantity(tokens: list[str]) -> tuple[Decimal | None, str | None, list[str]]:
    quantity: Decimal | None = None
    unit: str | None = None
    keep: list[str] = []
    skip_next = False
    for index, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        if (
            quantity is None
            and token in {"ein", "eine", "einen"}
            and index + 1 < len(tokens)
            and tokens[index + 1].startswith("halb")
        ):
            quantity = Decimal("0.5")
            skip_next = True
            continue
        number = token.replace(",", ".")
        if quantity is None:
            if token in NUMBER_WORDS:
                quantity = NUMBER_WORDS[token]
                continue
            try:
                quantity = Decimal(number)
                continue
            except Exception:
                pass
        if unit is None and token in UNITS:
            unit = UNITS[token]
            continue
        keep.append(token)
    return quantity, unit, keep


def _clean_product(text: str) -> str:
    fillers = {
        "bitte",
        "ich",
        "habe",
        "hab",
        "wir",
        "noch",
        "auf",
        "die",
        "der",
        "das",
        "den",
        "dem",
        "meine",
        "meiner",
        "unser",
        "unsere",
        "ist",
        "sind",
        "mal",
        "mir",
        "davon",
        "gekauft",
        "verbraucht",
        "verbrauche",
        "getrunken",
        "gegessen",
        "entnommen",
        "leer",
        "aufgebraucht",
        "entsorgt",
        "weggeworfen",
        "schlecht",
        "geworden",
        "setz",
        "setze",
        "füge",
        "fuege",
        "hinzu",
        "streich",
        "streiche",
        "entferne",
        "lösche",
        "loesche",
        "hak",
        "hake",
        "abhaken",
        "erledigt",
        "wie",
        "viel",
        "wieviel",
        "haben",
        "vorrat",
        "bestand",
        "einkaufsliste",
        "einkauf",
        "liste",
        "von",
        "zum",
        "in",
        "aus",
    }
    return " ".join(token for token in text.split() if token not in fillers).strip(" ,.?")


def _product_candidates(
    db: Session, household_id: str, requested: str
) -> tuple[Product | None, list[VoiceProductChoice], float]:
    products = list(db.scalars(select(Product).where(Product.household_id == household_id)))
    aliases = list(
        db.execute(
            select(ProductAlias, Product)
            .join(Product, Product.id == ProductAlias.product_id)
            .where(ProductAlias.household_id == household_id, Product.household_id == household_id)
        )
    )
    scored: dict[str, tuple[float, Product]] = {}
    needle = normalize(requested)
    for product in products:
        name = normalize(product.name)
        score = 1.0 if needle == name else SequenceMatcher(None, needle, name).ratio()
        if needle and (needle in name or name in needle):
            score = max(score, 0.91)
        scored[product.id] = (score, product)
    for alias, product in aliases:
        score = (
            1.0
            if needle == alias.normalized_alias
            else SequenceMatcher(None, needle, alias.normalized_alias).ratio()
        )
        if score > scored.get(product.id, (0.0, product))[0]:
            scored[product.id] = (score, product)
    ranked = sorted(scored.values(), key=lambda value: value[0], reverse=True)
    choices = [
        VoiceProductChoice(id=product.id, name=product.name)
        for score, product in ranked[:3]
        if score >= 0.48
    ]
    if not ranked or ranked[0][0] < 0.72:
        return None, choices, ranked[0][0] if ranked else 0.0
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
        return None, choices, ranked[0][0]
    return ranked[0][1], choices, ranked[0][0]


def parse_voice_command(db: Session, household_id: str, text: str) -> list[VoiceAction]:
    normalized = normalize(text)
    intent = detect_intent(normalized)
    if intent == "unknown":
        return []
    core = normalized.replace(" und ", ",")
    chunks = [chunk.strip() for chunk in core.split(",") if chunk.strip()]
    actions: list[VoiceAction] = []
    for chunk in chunks:
        quantity, unit, remaining = _extract_quantity(chunk.split())
        product_name = _clean_product(" ".join(remaining))
        if not product_name:
            continue
        product, choices, match_confidence = _product_candidates(db, household_id, product_name)
        shopping_intent = intent in {"add_to_shopping", "remove_from_shopping", "check_shopping"}
        expected_versions: dict[str, int] = {}
        if product and intent in {"consume", "discard"}:
            batches = db.scalars(
                select(StockBatch).where(
                    StockBatch.household_id == household_id,
                    StockBatch.product_id == product.id,
                    StockBatch.quantity > 0,
                )
            )
            expected_versions = {batch.id: batch.version for batch in batches}
        confidence = min(0.98, 0.72 + (match_confidence * 0.25))
        if shopping_intent and product is None:
            confidence = 0.86
        if not shopping_intent and product is None:
            confidence = min(confidence, 0.55)
        actions.append(
            VoiceAction(
                intent=intent,
                product_id=product.id if product else None,
                product_name=product.name if product else product_name.title(),
                quantity=quantity,
                unit=unit or (product.default_unit if product else "piece"),
                confidence=confidence,
                choices=choices,
                expected_versions=expected_versions,
                requires_confirmation=True,
            )
        )
    return actions


def find_shopping_item(
    db: Session, household_id: str, product_id: str | None, product_name: str
) -> ShoppingListItem | None:
    statement = select(ShoppingListItem).where(
        ShoppingListItem.household_id == household_id,
        ShoppingListItem.status == "open",
    )
    if product_id:
        statement = statement.where(ShoppingListItem.product_id == product_id)
    else:
        statement = statement.where(ShoppingListItem.free_text.ilike(product_name))
    return db.scalar(statement.order_by(ShoppingListItem.created_at))
