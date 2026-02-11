"""Playwright persistent browser context for WAAS automation.

Uses a persistent user data directory so login sessions survive across runs.
The user logs in manually once, then the script re-uses that session.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

from hmha import selectors

logger = logging.getLogger("hmha")

WAAS_URL = "https://www.workatastartup.com"
LOGIN_URL = "https://www.workatastartup.com/companies/jobs"


class BrowserManager:
    """Manages a persistent Chromium browser context."""

    def __init__(
        self,
        user_data_dir: str = "browser_data",
        headless: bool = False,
        slow_mo: int = 50,
    ):
        self._user_data_dir = str(Path(user_data_dir).resolve())
        self._headless = headless
        self._slow_mo = slow_mo
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def launch(self) -> Page:
        """Launch persistent Chromium context and return the active page."""
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            self._user_data_dir,
            headless=self._headless,
            slow_mo=self._slow_mo,
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        # Use the first page or create one
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        logger.info("Browser launched (persistent context: %s)", self._user_data_dir)
        return self._page

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not launched. Call launch() first.")
        return self._page

    async def is_logged_in(self) -> bool:
        """Navigate to WAAS and check for authenticated UI elements."""
        await self._page.goto(WAAS_URL, wait_until="domcontentloaded")
        try:
            await self._page.wait_for_selector(
                selectors.LOGGED_IN_INDICATOR, timeout=5000
            )
            return True
        except Exception:
            return False

    async def wait_for_manual_login(self, timeout_minutes: int = 5) -> bool:
        """Open WAAS and wait for the user to log in manually.

        Polls for the logged-in indicator every 2 seconds.
        Returns True if login detected within the timeout.
        """
        logger.info("Please log in to WAAS in the browser window...")
        await self._page.goto(LOGIN_URL, wait_until="domcontentloaded")

        deadline = asyncio.get_event_loop().time() + (timeout_minutes * 60)
        while asyncio.get_event_loop().time() < deadline:
            try:
                await self._page.wait_for_selector(
                    selectors.LOGGED_IN_INDICATOR, timeout=2000
                )
                logger.info("Login detected!")
                return True
            except Exception:
                await asyncio.sleep(2)

        logger.error("Login timeout after %d minutes.", timeout_minutes)
        return False

    async def check_for_captcha(self) -> bool:
        """Return True if a CAPTCHA or bot challenge is detected on the page."""
        for selector in selectors.CAPTCHA_INDICATORS:
            try:
                el = await self._page.query_selector(selector)
                if el:
                    return True
            except Exception:
                continue
        return False

    async def handle_captcha(self) -> None:
        """Pause and wait for the user to solve a CAPTCHA manually."""
        logger.warning("Bot detection triggered! Please solve the CAPTCHA in the browser.")
        input("Press Enter after solving the CAPTCHA to continue...")

    async def close(self) -> None:
        """Gracefully close the browser context."""
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed.")
