"""Entry point — runs the appointment checking loop."""

from __future__ import annotations

import asyncio
import random
import signal
import sys
from datetime import datetime

from .config import load_settings
from .scheduler import AppointmentChecker
from .telegram_notifier import TelegramNotifier
from .utils import format_date, setup_logging
from .visa_client import VisaClient


async def run() -> None:
    """Main async loop."""
    settings = load_settings()
    logger = setup_logging(settings.log_level)

    facility_names = [
        f"{settings.facility_name(fid)} ({fid})"
        for fid in settings.facility_id_list
    ]

    logger.info("=" * 60)
    logger.info("US Visa Appointment Scheduler starting up")
    logger.info("=" * 60)
    logger.info("Email:        %s", settings.usvisa_email)
    logger.info("Schedule ID:  %s", settings.schedule_id)
    logger.info("Country:      %s", settings.country_code)
    logger.info("Facilities:   %s", ", ".join(facility_names))
    logger.info("Current date: %s", format_date(settings.current_appointment_date.isoformat()))
    logger.info("Interval:     %d ± %d min", settings.check_interval_minutes, settings.check_interval_jitter_minutes)
    logger.info("Auto-resched: %s", settings.auto_reschedule)
    logger.info("Headless:     %s", settings.headless)
    logger.info("=" * 60)

    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    visa_client = VisaClient(settings)
    checker = AppointmentChecker(settings, visa_client, notifier)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    consecutive_errors = 0

    try:
        # Start browser
        await visa_client.start()

        # Send startup notification
        try:
            await notifier.notify_startup(
                current_date=format_date(settings.current_appointment_date.isoformat()),
                facility_names=facility_names,
            )
        except Exception as e:
            logger.error("Failed to send startup notification: %s", e)

        while not shutdown_event.is_set():
            check_start = datetime.now()
            logger.info("--- Check cycle at %s ---", check_start.strftime("%Y-%m-%d %H:%M:%S"))

            try:
                await checker.check_and_notify()
                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    "Check failed (consecutive: %d): %s",
                    consecutive_errors,
                    e,
                    exc_info=True,
                )

                # Notify on persistent errors
                if consecutive_errors >= settings.max_consecutive_errors:
                    try:
                        await notifier.notify_error(str(e), consecutive_errors)
                    except Exception:
                        logger.error("Failed to send error notification")

                # Re-create browser session on auth errors
                if "session expired" in str(e).lower() or "login failed" in str(e).lower():
                    logger.info("Restarting browser session...")
                    try:
                        await visa_client.close()
                    except Exception:
                        pass
                    await visa_client.start()

            # Calculate next check time with jitter
            base_interval = settings.check_interval_minutes * 60
            jitter = random.uniform(0, settings.check_interval_jitter_minutes * 60)
            wait_seconds = base_interval + jitter

            next_check = datetime.now().timestamp() + wait_seconds
            logger.info(
                "Next check in %.1f minutes (at %s)",
                wait_seconds / 60,
                datetime.fromtimestamp(next_check).strftime("%H:%M:%S"),
            )

            # Wait with ability to cancel
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue to next check

    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        try:
            await notifier.send_message(
                f"🔴 <b>VISA SCHEDULER CRASHED</b>\n\n<code>{str(e)[:500]}</code>"
            )
        except Exception:
            pass
        raise

    finally:
        logger.info("Shutting down...")
        await visa_client.close()
        await notifier.close()
        logger.info("Goodbye!")


def main() -> None:
    """Sync entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
