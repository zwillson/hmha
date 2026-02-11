"""Scrape job listings and detail pages from WAAS.

Handles the React SPA: scrolls to load jobs, extracts job cards,
and navigates to individual job pages for full details.
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page

from hmha import selectors
from hmha.models import Company, Job
from hmha.utils import random_delay

logger = logging.getLogger("hmha")


class JobScraper:
    """Discovers and scrapes jobs from the WAAS listing and detail pages."""

    def __init__(self, page: Page):
        self._page = page

    async def scrape_job_listings(self, url: str, max_jobs: int = 100) -> list[dict]:
        """Navigate to filtered jobs URL and extract job stubs.

        Returns a list of lightweight dicts: {job_id, title, company_name, url}.
        These are used to decide which jobs to visit in detail.
        """
        logger.info("Navigating to jobs page: %s", url)
        await self._page.goto(url, wait_until="domcontentloaded")
        await random_delay(2, 4)

        # Scroll to load more jobs (the page uses infinite scroll / load-more)
        await self._scroll_to_load_all(max_scrolls=15)

        # Extract job links from the page
        job_links = await self._page.query_selector_all(selectors.JOB_ROW)
        logger.info("Found %d job links on listing page.", len(job_links))

        jobs: list[dict] = []
        seen_ids: set[str] = set()

        for link in job_links[:max_jobs]:
            try:
                href = await link.get_attribute("href") or ""
                title = (await link.inner_text()).strip()

                # Extract job ID from URL like /jobs/12345
                job_id = self._extract_job_id(href)
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                # Build full URL
                full_url = href if href.startswith("http") else f"https://www.workatastartup.com{href}"

                jobs.append({
                    "job_id": job_id,
                    "title": title,
                    "url": full_url,
                })
            except Exception as e:
                logger.debug("Failed to parse job link: %s", e)
                continue

        logger.info("Extracted %d unique job stubs.", len(jobs))
        return jobs

    async def scrape_job_detail(self, job_url: str) -> Job:
        """Navigate to a job detail page and extract full information.

        Returns a fully populated Job dataclass with company info,
        description, requirements, and culture signals.
        """
        logger.info("Scraping job detail: %s", job_url)
        await self._page.goto(job_url, wait_until="domcontentloaded")
        await random_delay(1, 3)

        job_id = self._extract_job_id(job_url)

        # Extract the page's full text content for parsing
        page_text = await self._page.inner_text("body")

        # Try to get structured data from the page
        title = await self._safe_text(selectors.JOB_TITLE)
        company_name = await self._extract_company_name(page_text)
        yc_batch = await self._extract_yc_batch(page_text)

        # Scrape the company about section
        company_description = await self._extract_section(
            page_text, ["About", "about the company", "who we are"]
        )

        # Scrape job description and requirements
        description = await self._extract_section(
            page_text, ["About the role", "What you'll do", "Role", "Description"]
        )
        requirements = await self._extract_section(
            page_text, ["Requirements", "Qualifications", "What we're looking for", "You should have"]
        )

        # Extract culture and personality signals
        culture_notes = await self._extract_section(
            page_text, ["Culture", "Values", "Who you are", "You are", "Ideal candidate"]
        )

        # Get location, job type, salary from metadata tags
        meta = await self._extract_metadata()

        company = Company(
            name=company_name or "Unknown",
            description=company_description,
            yc_batch=yc_batch,
            url=job_url,
        )

        return Job(
            job_id=job_id or "",
            title=title or "Unknown Role",
            company=company,
            url=job_url,
            description=description,
            requirements=requirements,
            location=meta.get("location", ""),
            job_type=meta.get("job_type", ""),
            salary_range=meta.get("salary", ""),
            culture_notes=culture_notes,
        )

    async def _scroll_to_load_all(self, max_scrolls: int = 15) -> None:
        """Scroll the page and click 'Load more' to reveal all job cards."""
        for i in range(max_scrolls):
            previous_height = await self._page.evaluate("document.body.scrollHeight")
            await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await random_delay(1, 2)

            # Try clicking any "load more" or "show more" button
            for btn_selector in [selectors.LOAD_MORE_BUTTON, selectors.SHOW_MORE_JOBS]:
                try:
                    btn = await self._page.query_selector(btn_selector)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await random_delay(1, 2)
                except Exception:
                    pass

            new_height = await self._page.evaluate("document.body.scrollHeight")
            if new_height == previous_height:
                logger.debug("No more content to load after %d scrolls.", i + 1)
                break

    async def _safe_text(self, selector: str) -> str:
        """Get inner text of the first matching element, or empty string."""
        try:
            el = await self._page.query_selector(selector)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return ""

    async def _extract_company_name(self, page_text: str) -> str:
        """Pull the company name from the breadcrumb or heading."""
        # Try breadcrumb: "Companies / CompanyName (W24) / Jobs"
        match = re.search(r"Companies\s*/\s*(.+?)\s*\(", page_text)
        if match:
            return match.group(1).strip()

        # Fallback: first h1
        return await self._safe_text("h1")

    async def _extract_yc_batch(self, page_text: str) -> str:
        """Extract YC batch like (W24) or (S21) from page text."""
        match = re.search(r"\(([WS]\d{2})\)", page_text)
        return match.group(1) if match else ""

    async def _extract_section(self, page_text: str, headers: list[str]) -> str:
        """Extract a section of text following one of the given headers.

        Looks for a header keyword and returns the text block after it,
        up to the next header-like line or a reasonable length limit.
        """
        for header in headers:
            pattern = re.compile(
                rf"(?:^|\n)\s*{re.escape(header)}\s*\n([\s\S]*?)(?=\n\s*[A-Z][a-z]{{2,}}|\Z)",
                re.IGNORECASE,
            )
            match = pattern.search(page_text)
            if match:
                text = match.group(1).strip()
                # Limit to ~1000 chars to keep prompts manageable
                return text[:1000] if len(text) > 1000 else text
        return ""

    async def _extract_metadata(self) -> dict[str, str]:
        """Extract location, job type, and salary from page metadata chips/tags."""
        meta: dict[str, str] = {}
        try:
            # These are typically rendered as small tag/chip elements
            chips = await self._page.query_selector_all("span[class*='tag'], div[class*='chip'], div[class*='detail']")
            for chip in chips:
                text = (await chip.inner_text()).strip()
                lower = text.lower()
                if any(loc in lower for loc in ["remote", "san francisco", "new york", "us"]):
                    meta["location"] = text
                elif any(t in lower for t in ["full-time", "part-time", "intern", "contract"]):
                    meta["job_type"] = text
                elif "$" in text or "k" in lower:
                    meta["salary"] = text
        except Exception as e:
            logger.debug("Metadata extraction failed: %s", e)
        return meta

    @staticmethod
    def _extract_job_id(url: str) -> str | None:
        """Extract numeric job ID from a URL like /jobs/12345."""
        match = re.search(r"/jobs/(\d+)", url)
        return match.group(1) if match else None
