from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    environment: str = "development"
    database_url: str = "sqlite:///./vorrat.db"
    secret_key: str = "development-only-change-me-please"
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    cors_origins: list[str] = ["http://localhost:5173"]
    open_food_facts_user_agent: str = "Vorrat/0.1 (admin@example.invalid)"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "vorrat@example.invalid"
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@example.invalid"
    public_url: str = "https://localhost"
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
    recipe_ranker_provider: str = "deterministic"
    recipe_ranker_timeout_seconds: float = 15
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    ollama_model: str = "qwen3:4b"
    ollama_base_url: str = "http://host.docker.internal:11434"
    llm_provider: str = "none"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_timeout_seconds: float = 15
    llm_daily_limit_per_household: int = 50
    stt_provider: str = "faster-whisper"
    stt_model: str = Field(
        default="small", validation_alias=AliasChoices("STT_MODEL_SIZE", "STT_MODEL")
    )
    stt_api_key: str = ""
    stt_base_url: str = ""
    receipt_ocr_mode: str = "vision_llm"
    receipt_image_retention_days: int = 30
    receipt_shopping_dedup_hours: int = 12
    receipt_storage_path: str = "data/receipts"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
