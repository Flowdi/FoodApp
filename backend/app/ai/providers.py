import base64
import json
from datetime import UTC, datetime
from typing import Protocol

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import AIUsageLog


class LLMProvider(Protocol):
    name: str

    def text_to_json(
        self, prompt: str, schema: dict[str, object]
    ) -> tuple[object, int | None, int | None]: ...

    def image_to_json(
        self, prompt: str, images: list[bytes], schema: dict[str, object]
    ) -> tuple[object, int | None, int | None]: ...


def _json_from_text(value: str) -> object:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    return json.loads(cleaned)


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings

    def text_to_json(
        self, prompt: str, schema: dict[str, object]
    ) -> tuple[object, int | None, int | None]:
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json={
                "model": self.settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_response",
                        "strict": True,
                        "schema": schema,
                    },
                },
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage", {})
        return (
            _json_from_text(payload["choices"][0]["message"]["content"]),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )

    def image_to_json(
        self, prompt: str, images: list[bytes], schema: dict[str, object]
    ) -> tuple[object, int | None, int | None]:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(item).decode()}"},
            }
            for item in images
        )
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json={
                "model": self.settings.llm_model,
                "messages": [{"role": "user", "content": content}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_image_response",
                        "strict": True,
                        "schema": schema,
                    },
                },
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage", {})
        return (
            _json_from_text(payload["choices"][0]["message"]["content"]),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings):
        self.settings = settings

    def text_to_json(
        self, prompt: str, schema: dict[str, object]
    ) -> tuple[object, int | None, int | None]:
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/messages",
            headers={"x-api-key": self.settings.llm_api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": self.settings.llm_model,
                "max_tokens": 2048,
                "messages": [
                    {"role": "user", "content": f"{prompt}\nJSON-Schema:\n{json.dumps(schema)}"}
                ],
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage", {})
        return (
            _json_from_text(payload["content"][0]["text"]),
            usage.get("input_tokens"),
            usage.get("output_tokens"),
        )

    def image_to_json(
        self, prompt: str, images: list[bytes], schema: dict[str, object]
    ) -> tuple[object, int | None, int | None]:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(item).decode(),
                },
            }
            for item in images
        )
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/messages",
            headers={
                "x-api-key": self.settings.llm_api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": self.settings.llm_model,
                "max_tokens": 4096,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            *content,
                            {"type": "text", "text": f"JSON-Schema:\n{json.dumps(schema)}"},
                        ],
                    }
                ],
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage", {})
        text = "".join(item.get("text", "") for item in payload.get("content", []))
        return _json_from_text(text), usage.get("input_tokens"), usage.get("output_tokens")


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings

    def text_to_json(
        self, prompt: str, schema: dict[str, object]
    ) -> tuple[object, int | None, int | None]:
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/api/chat",
            json={
                "model": self.settings.llm_model,
                "stream": False,
                "format": schema,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return (
            _json_from_text(payload["message"]["content"]),
            payload.get("prompt_eval_count"),
            payload.get("eval_count"),
        )

    def image_to_json(
        self, prompt: str, images: list[bytes], schema: dict[str, object]
    ) -> tuple[object, int | None, int | None]:
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/api/chat",
            json={
                "model": self.settings.llm_model,
                "stream": False,
                "format": schema,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [base64.b64encode(item).decode() for item in images],
                    }
                ],
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return (
            _json_from_text(payload["message"]["content"]),
            payload.get("prompt_eval_count"),
            payload.get("eval_count"),
        )


def configured_llm(settings: Settings | None = None) -> LLMProvider | None:
    settings = settings or get_settings()
    if settings.llm_provider == "openai":
        settings = settings.model_copy(
            update={
                "llm_model": settings.llm_model or settings.openai_model,
                "llm_api_key": settings.llm_api_key or settings.openai_api_key,
                "llm_base_url": settings.llm_base_url or settings.openai_base_url,
            }
        )
    elif settings.llm_provider == "anthropic":
        settings = settings.model_copy(
            update={
                "llm_model": settings.llm_model or settings.anthropic_model,
                "llm_api_key": settings.llm_api_key or settings.anthropic_api_key,
                "llm_base_url": settings.llm_base_url or settings.anthropic_base_url,
            }
        )
    elif settings.llm_provider == "ollama":
        settings = settings.model_copy(
            update={
                "llm_model": settings.llm_model or settings.ollama_model,
                "llm_base_url": settings.llm_base_url or settings.ollama_base_url,
            }
        )
    providers: dict[str, type[OpenAIProvider] | type[AnthropicProvider] | type[OllamaProvider]] = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
    }
    provider_type = providers.get(settings.llm_provider.lower())
    return provider_type(settings) if provider_type else None


