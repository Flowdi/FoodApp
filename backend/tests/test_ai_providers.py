from fastapi import HTTPException
from pydantic import BaseModel

from backend.app.ai.providers import generate_image_structured, generate_structured
from backend.app.config import Settings
from backend.app.models import Household


class Result(BaseModel):
    value: int


class RetryingProvider:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def text_to_json(self, prompt: str, schema: dict[str, object]):
        self.calls += 1
        return ({"wrong": True} if self.calls == 1 else {"value": 4}, 2, 1)

    def image_to_json(self, prompt: str, images: list[bytes], schema: dict[str, object]):
        self.calls += 1
        return ({"wrong": True} if self.calls == 1 else {"value": 5}, 2, 1)


async def test_invalid_llm_json_is_retried_once(client) -> None:
    with client.session_factory() as db:
        household = Household(name="KI-Test")
        db.add(household)
        db.commit()
        provider = RetryingProvider()
        result = generate_structured(
            db,
            household_id=household.id,
            feature="test",
            prompt="test",
            response_model=Result,
            provider=provider,
            settings=Settings(llm_daily_limit_per_household=5),
        )
        assert result.value == 4
        assert provider.calls == 2


async def test_daily_limit_blocks_provider_call(client) -> None:
    with client.session_factory() as db:
        household = Household(name="Limit-Test")
        db.add(household)
        db.commit()
        provider = RetryingProvider()
        try:
            generate_structured(
                db,
                household_id=household.id,
                feature="test",
                prompt="test",
                response_model=Result,
                provider=provider,
                settings=Settings(llm_daily_limit_per_household=0),
            )
        except HTTPException as exc:
            assert exc.status_code == 429
        else:
            raise AssertionError("Tageslimit wurde nicht angewendet")
        assert provider.calls == 0


async def test_invalid_image_json_is_retried_once(client) -> None:
    with client.session_factory() as db:
        household = Household(name="Bild-Test")
        db.add(household)
        db.commit()
        provider = RetryingProvider()
        result = generate_image_structured(
            db,
            household_id=household.id,
            feature="receipt",
            prompt="test",
            images=[b"image"],
            response_model=Result,
            provider=provider,
            settings=Settings(llm_daily_limit_per_household=5),
        )
        assert result.value == 5
        assert provider.calls == 2
