import argparse
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import (
    Membership,
    MinStockRule,
    MovementType,
    Product,
    ProductBarcode,
    ShoppingListItem,
    StockBatch,
    StorageLocation,
    User,
)
from .services.stock import apply_delta

DEMO_MARKER = "[demo-seed-v1]"
DEMO_NAMESPACE = uuid.UUID("15360639-784d-4edc-b565-e663f80c815a")

PRODUCT_GROUPS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Molkerei",
        "Kühlschrank",
        (
            ("Frische Vollmilch", "l"),
            ("Naturjoghurt", "g"),
            ("Butter", "g"),
            ("Gouda", "g"),
            ("Quark", "g"),
            ("Sahne", "ml"),
            ("Mozzarella", "package"),
            ("Feta", "g"),
            ("Eier", "piece"),
            ("Haferdrink", "l"),
        ),
    ),
    (
        "Obst",
        "Obstkorb",
        (
            ("Äpfel Elstar", "piece"),
            ("Bananen", "piece"),
            ("Birnen", "piece"),
            ("Orangen", "piece"),
            ("Zitronen", "piece"),
            ("Trauben", "g"),
            ("Erdbeeren", "g"),
            ("Heidelbeeren", "g"),
            ("Kiwi", "piece"),
            ("Avocado", "piece"),
        ),
    ),
    (
        "Gemüse",
        "Kühlschrank",
        (
            ("Tomaten", "g"),
            ("Salatgurke", "piece"),
            ("Paprika rot", "piece"),
            ("Zucchini", "piece"),
            ("Brokkoli", "piece"),
            ("Blumenkohl", "piece"),
            ("Karotten", "g"),
            ("Kartoffeln", "kg"),
            ("Zwiebeln", "kg"),
            ("Knoblauch", "piece"),
            ("Champignons", "g"),
            ("Feldsalat", "g"),
        ),
    ),
    (
        "Fleisch & Fisch",
        "Kühlschrank",
        (
            ("Hähnchenbrust", "g"),
            ("Rinderhack", "g"),
            ("Lachsfilet", "g"),
            ("Kochschinken", "g"),
            ("Salami", "g"),
            ("Tofu natur", "g"),
            ("Bratwürste", "package"),
            ("Räucherlachs", "g"),
        ),
    ),
    (
        "Brot & Backwaren",
        "Vorratsschrank",
        (
            ("Vollkornbrot", "package"),
            ("Toastbrot", "package"),
            ("Brötchen", "piece"),
            ("Knäckebrot", "package"),
            ("Tortilla-Wraps", "package"),
            ("Mehl Type 405", "g"),
            ("Trockenhefe", "package"),
        ),
    ),
    (
        "Nudeln, Reis & Getreide",
        "Vorratsschrank",
        (
            ("Spaghetti", "g"),
            ("Penne", "g"),
            ("Basmatireis", "kg"),
            ("Naturreis", "g"),
            ("Haferflocken", "g"),
            ("Couscous", "g"),
            ("Bulgur", "g"),
            ("Quinoa", "g"),
            ("Müsli", "g"),
            ("Linsen rot", "g"),
            ("Kichererbsen getrocknet", "g"),
            ("Paniermehl", "g"),
        ),
    ),
    (
        "Konserven",
        "Vorratsschrank",
        (
            ("Tomaten gehackt", "package"),
            ("Mais", "package"),
            ("Kidneybohnen", "package"),
            ("Kichererbsen Dose", "package"),
            ("Thunfisch", "package"),
            ("Kokosmilch", "ml"),
            ("Apfelmus", "g"),
            ("Erbsen und Möhren", "package"),
        ),
    ),
    (
        "Tiefkühl",
        "Gefrierschrank",
        (
            ("TK-Erbsen", "g"),
            ("TK-Spinat", "g"),
            ("Beerenmischung", "g"),
            ("Pommes frites", "g"),
            ("Gemüsemischung", "g"),
            ("Pizza Margherita", "piece"),
            ("Fischstäbchen", "package"),
            ("Vanilleeis", "ml"),
        ),
    ),
    (
        "Getränke",
        "Keller",
        (
            ("Mineralwasser", "l"),
            ("Apfelsaft", "l"),
            ("Orangensaft", "l"),
            ("Cola", "l"),
            ("Kräutertee", "package"),
            ("Kaffeebohnen", "g"),
            ("Pils alkoholfrei", "l"),
            ("Tonic Water", "l"),
        ),
    ),
    (
        "Gewürze & Öle",
        "Vorratsschrank",
        (
            ("Olivenöl", "ml"),
            ("Rapsöl", "ml"),
            ("Salz", "g"),
            ("Schwarzer Pfeffer", "g"),
            ("Paprikapulver", "g"),
            ("Currypulver", "g"),
            ("Balsamico", "ml"),
        ),
    ),
    (
        "Snacks",
        "Vorratsschrank",
        (
            ("Zartbitterschokolade", "g"),
            ("Kartoffelchips", "g"),
            ("Walnüsse", "g"),
            ("Gummibärchen", "g"),
            ("Butterkekse", "g"),
        ),
    ),
    (
        "Drogerie & Haushalt",
        "Badezimmer",
        (
            ("Zahnpasta", "piece"),
            ("Handseife", "ml"),
            ("Shampoo", "ml"),
            ("Spülmittel", "ml"),
            ("Küchenrolle", "package"),
        ),
    ),
)


