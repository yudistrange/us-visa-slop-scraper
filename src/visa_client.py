"""Browser-based client for ais.usvisa-info.com using Playwright."""

from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import Settings

logger = logging.getLogger("visa_scheduler.client")

# Realistic user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


class VisaClient:
    """Handles authentication and date-checking on ais.usvisa-info.com."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._signed_in = False

    async def start(self) -> None:
        """Launch browser and create a context."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.settings.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        user_agent = random.choice(USER_AGENTS)
        self._context = await self._browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Mask webdriver detection
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        self._page = await self._context.new_page()
        logger.info("Browser started (headless=%s, UA=%s)", self.settings.headless, user_agent[:50])

    async def close(self) -> None:
        """Clean up browser resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._signed_in = False
        logger.info("Browser closed")

    async def _random_delay(self, min_sec: float = 1.0, max_sec: float = 3.0) -> None:
        """Human-like random delay."""
        import asyncio
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def sign_in(self) -> None:
        """Sign into ais.usvisa-info.com."""
        page = self._page
        assert page is not None, "Browser not started. Call start() first."

        logger.info("Navigating to sign-in page...")
        await page.goto(self.settings.sign_in_url, wait_until="domcontentloaded")
        await self._random_delay(2, 4)

        # Accept cookies if banner appears
        try:
            cookie_btn = page.locator("a.cookie_action_close_header, button#onetrust-accept-btn-handler")
            if await cookie_btn.count() > 0:
                await cookie_btn.first.click()
                await self._random_delay(0.5, 1.5)
        except Exception:
            pass

        # Fill credentials
        logger.info("Filling login credentials...")
        email_input = page.locator('input[name="user[email]"]')
        await email_input.fill("")
        await email_input.type(self.settings.usvisa_email, delay=random.randint(50, 150))
        await self._random_delay(0.5, 1.5)

        password_input = page.locator('input[name="user[password]"]')
        await password_input.fill("")
        await password_input.type(self.settings.usvisa_password, delay=random.randint(50, 150))
        await self._random_delay(0.5, 1.5)

        # Check the privacy checkbox
        try:
            checkbox = page.locator('input[name="policy_confirmed"]')
            if await checkbox.count() > 0:
                await checkbox.check()
                await self._random_delay(0.3, 1.0)
        except Exception:
            pass

        # Submit
        submit_btn = page.locator('input[type="submit"][name="commit"]')
        await submit_btn.click()

        # Wait for navigation after login
        await page.wait_for_load_state("domcontentloaded")
        await self._random_delay(2, 4)

        # Check if login succeeded
        if "sign_in" in page.url:
            # Check for error messages
            error = page.locator(".flash-container .alert, .error-message")
            if await error.count() > 0:
                error_text = await error.first.inner_text()
                raise RuntimeError(f"Login failed: {error_text.strip()}")
            raise RuntimeError("Login failed: still on sign-in page")

        self._signed_in = True
        logger.info("Successfully signed in")

    async def _ensure_signed_in(self) -> None:
        """Ensure we have an active session, re-login if needed."""
        if not self._signed_in:
            await self.sign_in()

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_available_dates(self) -> list[str]:
        """
        Fetch available appointment dates from the API.

        Returns a sorted list of date strings in YYYY-MM-DD format.
        """
        await self._ensure_signed_in()
        page = self._page
        assert page is not None

        logger.info("Fetching available dates for facility %s...", self.settings.facility_id)
        await self._random_delay(1, 2)

        # Make the API request through the browser (uses session cookies)
        response = await page.evaluate(
            """async (url) => {
                const resp = await fetch(url, {
                    headers: {
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                });
                if (!resp.ok) {
                    return { error: resp.status, text: await resp.text() };
                }
                return await resp.json();
            }""",
            self.settings.appointments_url,
        )

        if isinstance(response, dict) and "error" in response:
            error_status = response["error"]
            logger.warning("API returned status %s — session may have expired", error_status)
            if error_status in (401, 403):
                self._signed_in = False
                raise RuntimeError(f"Session expired (HTTP {error_status})")
            raise RuntimeError(f"API error: HTTP {error_status}")

        if not isinstance(response, list):
            logger.warning("Unexpected response format: %s", type(response))
            self._signed_in = False
            raise RuntimeError(f"Unexpected response: {str(response)[:200]}")

        dates = sorted([entry["date"] for entry in response if "date" in entry])
        logger.info("Found %d available dates", len(dates))

        if dates:
            logger.info("Earliest: %s | Latest: %s", dates[0], dates[-1])

        return dates

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_available_times(self, appointment_date: str) -> list[str]:
        """Fetch available times for a specific date."""
        await self._ensure_signed_in()
        page = self._page
        assert page is not None

        url = f"{self.settings.appointment_times_url}?date={appointment_date}&appointments[expedite]=false"
        logger.info("Fetching times for %s...", appointment_date)
        await self._random_delay(1, 2)

        response = await page.evaluate(
            """async (url) => {
                const resp = await fetch(url, {
                    headers: {
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                });
                if (!resp.ok) return { error: resp.status };
                return await resp.json();
            }""",
            url,
        )

        if isinstance(response, dict) and "error" in response:
            raise RuntimeError(f"API error fetching times: HTTP {response['error']}")

        if isinstance(response, dict) and "available_times" in response:
            times = response["available_times"]
        elif isinstance(response, dict) and "business_times" in response:
            times = response["business_times"]
        elif isinstance(response, list):
            times = response
        else:
            times = []

        logger.info("Available times for %s: %s", appointment_date, times)
        return times

    async def reschedule(self, appointment_date: str, appointment_time: str) -> bool:
        """
        Reschedule the appointment to the given date and time.

        Returns True if successful.
        """
        await self._ensure_signed_in()
        page = self._page
        assert page is not None

        logger.info("Attempting to reschedule to %s at %s...", appointment_date, appointment_time)

        # Navigate to the reschedule page
        await page.goto(self.settings.reschedule_url, wait_until="domcontentloaded")
        await self._random_delay(2, 4)

        # Get the CSRF token
        csrf_token = await page.evaluate(
            """() => {
                const meta = document.querySelector('meta[name="csrf-token"]');
                return meta ? meta.getAttribute('content') : null;
            }"""
        )

        if not csrf_token:
            raise RuntimeError("Could not find CSRF token for reschedule")

        # Submit reschedule via API
        response = await page.evaluate(
            """async ({url, date, time, facilityId, csrfToken}) => {
                const formData = new URLSearchParams();
                formData.append('utf8', '✓');
                formData.append('authenticity_token', csrfToken);
                formData.append('appointments[consulate_appointment][facility_id]', facilityId);
                formData.append('appointments[consulate_appointment][date]', date);
                formData.append('appointments[consulate_appointment][time]', time);
                formData.append('confirmed', 'true');

                const resp = await fetch(url, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRF-Token': csrfToken,
                    },
                    body: formData.toString(),
                });

                return { status: resp.status, ok: resp.ok, text: await resp.text() };
            }""",
            {
                "url": self.settings.reschedule_url,
                "date": appointment_date,
                "time": appointment_time,
                "facilityId": str(self.settings.facility_id),
                "csrfToken": csrf_token,
            },
        )

        if response.get("ok"):
            logger.info("✅ Successfully rescheduled to %s at %s!", appointment_date, appointment_time)
            return True
        else:
            logger.error(
                "Reschedule failed: HTTP %s — %s",
                response.get("status"),
                response.get("text", "")[:300],
            )
            return False
