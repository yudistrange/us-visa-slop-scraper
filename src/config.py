"""Configuration management using pydantic-settings."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Known facility ID → city name mapping
FACILITY_NAMES: dict[int, str] = {
    # Canada
    89: "Calgary",
    90: "Halifax",
    91: "Montreal",
    92: "Ottawa",
    93: "Quebec City",
    94: "Toronto",
    95: "Vancouver",
    # India
    5: "Mumbai",
    6: "Chennai",
    7: "Hyderabad",
    8: "Kolkata",
    9: "New Delhi",
    # UK
    18: "London",
    19: "Belfast",
    # Mexico
    10: "Ciudad Juarez",
    11: "Guadalajara",
    12: "Hermosillo",
    13: "Matamoros",
    14: "Merida",
    15: "Mexico City",
    16: "Monterrey",
    17: "Nogales",
    # Germany
    20: "Berlin",
    21: "Frankfurt",
    22: "Munich",
    # Australia
    23: "Melbourne",
    24: "Perth",
    25: "Sydney",
}


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
    facility_ids: str = "95"  # Comma-separated list: "89,94,95"
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
    reschedule_threshold_days: int = Field(default=0, ge=0)

    # --- Advanced ---
    log_level: str = "INFO"
    max_consecutive_errors: int = 5
    headless: bool = True

    # --- Parsed facility list ---
    @property
    def facility_id_list(self) -> list[int]:
        """Parse comma-separated FACILITY_IDS into a list of ints."""
        return [int(fid.strip()) for fid in self.facility_ids.split(",") if fid.strip()]

    def facility_name(self, facility_id: int) -> str:
        """Human-readable name for a facility ID."""
        return FACILITY_NAMES.get(facility_id, f"Facility {facility_id}")

    # --- URL builders (per facility) ---
    @property
    def base_url(self) -> str:
        return f"https://ais.usvisa-info.com/{self.country_code}/niv"

    @property
    def sign_in_url(self) -> str:
        return f"{self.base_url}/users/sign_in"

    def appointments_url(self, facility_id: int) -> str:
        return (
            f"{self.base_url}/schedule/{self.schedule_id}/appointment/days"
            f"/{facility_id}.json?appointments[expedite]=false"
        )

    def appointment_times_url(self, facility_id: int) -> str:
        return (
            f"{self.base_url}/schedule/{self.schedule_id}/appointment/times"
            f"/{facility_id}.json"
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

    @field_validator("facility_ids")
    @classmethod
    def validate_facility_ids(cls, v: str) -> str:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        if not parts:
            raise ValueError("FACILITY_IDS must contain at least one facility ID")
        for p in parts:
            if not p.isdigit():
                raise ValueError(f"Invalid facility ID: '{p}' — must be an integer")
        return v


def load_settings() -> Settings:
    """Load and return application settings."""
    return Settings()  # type: ignore[call-arg]
