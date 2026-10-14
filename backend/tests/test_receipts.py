import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.models import (
    Membership,
    Product,
    ProductAlias,
    Receipt,
    Role,
    StockMovement,
)
from backend.app.receipt_schemas import ExtractedReceipt
from backend.app.services.receipts import apply_extraction, learn_alias, parse_receipt_text

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "receipts.json").read_text(encoding="utf-8")
)


def add_receipt(db, auth, *, image_hash="a" * 64) -> Receipt:
    membership = db.scalar(
        select(Membership).where(Membership.household_id == auth[0]["X-Household-ID"])
    )
    assert membership is not None
    receipt = Receipt(
        household_id=membership.household_id,
        uploaded_by_id=membership.user_id,
        image_hash=image_hash,
        image_paths=[],
        status="processing",
    )
    db.add(receipt)
    db.commit()
    return receipt


@pytest.mark.parametrize("fixture", FIXTURES, ids=[item["name"] for item in FIXTURES])
async def test_five_receipt_formats_create_review_lines(client, auth, fixture) -> None:
    extracted = ExtractedReceipt.model_validate(fixture)
    with client.session_factory() as db:
        receipt = add_receipt(db, auth, image_hash=fixture["name"].ljust(64, "0"))
        apply_extraction(
            db,
            receipt,
            extracted,
            Settings(receipt_shopping_dedup_hours=12),
        )
        assert receipt.status == "review"
        assert len(receipt.lines) == len(fixture["lines"])
        for source, line in zip(fixture["lines"], receipt.lines, strict=True):
            if source["line_kind"] != "food":
                assert line.status == "ignored"


async def test_receipt_alias_is_learned_and_reused(client, auth) -> None:
    with client.session_factory() as db:
        product = db.get(Product, auth[2]["id"])
        assert product is not None
        learn_alias(db, auth[0]["X-Household-ID"], product.id, "H-MILCH 3,5% 1L")
        db.commit()
        receipt = add_receipt(db, auth, image_hash="b" * 64)
        apply_extraction(
            db,
            receipt,
            ExtractedReceipt.model_validate(
                {
                    "merchant": "Markt",
                    "purchased_at": "2026-10-12T18:20:00Z",
                    "total": "1.29",
                    "lines": [{"raw_text": "H-MILCH 3,5% 1L", "total_price": "1.29"}],
                }
            ),
            Settings(),
        )
        assert receipt.lines[0].product_id == product.id
        assert receipt.lines[0].status == "mapped"
        alias = db.scalar(select(ProductAlias).where(ProductAlias.product_id == product.id))
        assert alias is not None and alias.usage_count == 2


async def test_rule_parser_recognizes_weight_deposit_and_discount() -> None:
    parsed = parse_receipt_text(
        "Markt\n12.10.2026 18:20\nBananen 0,512 kg 1,53\nPFAND 0,25\nRABATT -0,20\nSUMME 1,58"
    )
    assert parsed.total == Decimal("1.58")
    assert parsed.lines[0].quantity == Decimal("0.512")
    assert parsed.lines[0].unit == "kg"
    assert [line.line_kind for line in parsed.lines[1:]] == ["deposit", "discount"]


