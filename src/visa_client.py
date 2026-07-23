"""Browser-based client for ais.usvisa-info.com using Playwright."""

from __future__ import annotations

import asyncio
import logging
from html.parser import HTMLParser
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    async_playwright,
)
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import Settings

logger = logging.getLogger("visa_scheduler.client")

SCREENSHOTS_DIR = Path("logs/screenshots")


class CsrfTokenParser(HTMLParser):
    """Extract Rails' CSRF token without keeping a renderer page alive."""

    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != "meta":
            return
        attributes = dict(attrs)
        if attributes.get("name") == "csrf-token":
            self.token = attributes.get("content")


class BrowserSessionError(RuntimeError):
    """Base class for errors that require re-establishing the browser session."""


class LoginError(BrowserSessionError):
    """Sign-in failed; the browser session must be restarted."""


class SessionExpiredError(BrowserSessionError):
    """An authenticated request was rejected (401/403); the session is stale."""

# Realistic user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


@dataclass
class FacilityResult:
    """Result of checking a single facility."""

    facility_id: int
    facility_name: str
    dates: list[str] = field(default_factory=list)
    earliest_date: str | None = None
    error: str | None = None


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
        """Launch browser and create a context.

        The "already started" guard relies on close() clearing every handle even
        when a close step fails, and on this method leaving no handles behind if
        it raises partway through. If either invariant breaks, a later start()
        would wedge on this guard forever.
        """
        if any((self._playwright, self._browser, self._context, self._page)):
            raise RuntimeError("Browser is already started; call close() before start()")

        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        try:
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
        except BaseException:
            # Release any partially-created resources so we don't leak a live
            # browser/driver and so the guard above stays satisfiable. Catch
            # BaseException (not just Exception) so a CancelledError raised
            # mid-startup still triggers cleanup. Never let a cleanup failure
            # mask the original launch error.
            try:
                await self.close()
            except Exception as cleanup_error:
                logger.warning("Cleanup after failed start was incomplete: %s", cleanup_error)
            raise

        logger.info("Browser started (headless=%s, UA=%s)", self.settings.headless, user_agent[:50])

    async def close(self) -> None:
        """Clean up all browser resources, even if one cleanup step fails."""
        context = self._context
        browser = self._browser
        playwright = self._playwright

        # Clear references before awaiting cleanup so a failed close cannot leave
        # stale handles that are later overwritten by start().
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._signed_in = False

        errors: list[tuple[str, Exception]] = []
        for resource_name, resource, close_method in [
            ("browser context", context, "close"),
            ("browser", browser, "close"),
            ("Playwright", playwright, "stop"),
        ]:
            if resource is None:
                continue
            try:
                await getattr(resource, close_method)()
            except Exception as exc:
                errors.append((resource_name, exc))
                logger.warning("Failed to close %s: %s", resource_name, exc)

        if errors:
            failed_resources = ", ".join(name for name, _ in errors)
            raise RuntimeError(f"Failed to close: {failed_resources}") from errors[0][1]

        logger.info("Browser closed")

    async def _random_delay(self, min_sec: float = 1.0, max_sec: float = 3.0) -> None:
        """Human-like random delay."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def _save_screenshot(self, name: str) -> None:
        """Save a screenshot for debugging."""
        if self._page:
            path = SCREENSHOTS_DIR / f"{name}.png"
            await self._page.screenshot(path=str(path))
            logger.info("Screenshot saved: %s", path)

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

        # The site's styled checkbox hides the native input. A successful click
        # on its label/wrapper does not necessarily mean that the input changed,
        # so verify the native state before submitting the form.
        checkbox = page.locator(
            'input#policy_confirmed, input[name="policy_confirmed"]'
        ).first
        checkbox_checked = False

        if await checkbox.count() > 0:
            checkbox_checked = await checkbox.is_checked()

            if not checkbox_checked:
                for selector in [
                    'label[for="policy_confirmed"]',
                    'label.icheckbox',
                    '.icheckbox',
                    'div.icheckbox',
                ]:
                    el = page.locator(selector)
                    if await el.count() == 0:
                        continue
                    try:
                        await el.first.click()
                    except PlaywrightError:
                        continue
                    checkbox_checked = await checkbox.is_checked()
                    if checkbox_checked:
                        logger.info("Checked policy checkbox via: %s", selector)
                        break

            if not checkbox_checked:
                try:
                    # check() is idempotent, unlike click(), and force=True
                    # supports the hidden native input used by the site.
                    await checkbox.check(force=True)
                    checkbox_checked = await checkbox.is_checked()
                    if checkbox_checked:
                        logger.info("Checked policy checkbox via native input")
                except PlaywrightError:
                    pass

        if not checkbox_checked:
            await self._save_screenshot("checkbox_not_checked")
            raise LoginError(
                "Login failed: policy checkbox could not be checked. "
                "Screenshot saved to logs/screenshots/checkbox_not_checked.png"
            )

        await self._random_delay(0.3, 1.0)

        # Submit
        logger.info("Submitting login form...")
        submit_btn = page.locator('input[type="submit"][name="commit"]')
        await submit_btn.click()

        # Wait for navigation after login
        await page.wait_for_load_state("domcontentloaded")
        await self._random_delay(2, 4)

        # Check if login succeeded
        if "sign_in" in page.url:
            await self._save_screenshot("login_failed")

            error = page.locator(".flash-container .alert, .error-message")
            if await error.count() > 0:
                error_text = await error.first.inner_text()
                raise LoginError(f"Login failed: {error_text.strip()}")
            raise LoginError(
                "Login failed: still on sign-in page. "
                "Screenshot saved to logs/screenshots/login_failed.png"
            )

        self._signed_in = True
        logger.info("✅ Successfully signed in (URL: %s)", page.url)

        # APIRequestContext shares this context's cookie jar, so the renderer is
        # no longer needed after authentication. Recreate a page only when a new
        # login is required.
        self._page = None
        try:
            await page.close()
        except PlaywrightError as exc:
            self._signed_in = False
            raise BrowserSessionError(f"Failed to release login page: {exc}") from exc
        logger.info("Login page closed; continuing with the context request client")

    async def _ensure_signed_in(self) -> None:
        """Ensure we have an active session, creating a login page on demand."""
        if self._signed_in:
            return

        context = self._context
        if context is None:
            raise BrowserSessionError("Browser context is not available")

        if self._page is None:
            try:
                self._page = await context.new_page()
            except PlaywrightError as exc:
                raise BrowserSessionError(f"Failed to create login page: {exc}") from exc

        try:
            await self.sign_in()
        except BrowserSessionError:
            raise
        except Exception as exc:
            self._signed_in = False
            raise LoginError(f"Login failed: {exc}") from exc

    async def _fetch_json(self, url: str) -> dict | list:
        """Fetch JSON through the context request client, which shares cookies."""
        context = self._context
        assert context is not None, "Browser not started. Call start() first."

        try:
            response = await context.request.get(
                url,
                headers={
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
        except PlaywrightError as exc:
            self._signed_in = False
            raise BrowserSessionError(f"Browser request failed: {exc}") from exc

        try:
            if response.status in (401, 403) or "sign_in" in response.url:
                self._signed_in = False
                raise SessionExpiredError(
                    f"Session expired (HTTP {response.status})"
                )

            if not response.ok:
                error_text = (await response.text())[:200]
                raise RuntimeError(
                    f"API error: HTTP {response.status} — {error_text}"
                )

            try:
                result = await response.json()
            except (ValueError, PlaywrightError) as exc:
                content_type = response.headers.get("content-type", "")
                if "text/html" in content_type:
                    self._signed_in = False
                    raise SessionExpiredError(
                        "Session expired: API returned HTML instead of JSON"
                    ) from exc
                raise RuntimeError("API returned invalid JSON") from exc

            return result
        finally:
            # APIRequestContext retains response bodies until they are disposed
            # or the entire context closes. Dispose eagerly in this polling loop.
            await response.dispose()

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_available_dates(self, facility_id: int) -> list[str]:
        """
        Fetch available appointment dates for a single facility.

        Returns a sorted list of date strings in YYYY-MM-DD format.
        """
        await self._ensure_signed_in()

        facility_name = self.settings.facility_name(facility_id)
        logger.info("Fetching available dates for %s (ID: %d)...", facility_name, facility_id)
        await self._random_delay(1, 2)

        url = self.settings.appointments_url(facility_id)
        response = await self._fetch_json(url)

        if not isinstance(response, list):
            self._signed_in = False
            raise RuntimeError(f"Unexpected response: {str(response)[:200]}")

        dates = sorted([entry["date"] for entry in response if "date" in entry])
        logger.info(
            "%s: %d dates available%s",
            facility_name,
            len(dates),
            f" (earliest: {dates[0]})" if dates else "",
        )
        return dates

    async def get_all_facility_dates(self) -> list[FacilityResult]:
        """
        Check all configured facilities sequentially.

        Adds a random delay between each facility to avoid detection.
        Returns a list of FacilityResult, one per facility.
        """
        results: list[FacilityResult] = []

        for i, facility_id in enumerate(self.settings.facility_id_list):
            facility_name = self.settings.facility_name(facility_id)

            # Small delay between facilities (not before the first one)
            if i > 0:
                await self._random_delay(2, 5)

            try:
                dates = await self.get_available_dates(facility_id)
                result = FacilityResult(
                    facility_id=facility_id,
                    facility_name=facility_name,
                    dates=dates,
                    earliest_date=dates[0] if dates else None,
                )
            except BrowserSessionError:
                # Auth/session failures are not per-facility problems — the whole
                # browser session is dead. Propagate so the caller can restart
                # instead of masking it as a facility result (which would reset
                # the error counter and skip the restart path).
                raise
            except Exception as e:
                logger.error("Error checking %s: %s", facility_name, e)
                result = FacilityResult(
                    facility_id=facility_id,
                    facility_name=facility_name,
                    error=str(e),
                )

            results.append(result)

        return results

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_available_times(self, facility_id: int, appointment_date: str) -> list[str]:
        """Fetch available times for a specific facility and date."""
        await self._ensure_signed_in()

        url = (
            f"{self.settings.appointment_times_url(facility_id)}"
            f"?date={appointment_date}&appointments[expedite]=false"
        )

        facility_name = self.settings.facility_name(facility_id)
        logger.info("Fetching times for %s on %s...", facility_name, appointment_date)
        await self._random_delay(1, 2)

        response = await self._fetch_json(url)

        if isinstance(response, dict) and "available_times" in response:
            times = response["available_times"]
        elif isinstance(response, dict) and "business_times" in response:
            times = response["business_times"]
        elif isinstance(response, list):
            times = response
        else:
            times = []

        logger.info("Available times for %s on %s: %s", facility_name, appointment_date, times)
        return times

    async def reschedule(
        self, facility_id: int, appointment_date: str, appointment_time: str
    ) -> bool:
        """
        Reschedule the appointment to the given facility, date, and time.

        Returns True if successful.
        """
        await self._ensure_signed_in()
        context = self._context
        assert context is not None

        facility_name = self.settings.facility_name(facility_id)
        logger.info(
            "Attempting to reschedule to %s on %s at %s...",
            facility_name,
            appointment_date,
            appointment_time,
        )

        # Fetch the reschedule form without creating a renderer page.
        await self._random_delay(2, 4)
        form_response = await context.request.get(
            self.settings.reschedule_url,
            headers={"Accept": "text/html"},
        )
        try:
            if form_response.status in (401, 403) or "sign_in" in form_response.url:
                self._signed_in = False
                raise SessionExpiredError(
                    f"Session expired (HTTP {form_response.status})"
                )
            if not form_response.ok:
                raise RuntimeError(
                    f"Could not load reschedule form: HTTP {form_response.status}"
                )

            parser = CsrfTokenParser()
            parser.feed(await form_response.text())
            csrf_token = parser.token
        finally:
            await form_response.dispose()

        if not csrf_token:
            raise RuntimeError("Could not find CSRF token for reschedule")

        # Submit reschedule through the cookie-sharing request context.
        response = await context.request.put(
            self.settings.reschedule_url,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": csrf_token,
            },
            form={
                "utf8": "✓",
                "authenticity_token": csrf_token,
                "appointments[consulate_appointment][facility_id]": str(facility_id),
                "appointments[consulate_appointment][date]": appointment_date,
                "appointments[consulate_appointment][time]": appointment_time,
                "confirmed": "true",
            },
        )
        try:
            response_text = await response.text()
            if response.status in (401, 403) or "sign_in" in response.url:
                self._signed_in = False
                raise SessionExpiredError(
                    f"Session expired (HTTP {response.status})"
                )
            if response.ok:
                logger.info(
                    "✅ Successfully rescheduled to %s on %s at %s!",
                    facility_name,
                    appointment_date,
                    appointment_time,
                )
                return True

            logger.error(
                "Reschedule failed: HTTP %s — %s",
                response.status,
                response_text[:300],
            )
            return False
        finally:
            await response.dispose()