def generate_structured[StructuredT: BaseModel](
    db: Session,
    *,
    household_id: str,
    feature: str,
    prompt: str,
    response_model: type[StructuredT],
    provider: LLMProvider | None = None,
    settings: Settings | None = None,
) -> StructuredT:
    settings = settings or get_settings()
    provider = provider or configured_llm(settings)
    if provider is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "llm_unavailable", "message": "Keine KI-Unterstützung konfiguriert"},
        )
    today = datetime.now(UTC).date()
    used = db.scalar(
        select(func.count(AIUsageLog.id)).where(
            AIUsageLog.household_id == household_id,
            func.date(AIUsageLog.created_at) == today,
        )
    )
    if int(used or 0) >= settings.llm_daily_limit_per_household:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"code": "llm_daily_limit", "message": "Tägliches KI-Limit erreicht"},
        )
    current_prompt = prompt
    last_error: ValidationError | ValueError | None = None
    for attempt in range(2):
        try:
            raw, input_units, output_units = provider.text_to_json(
                current_prompt, response_model.model_json_schema()
            )
            result = response_model.model_validate(raw)
            db.add(
                AIUsageLog(
                    household_id=household_id,
                    provider=provider.name,
                    feature=feature,
                    input_units=input_units,
                    output_units=output_units,
                )
            )
            db.commit()
            return result
        except (ValidationError, ValueError) as exc:
            last_error = exc
            current_prompt = (
                f"{prompt}\nDie vorige Antwort war ungültig: {exc}. "
                "Antworte ausschließlich mit gültigem JSON nach dem Schema."
            )
            if attempt == 1:
                break
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        {"code": "llm_invalid_response", "message": "KI-Antwort konnte nicht geprüft werden"},
    ) from last_error


def generate_image_structured[StructuredT: BaseModel](
    db: Session,
    *,
    household_id: str,
    feature: str,
    prompt: str,
    images: list[bytes],
    response_model: type[StructuredT],
    provider: LLMProvider | None = None,
    settings: Settings | None = None,
) -> StructuredT:
    settings = settings or get_settings()
    provider = provider or configured_llm(settings)
    if provider is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "llm_unavailable", "message": "Keine KI-Unterstützung konfiguriert"},
        )
    today = datetime.now(UTC).date()
    used = db.scalar(
        select(func.count(AIUsageLog.id)).where(
            AIUsageLog.household_id == household_id,
            func.date(AIUsageLog.created_at) == today,
        )
    )
    if int(used or 0) >= settings.llm_daily_limit_per_household:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"code": "llm_daily_limit", "message": "Tägliches KI-Limit erreicht"},
        )
    current_prompt = prompt
    last_error: ValidationError | ValueError | None = None
    for attempt in range(2):
        try:
            raw, input_units, output_units = provider.image_to_json(
                current_prompt, images, response_model.model_json_schema()
            )
            result = response_model.model_validate(raw)
            db.add(
                AIUsageLog(
                    household_id=household_id,
                    provider=provider.name,
                    feature=feature,
                    input_units=input_units,
                    output_units=output_units,
                )
            )
            db.commit()
            return result
        except (ValidationError, ValueError) as exc:
            last_error = exc
            current_prompt = (
                f"{prompt}\nDie vorige Bildanalyse war ungültig: {exc}. "
                "Antworte ausschließlich mit gültigem JSON nach dem Schema."
            )
            if attempt == 1:
                break
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        {"code": "llm_invalid_response", "message": "KI-Antwort konnte nicht geprüft werden"},
    ) from last_error