def ean13(index: int) -> str:
    stem = f"2901234{index:05d}"
    checksum = (
        10
        - sum((3 if position % 2 else 1) * int(digit) for position, digit in enumerate(stem)) % 10
    ) % 10
    return f"{stem}{checksum}"


def initial_quantity(unit: str, index: int) -> Decimal:
    if unit == "kg":
        return Decimal("1.5") + Decimal(index % 3) / 2
    if unit in {"g", "ml"}:
        return Decimal(250 + (index % 4) * 250)
    if unit == "l":
        return Decimal(1 + index % 4)
    return Decimal(1 + index % 6)


def best_before(index: int, category: str) -> date | None:
    if category == "Drogerie & Haushalt" or index % 11 == 0:
        return None
    today = date.today()
    if index < 4:
        return today - timedelta(days=4 - index)
    if index < 12:
        return today + timedelta(days=3 + index % 5)
    return today + timedelta(days=14 + (index * 9) % 330)


def select_membership(db: Session, email: str, household_id: str | None) -> Membership:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        raise RuntimeError(f"Kein Benutzer mit der E-Mail-Adresse {email} gefunden.")
    statement = select(Membership).where(Membership.user_id == user.id)
    if household_id:
        statement = statement.where(Membership.household_id == household_id)
    membership = db.scalar(statement.order_by(Membership.household_id))
    if membership is None:
        raise RuntimeError("Der Benutzer gehört keinem passenden Haushalt an.")
    return membership


