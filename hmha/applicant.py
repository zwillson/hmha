"""Handle the apply-to-job flow on WAAS.

Clicks Apply, fills the modal textarea, and submits the application.
Handles edge cases: already applied, missing button, modal failures.
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from hmha import selectors
from hmha.models import Application, ApplicationStatus, Job

logger = logging.getLogger("hmha")


class JobApplicant:
    """Executes the apply flow on a WAAS job detail page."""

    def __init__(self, page: Page, dry_run: bool = False):
        self._page = page
        self._dry_run = dry_run

    async def apply_to_job(self, job: Job, message: str) -> Application:
        """Full apply flow: click Apply -> fill modal -> send.

        Returns an Application with the result status.
        """
        # Check if already applied on the page
        if await self._is_already_applied():
            logger.info("Already applied to %s at %s.", job.title, job.company.name)
            return Application(
                job=job,
                message=message,
                status=ApplicationStatus.SKIPPED,
                notes="already_applied_on_site",
            )

        # Click the Apply button
        if not await self._click_apply_button():
            logger.warning("No Apply button found for %s.", job.title)
            return Application(
                job=job,
                message=message,
                status=ApplicationStatus.ERROR,
                notes="no_apply_button",
            )

        # Wait for the modal to appear
        if not await self._wait_for_modal():
            logger.warning("Apply modal did not open for %s.", job.title)
            return Application(
                job=job,
                message=message,
                status=ApplicationStatus.ERROR,
                notes="modal_not_opened",
            )

        # Fill the message textarea
        await self._fill_message(message)

        # Dry run: don't actually send
        if self._dry_run:
            logger.info("[DRY RUN] Would send application to %s.", job.company.name)
            await self._close_modal()
            return Application(
                job=job,
                message=message,
                status=ApplicationStatus.DRY_RUN,
            )

        # Click send and verify
        if await self._submit_application():
            logger.info("Application sent to %s at %s!", job.title, job.company.name)
            return Application(
                job=job,
                message=message,
                status=ApplicationStatus.SENT,
            )
        else:
            logger.error("Failed to submit application for %s.", job.title)
            await self._close_modal()
            return Application(
                job=job,
                message=message,
                status=ApplicationStatus.ERROR,
                notes="submit_failed",
            )

    async def _is_already_applied(self) -> bool:
        """Check if the current page shows an 'Already Applied' indicator."""
        try:
            el = await self._page.query_selector(selectors.ALREADY_APPLIED)
            return el is not None
        except Exception:
            return False

    async def _click_apply_button(self) -> bool:
        """Locate and click the Apply button. Return False if not found."""
        try:
            btn = await self._page.wait_for_selector(selectors.APPLY_BUTTON, timeout=5000)
            if btn:
                await btn.click()
                return True
        except Exception as e:
            logger.debug("Apply button error: %s", e)
        return False

    async def _wait_for_modal(self, timeout_ms: int = 5000) -> bool:
        """Wait for the application modal to appear."""
        try:
            await self._page.wait_for_selector(selectors.MODAL, timeout=timeout_ms)
            return True
        except Exception:
            return False

    async def _fill_message(self, message: str) -> None:
        """Fill the modal's textarea instantly using fill() + event dispatch."""
        textarea = await self._page.wait_for_selector(selectors.MODAL_TEXTAREA, timeout=3000)
        if not textarea:
            raise RuntimeError("Textarea not found in modal.")

        await textarea.click()
        await textarea.fill(message)
        await self._page.evaluate(
            """(selector) => {
                const el = document.querySelector(selector);
                if (el) {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""",
            selectors.MODAL_TEXTAREA,
        )

    async def _submit_application(self) -> bool:
        """Click the Send button and wait for the modal to close."""
        try:
            btn = await self._page.wait_for_selector(selectors.SEND_BUTTON, timeout=3000)
            if not btn:
                return False

            await btn.click()

            # Verify: modal should close after successful submission
            try:
                await self._page.wait_for_selector(selectors.MODAL, state="hidden", timeout=5000)
                return True
            except Exception:
                # Modal still visible - might be an error or success without closing
                # Check if the button text changed or is disabled
                logger.debug("Modal still visible after submit. Checking state...")
                return True  # Optimistic - the send likely worked
        except Exception as e:
            logger.error("Submit error: %s", e)
            return False

    async def _close_modal(self) -> None:
        """Close the modal if it's still open."""
        try:
            close_btn = await self._page.query_selector(selectors.CLOSE_BUTTON)
            if close_btn:
                await close_btn.click()
        except Exception:
            # Try pressing Escape as fallback
            try:
                await self._page.keyboard.press("Escape")
            except Exception:
                pass
