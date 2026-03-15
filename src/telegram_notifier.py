"""Telegram notification service."""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("visa_scheduler.telegram")


class TelegramNotifier:
    """Send notifications via Telegram Bot API."""

    API_BASE = "https://api.telegram.org"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def _base_url(self) -> str:
        return f"{self.API_BASE}/bot{self.bot_token}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> dict:
        """Send a text message to the configured chat."""
        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }

        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            logger.error("Telegram API error: %s", data)
            raise RuntimeError(f"Telegram API error: {data.get('description', 'Unknown')}")

        logger.debug("Telegram message sent successfully")
        return data

    async def notify_earlier_date(
        self,
        available_date: str,
        current_date: str,
        days_earlier: int,
        facility_name: str = "Consulate",
        auto_rescheduled: bool = False,
    ) -> dict:
        """Send a formatted notification about an earlier appointment date."""
        if auto_rescheduled:
            status = "✅ <b>AUTO-RESCHEDULED</b>"
            action_line = "Your appointment has been automatically rescheduled!"
        else:
            status = "🔔 <b>EARLIER DATE AVAILABLE</b>"
            action_line = "Log in to reschedule: https://ais.usvisa-info.com"

        text = (
            f"{status}\n"
            f"\n"
            f"📍 <b>{facility_name}</b>\n"
            f"📅 Available: <b>{available_date}</b>\n"
            f"📅 Current: {current_date}\n"
            f"⏱ <b>{days_earlier} days earlier!</b>\n"
            f"\n"
            f"{action_line}"
        )

        return await self.send_message(text)

    async def notify_error(self, error_msg: str, consecutive_count: int) -> dict:
        """Send an error notification."""
        text = (
            f"⚠️ <b>VISA SCHEDULER ERROR</b>\n"
            f"\n"
            f"Consecutive errors: {consecutive_count}\n"
            f"Error: <code>{error_msg[:500]}</code>\n"
            f"\n"
            f"The scheduler will keep retrying."
        )
        return await self.send_message(text)

    async def notify_startup(
        self, current_date: str, facility_names: list[str]
    ) -> dict:
        """Send a startup notification listing all monitored facilities."""
        facilities_str = "\n".join(f"  • {name}" for name in facility_names)
        text = (
            f"🚀 <b>VISA SCHEDULER STARTED</b>\n"
            f"\n"
            f"📅 Current appointment: <b>{current_date}</b>\n"
            f"🏢 Monitoring:\n{facilities_str}\n"
            f"\n"
            f"Checking for earlier dates..."
        )
        return await self.send_message(text)

    async def notify_no_dates(self) -> dict:
        """Send a notification that no dates are available at all."""
        text = (
            f"ℹ️ <b>No appointment dates available</b>\n"
            f"\n"
            f"No open slots at any monitored consulate right now.\n"
            f"Will keep checking..."
        )
        return await self.send_message(text, disable_notification=True)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