def seed_demo(db: Session, *, email: str, household_id: str | None = None) -> dict[str, int]:
    membership = select_membership(db, email, household_id)
    existing = list(
        db.scalars(
            select(Product).where(
                Product.household_id == membership.household_id,
                Product.notes == DEMO_MARKER,
            )
        )
    )
    if existing:
        if len(existing) != 100:
            raise RuntimeError("Unvollständige Demo-Daten gefunden; bitte manuell prüfen.")
        return {"products": 100, "created": 0}

    location_names = {group[1] for group in PRODUCT_GROUPS} | {"Keller"}
    locations = {
        location.name: location
        for location in db.scalars(
            select(StorageLocation).where(StorageLocation.household_id == membership.household_id)
        )
    }
    for name in sorted(location_names):
        if name not in locations:
            locations[name] = StorageLocation(household_id=membership.household_id, name=name)
            db.add(locations[name])
    db.flush()

    products: list[Product] = []
    for category, location_name, items in PRODUCT_GROUPS:
        for name, unit in items:
            index = len(products)
            product = Product(
                household_id=membership.household_id,
                name=name,
                brand=("Hausmarke", "Regional", "Bio Auswahl", "Vorrat Gut")[index % 4],
                category=category,
                default_unit="package",
                default_location_id=locations[location_name].id,
                package_quantity=f"{initial_quantity(unit, index)} {unit}",
                notes=DEMO_MARKER,
            )
            product.barcodes = [ProductBarcode(barcode=ean13(index + 1))]
            db.add(product)
            products.append(product)
    if len(products) != 100:
        raise AssertionError(f"Demo-Katalog enthält {len(products)} statt 100 Produkte")
    db.flush()

    batches: list[StockBatch] = []
    for index, product in enumerate(products):
        batch = StockBatch(
            household_id=membership.household_id,
            product_id=product.id,
            location_id=product.default_location_id,
            quantity=0,
            unit="package",
            best_before=best_before(index, product.category or ""),
        )
        db.add(batch)
        db.flush()
        apply_delta(
            db,
            household_id=membership.household_id,
            batch_id=batch.id,
            user_id=membership.user_id,
            movement_type=MovementType.purchase,
            delta=1 + index % 12,
            expected_version=1,
            idempotency_key=str(
                uuid.uuid5(DEMO_NAMESPACE, f"purchase:{membership.household_id}:{index}")
            ),
            note="Demo-Bestand eingebucht",
            client_info="demo-seed",
            commit=False,
        )
        batches.append(batch)

    for index, batch in enumerate(batches[:12]):
        amount = 1
        apply_delta(
            db,
            household_id=membership.household_id,
            batch_id=batch.id,
            user_id=membership.user_id,
            movement_type=MovementType.discard if index % 4 == 0 else MovementType.consume,
            delta=-amount,
            expected_version=batch.version,
            idempotency_key=str(
                uuid.uuid5(DEMO_NAMESPACE, f"out:{membership.household_id}:{index}")
            ),
            note="Demo-Verlauf",
            client_info="demo-seed",
            commit=False,
        )

    for product in products[:5]:
        available = sum(batch.quantity for batch in batches if batch.product_id == product.id)
        db.add(
            MinStockRule(
                household_id=membership.household_id,
                product_id=product.id,
                minimum_quantity=available + 2,
                unit="package",
            )
        )

    now = datetime.now(UTC)
    for index, product in enumerate(products[:10]):
        checked = index >= 7
        db.add(
            ShoppingListItem(
                household_id=membership.household_id,
                product_id=product.id,
                quantity=1,
                unit="package",
                note=DEMO_MARKER,
                source="manual",
                status="checked" if checked else "open",
                created_by_id=membership.user_id,
                checked_by_id=membership.user_id if checked else None,
                checked_at=now if checked else None,
                create_key=str(
                    uuid.uuid5(DEMO_NAMESPACE, f"shopping:{membership.household_id}:{index}")
                ),
            )
        )
    db.commit()
    return {"products": len(products), "batches": len(batches), "shopping_items": 10, "created": 1}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Realistische lokale Demo-Daten für Vorrat anlegen"
    )
    parser.add_argument(
        "--email", default="demo@example.com", help="E-Mail des vorhandenen Benutzers"
    )
    parser.add_argument("--household-id", help="Optionaler Zielhaushalt des Benutzers")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = seed_demo(db, email=args.email, household_id=args.household_id)
    if result["created"]:
        print(
            f"Demo-Daten angelegt: {result['products']} Produkte, "
            f"{result['batches']} Chargen, 10 Einkaufslisteneinträge."
        )
    else:
        print("Demo-Daten sind bereits vollständig vorhanden; es wurden keine Duplikate angelegt.")


if __name__ == "__main__":
    main()
