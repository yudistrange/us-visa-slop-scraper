"""Core scheduling logic — check dates across facilities, compare, notify/reschedule."""

from __future__ import annotations

import logging
from datetime import datetime

from .config import Settings
from .telegram_notifier import TelegramNotifier
from .utils import format_date
from .visa_client import FacilityResult, VisaClient

logger = logging.getLogger("visa_scheduler.scheduler")


class AppointmentChecker:
    """Checks for earlier visa appointments across all configured facilities."""

    def __init__(
        self,
        settings: Settings,
        visa_client: VisaClient,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.visa_client = visa_client
        self.notifier = notifier
        # Track last notified date per facility to avoid duplicate alerts
        self._last_notified: dict[int, str] = {}

    async def check_and_notify(self) -> None:
        """
        Main check cycle:
        1. Fetch available dates for ALL configured facilities
        2. Compare each with current appointment
        3. Notify for each facility that has an earlier date
        4. Optionally auto-reschedule to the absolute earliest across all
        """
        results = await self.visa_client.get_all_facility_dates()

        current_str = self.settings.current_appointment_date.isoformat()
        current_date = self.settings.current_appointment_date

        # Log summary
        self._log_summary(results, current_str)

        # Collect facilities that have earlier dates
        earlier: list[FacilityResult] = []
        for r in results:
            if r.error:
                continue
            if not r.earliest_date:
                continue
            earliest_dt = datetime.strptime(r.earliest_date, "%Y-%m-%d").date()
            if earliest_dt < current_date:
                earlier.append(r)

        if not earlier:
            logger.info("No earlier dates found across any facility")
            return

        # Sort by earliest date (best first)
        earlier.sort(key=lambda r: r.earliest_date)  # type: ignore[arg-type]

        # Notify for each facility with an earlier date
        for r in earlier:
            earliest_dt = datetime.strptime(r.earliest_date, "%Y-%m-%d").date()  # type: ignore[arg-type]
            days_diff = (current_date - earliest_dt).days

            logger.info(
                "🎉 EARLIER DATE at %s: %s (%d days earlier!)",
                r.facility_name,
                r.earliest_date,
                days_diff,
            )

            # Skip if we already notified about this exact date at this facility
            if self._last_notified.get(r.facility_id) == r.earliest_date:
                logger.info(
                    "Already notified about %s at %s, skipping",
                    r.earliest_date,
                    r.facility_name,
                )
                continue

            await self.notifier.notify_earlier_date(
                available_date=format_date(r.earliest_date),  # type: ignore[arg-type]
                current_date=format_date(current_str),
                days_earlier=days_diff,
                facility_name=r.facility_name,
                auto_rescheduled=False,  # Updated below if auto-reschedule succeeds
            )
            self._last_notified[r.facility_id] = r.earliest_date  # type: ignore[assignment]

        # Auto-reschedule to the absolute best option
        if self.settings.auto_reschedule:
            best = earlier[0]
            await self._try_reschedule(best)

    async def _try_reschedule(self, result: FacilityResult) -> None:
        """Attempt to reschedule to the earliest date at the given facility."""
        assert result.earliest_date is not None

        try:
            times = await self.visa_client.get_available_times(
                result.facility_id, result.earliest_date
            )

            if not times:
                logger.warning(
                    "No times available for %s on %s, cannot reschedule",
                    result.facility_name,
                    result.earliest_date,
                )
                return

            chosen_time = times[0]
            logger.info(
                "Auto-rescheduling to %s on %s at %s",
                result.facility_name,
                result.earliest_date,
                chosen_time,
            )

            success = await self.visa_client.reschedule(
                result.facility_id, result.earliest_date, chosen_time
            )

            if success:
                earliest_dt = datetime.strptime(result.earliest_date, "%Y-%m-%d").date()
                days_diff = (self.settings.current_appointment_date - earliest_dt).days

                await self.notifier.notify_earlier_date(
                    available_date=format_date(result.earliest_date),
                    current_date=format_date(self.settings.current_appointment_date.isoformat()),
                    days_earlier=days_diff,
                    facility_name=result.facility_name,
                    auto_rescheduled=True,
                )

                self.settings.current_appointment_date = earliest_dt
                logger.info("Updated current appointment date to %s", result.earliest_date)
            else:
                logger.warning("❌ Auto-reschedule to %s failed", result.facility_name)

        except Exception as e:
            logger.error("Reschedule error for %s: %s", result.facility_name, e, exc_info=True)

    def _log_summary(self, results: list[FacilityResult], current_str: str) -> None:
        """Log a one-line-per-facility summary."""
        logger.info("--- Results for %d facilities (current: %s) ---", len(results), current_str)
        for r in results:
            if r.error:
                logger.warning("  %-15s  ❌ Error: %s", r.facility_name, r.error[:80])
            elif r.earliest_date:
                logger.info("  %-15s  📅 %s  (%d dates)", r.facility_name, r.earliest_date, len(r.dates))
            else:
                logger.info("  %-15s  —  no dates", r.facility_name)
