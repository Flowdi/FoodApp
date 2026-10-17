from sqlalchemy import func, select

from backend.app.demo_seed import DEMO_MARKER, ean13, seed_demo
from backend.app.models import Product, ProductBarcode, ShoppingListItem, StockBatch, StockMovement


def test_demo_seed_creates_realistic_idempotent_dataset(client, auth) -> None:
    with client.session_factory() as db:
        first = seed_demo(db, email="owner@example.com")
        second = seed_demo(db, email="owner@example.com")

        products = list(db.scalars(select(Product).where(Product.notes == DEMO_MARKER)))
        batch_count = db.scalar(
            select(func.count())
            .select_from(StockBatch)
            .where(StockBatch.product_id.in_([product.id for product in products]))
        )
        movement_count = db.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.client_info == "demo-seed")
        )
        shopping_count = db.scalar(
            select(func.count())
            .select_from(ShoppingListItem)
            .where(ShoppingListItem.note == DEMO_MARKER)
        )
        barcodes = set(
            db.scalars(
                select(ProductBarcode.barcode).where(
                    ProductBarcode.product_id.in_([product.id for product in products])
                )
            )
        )

    assert first["products"] == 100
    assert first["created"] == 1
    assert second == {"products": 100, "created": 0}
    assert len(products) == 100
    assert batch_count == 100
    assert movement_count == 112
    assert shopping_count == 10
    assert barcodes == {ean13(index) for index in range(1, 101)}
