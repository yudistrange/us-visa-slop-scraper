"""Configuration management using pydantic-settings."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- US Visa credentials ---
    usvisa_email: str
    usvisa_password: str
    schedule_id: str
    facility_id: int = 95
    country_code: str = "en-ca"

    # --- Current appointment ---
    current_appointment_date: date

    # --- Telegram ---
    telegram_bot_token: str
    telegram_chat_id: str

    # --- Scheduler ---
    check_interval_minutes: int = Field(default=10, ge=1)
    check_interval_jitter_minutes: int = Field(default=5, ge=0)
    auto_reschedule: bool = False

    # --- Advanced ---
    log_level: str = "INFO"
    max_consecutive_errors: int = 5
    headless: bool = True

    # --- Derived ---
    @property
    def base_url(self) -> str:
        return f"https://ais.usvisa-info.com/{self.country_code}/niv"

    @property
    def sign_in_url(self) -> str:
        return f"{self.base_url}/users/sign_in"

    @property
    def appointments_url(self) -> str:
        return (
            f"{self.base_url}/schedule/{self.schedule_id}/appointment/days"
            f"/{self.facility_id}.json?appointments[expedite]=false"
        )

    @property
    def appointment_times_url(self) -> str:
        return (
            f"{self.base_url}/schedule/{self.schedule_id}/appointment/times"
            f"/{self.facility_id}.json"
        )

    @property
    def reschedule_url(self) -> str:
        return f"{self.base_url}/schedule/{self.schedule_id}/appointment"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper


def load_settings() -> Settings:
    """Load and return application settings."""
    return Settings()  # type: ignore[call-arg]
