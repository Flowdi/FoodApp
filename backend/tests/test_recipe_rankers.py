import json

import pytest

from backend.app.config import Settings
from backend.app.services.recipe_rankers import (
    AnthropicRanker,
    OllamaRanker,
    OpenAIRanker,
    configured_ranker,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


@pytest.mark.parametrize(
    ("provider", "payload", "ranker_type"),
    [
        (
            "openai",
            {"output": [{"content": [{"type": "output_text", "text": "{}"}]}]},
            OpenAIRanker,
        ),
        ("anthropic", {"content": [{"type": "text", "text": "{}"}]}, AnthropicRanker),
        ("ollama", {"message": {"content": "{}"}}, OllamaRanker),
    ],
)
def test_provider_selection_and_request_shape(monkeypatch, provider, payload, ranker_type) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse(payload)

    monkeypatch.setattr("backend.app.services.recipe_rankers.httpx.post", fake_post)
    settings = Settings(
        recipe_ranker_provider=provider,
        openai_api_key="test-openai",
        anthropic_api_key="test-anthropic",
    )
    ranker = configured_ranker(settings)
    assert isinstance(ranker, ranker_type)
    with pytest.raises(ValueError):
        ranker.rank([])
    assert str(captured["url"]).startswith(("https://", "http://"))
    assert captured["json"] is not None


def test_ollama_uses_json_schema(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        body = json.dumps({"ranking": []})
        return FakeResponse({"message": {"content": body}})

    monkeypatch.setattr("backend.app.services.recipe_rankers.httpx.post", fake_post)
    ranker = OllamaRanker(Settings(recipe_ranker_provider="ollama"))
    assert ranker.rank([]) == []
    assert isinstance(captured["json"]["format"], dict)
