"""Core scheduling logic — check dates, compare, decide to notify/reschedule."""

from __future__ import annotations

import logging
from datetime import date, datetime

from .config import Settings
from .telegram_notifier import TelegramNotifier
from .utils import days_until, format_date
from .visa_client import VisaClient

logger = logging.getLogger("visa_scheduler.scheduler")


class AppointmentChecker:
    """Checks for earlier visa appointments and takes action."""

    def __init__(
        self,
        settings: Settings,
        visa_client: VisaClient,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.visa_client = visa_client
        self.notifier = notifier
        self._last_notified_date: str | None = None

    async def check_and_notify(self) -> None:
        """
        Main check cycle:
        1. Fetch available dates
        2. Compare with current appointment
        3. Notify (and optionally reschedule) if earlier
        """
        dates = await self.visa_client.get_available_dates()

        if not dates:
            logger.info("No available appointment dates found")
            return

        earliest = dates[0]
        current_str = self.settings.current_appointment_date.isoformat()

        logger.info(
            "Earliest available: %s | Current appointment: %s",
            earliest,
            current_str,
        )

        # Parse for comparison
        earliest_date = datetime.strptime(earliest, "%Y-%m-%d").date()
        current_date = self.settings.current_appointment_date

        if earliest_date >= current_date:
            logger.info(
                "No earlier date found (earliest: %s, current: %s)",
                earliest,
                current_str,
            )
            return

        # Found an earlier date!
        days_diff = (current_date - earliest_date).days
        logger.info(
            "🎉 EARLIER DATE FOUND: %s (%d days earlier!)",
            earliest,
            days_diff,
        )

        # Skip if we already notified about this exact date
        if self._last_notified_date == earliest:
            logger.info("Already notified about %s, skipping duplicate", earliest)
            return

        # Auto-reschedule if enabled
        auto_rescheduled = False
        if self.settings.auto_reschedule:
            auto_rescheduled = await self._try_reschedule(earliest)

        # Send Telegram notification
        await self.notifier.notify_earlier_date(
            available_date=format_date(earliest),
            current_date=format_date(current_str),
            days_earlier=days_diff,
            facility_name=f"Facility {self.settings.facility_id}",
            auto_rescheduled=auto_rescheduled,
        )

        self._last_notified_date = earliest

        # Update current date if rescheduled
        if auto_rescheduled:
            self.settings.current_appointment_date = earliest_date
            logger.info("Updated current appointment date to %s", earliest)

    async def _try_reschedule(self, target_date: str) -> bool:
        """Attempt to reschedule to the target date."""
        try:
            # Get available times for that date
            times = await self.visa_client.get_available_times(target_date)

            if not times:
                logger.warning("No times available for %s, cannot reschedule", target_date)
                return False

            # Pick the first available time
            chosen_time = times[0]
            logger.info("Attempting reschedule to %s at %s", target_date, chosen_time)

            success = await self.visa_client.reschedule(target_date, chosen_time)

            if success:
                logger.info("✅ Rescheduled successfully!")
            else:
                logger.warning("❌ Reschedule attempt failed")

            return success

        except Exception as e:
            logger.error("Reschedule error: %s", e, exc_info=True)
            return False