async def test_duplicate_and_recent_shopping_purchase_are_flagged(client, auth) -> None:
    shopping = await client.post(
        "/api/v1/shopping-list",
        headers=auth[0],
        json={
            "product_id": auth[2]["id"],
            "quantity": 1,
            "unit": "l",
            "source": "manual",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    checked = await client.post(
        f"/api/v1/shopping-list/{shopping.json()['id']}/check",
        headers=auth[0],
        json={"expected_version": 1, "idempotency_key": str(uuid.uuid4())},
    )
    assert checked.status_code == 200
    extraction = ExtractedReceipt.model_validate(
        {
            "merchant": "Markt",
            "purchased_at": "2026-10-12T18:20:00Z",
            "total": "1.29",
            "lines": [
                {
                    "raw_text": "MILCH 1,29",
                    "quantity": 1,
                    "unit": "l",
                    "total_price": "1.29",
                    "suggested_product_id": auth[2]["id"],
                    "confidence": 0.95,
                }
            ],
        }
    )
    with client.session_factory() as db:
        original = add_receipt(db, auth, image_hash="c" * 64)
        apply_extraction(db, original, extraction, Settings())
        original.status = "confirmed"
        original.confirmed_at = datetime.now(UTC)
        db.commit()
        duplicate = add_receipt(db, auth, image_hash="c" * 64)
        apply_extraction(db, duplicate, extraction, Settings(receipt_shopping_dedup_hours=12))
        assert duplicate.duplicate_of_id == original.id
        assert duplicate.lines[0].status == "already_booked"


async def test_confirm_receipt_is_atomic_idempotent_and_reversible(client, auth) -> None:
    with client.session_factory() as db:
        second = Product(
            household_id=auth[0]["X-Household-ID"], name="Joghurt", default_unit="piece"
        )
        db.add(second)
        db.commit()
        receipt = add_receipt(db, auth, image_hash="d" * 64)
        apply_extraction(
            db,
            receipt,
            ExtractedReceipt.model_validate(
                {
                    "merchant": "Markt",
                    "purchased_at": "2026-10-13T18:20:00Z",
                    "total": "3.29",
                    "lines": [
                        {
                            "raw_text": "H-MILCH",
                            "suggested_product_id": auth[2]["id"],
                            "confidence": 1,
                        },
                        {
                            "raw_text": "JOGHURT",
                            "quantity": 2,
                            "suggested_product_id": second.id,
                            "confidence": 1,
                        },
                    ],
                }
            ),
            Settings(),
        )
        receipt_id = receipt.id
        lines = [
            (line.id, line.version, line.product_id, str(line.quantity), line.unit)
            for line in receipt.lines
        ]
    keys = [str(uuid.uuid4()) for _ in lines]
    payload = {
        "lines": [
            {
                "line_id": line_id,
                "expected_version": version,
                "product_id": product_id,
                "quantity": quantity,
                "unit": unit,
                "idempotency_key": key,
            }
            for (line_id, version, product_id, quantity, unit), key in zip(lines, keys, strict=True)
        ]
    }
    confirmed = await client.post(
        f"/api/v1/receipts/{receipt_id}/confirm", headers=auth[0], json=payload
    )
    replay = await client.post(
        f"/api/v1/receipts/{receipt_id}/confirm", headers=auth[0], json=payload
    )
    assert confirmed.status_code == replay.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    with client.session_factory() as db:
        purchases = db.scalar(
            select(func.count(StockMovement.id)).where(
                StockMovement.household_id == auth[0]["X-Household-ID"],
                StockMovement.movement_type == "purchase",
            )
        )
        assert purchases == 2
        aliases = list(db.scalars(select(ProductAlias).where(ProductAlias.source == "receipt")))
        assert len(aliases) == 2
    reversed_response = await client.post(
        f"/api/v1/receipts/{receipt_id}/reverse",
        headers=auth[0],
        json={"idempotency_key": str(uuid.uuid4())},
    )
    assert reversed_response.status_code == 200
    assert reversed_response.json()["status"] == "reversed"
    with client.session_factory() as db:
        assert db.scalar(select(func.count(StockMovement.id))) == 4


async def test_receipt_line_update_rejects_stale_version(client, auth) -> None:
    with client.session_factory() as db:
        receipt = add_receipt(db, auth, image_hash="f" * 64)
        apply_extraction(
            db,
            receipt,
            ExtractedReceipt.model_validate(
                {"merchant": "Markt", "lines": [{"raw_text": "UNBEKANNT 1,00"}]}
            ),
            Settings(),
        )
        receipt_id = receipt.id
        line_id = receipt.lines[0].id
    conflict = await client.patch(
        f"/api/v1/receipts/{receipt_id}/lines/{line_id}",
        headers=auth[0],
        json={"expected_version": 99, "quantity": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "receipt_line_conflict"


async def test_receipts_are_tenant_scoped_and_viewers_cannot_confirm(client, auth) -> None:
    with client.session_factory() as db:
        receipt = add_receipt(db, auth, image_hash="e" * 64)
        apply_extraction(
            db,
            receipt,
            ExtractedReceipt.model_validate(
                {
                    "merchant": "Markt",
                    "lines": [
                        {
                            "raw_text": "MILCH",
                            "suggested_product_id": auth[2]["id"],
                            "confidence": 1,
                        }
                    ],
                }
            ),
            Settings(),
        )
        receipt_id = receipt.id
        line = receipt.lines[0]
        membership = db.scalar(
            select(Membership).where(Membership.household_id == auth[0]["X-Household-ID"])
        )
        assert membership is not None
        membership.role = Role.viewer
        db.commit()
    response = await client.post(
        f"/api/v1/receipts/{receipt_id}/confirm",
        headers=auth[0],
        json={
            "lines": [
                {
                    "line_id": line.id,
                    "expected_version": line.version,
                    "product_id": auth[2]["id"],
                    "quantity": 1,
                    "unit": "l",
                    "idempotency_key": str(uuid.uuid4()),
                }
            ]
        },
    )
    assert response.status_code == 403

    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "display_name": "Other",
            "password": "strong-password",
            "household_name": "Other household",
        },
    )
    token = registration.json()["access_token"]
    bootstrap = await client.get(
        "/api/v1/auth/bootstrap", headers={"Authorization": f"Bearer {token}"}
    )
    other_headers = {
        "Authorization": f"Bearer {token}",
        "X-Household-ID": bootstrap.json()["memberships"][0]["household_id"],
    }
    hidden = await client.get(f"/api/v1/receipts/{receipt_id}", headers=other_headers)
    assert hidden.status_code == 404
