from sqlalchemy import select

from .database import SessionLocal
from .models import Household, Membership, Product, ProductBarcode, Role, StorageLocation, User
from .security import hash_password


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == "demo@example.com")):
            return
        legacy_user = db.scalar(select(User).where(User.email == "demo@vorrat.local"))
        if legacy_user:
            legacy_user.email = "demo@example.com"
            db.commit()
            return
        user = User(
            email="demo@example.com",
            display_name="Demo",
            password_hash=hash_password("demo-password"),
        )
        household = Household(name="Demo-Haushalt")
        db.add_all([user, household])
        db.flush()
        db.add(Membership(user_id=user.id, household_id=household.id, role=Role.owner))
        db.add_all(
            [
                StorageLocation(household_id=household.id, name=name)
                for name in ("Kühlschrank", "Gefrierschrank", "Vorratsschrank", "Keller")
            ]
        )
        milk = Product(
            household_id=household.id,
            name="Milch",
            brand="Demo",
            category="Molkerei",
            default_unit="l",
        )
        milk.barcodes = [ProductBarcode(barcode="4000000000016")]
        db.add_all(
            [
                milk,
                Product(
                    household_id=household.id,
                    name="Nudeln",
                    category="Trockenwaren",
                    default_unit="package",
                ),
                Product(
                    household_id=household.id,
                    name="Tomaten",
                    category="Gemüse",
                    default_unit="piece",
                ),
            ]
        )
        db.commit()


if __name__ == "__main__":
    seed()
