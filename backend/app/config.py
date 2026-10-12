from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
