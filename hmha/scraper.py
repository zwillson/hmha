"""Scrape job listings and detail pages from WAAS.

Handles the React SPA: scrolls to load jobs, extracts job cards,
and navigates to individual job pages for full details.
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page

from hmha import selectors
from hmha.models import Company, Founder, Job
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
        await random_delay(0.5, 1)

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
        await random_delay(0.3, 0.8)

        job_id = self._extract_job_id(job_url)

        # Extract the page's full text content for parsing
        page_text = await self._page.inner_text("body")

        # --- Company name: try multiple strategies ---
        company_name = ""

        # Strategy 1: URL pattern /companies/NAME/jobs/...
        url_match = re.search(r"/companies/([^/]+)", job_url)
        if url_match:
            # Convert slug to title case: "hypercubic" -> "Hypercubic"
            company_name = url_match.group(1).replace("-", " ").title()

        # Strategy 2: breadcrumb pattern "Companies / Name"
        if not company_name:
            bc_match = re.search(r"Companies\s*/\s*(.+?)(?:\s*\(|\s*/|\s*\n)", page_text)
            if bc_match:
                company_name = bc_match.group(1).strip()

        # Strategy 3: look for company name near YC batch
        if not company_name:
            batch_match = re.search(r"([A-Z][A-Za-z0-9 ]+)\s*\([WS]\d{2}\)", page_text)
            if batch_match:
                company_name = batch_match.group(1).strip()

        # Strategy 4: first h1 (but filter out generic text)
        if not company_name:
            h1_text = await self._safe_text("h1")
            if h1_text and h1_text.lower() not in ("companies", "jobs", "apply"):
                company_name = h1_text

        # --- Job title: try selectors and URL ---
        title = ""
        # Try getting from a heading that isn't the company name
        all_h1s = await self._page.query_selector_all("h1, h2")
        for heading in all_h1s:
            text = (await heading.inner_text()).strip()
            if text and text != company_name and len(text) < 100:
                title = text
                break

        # Fallback: extract from URL slug
        if not title:
            title_match = re.search(r"/jobs/[^-]+-(.+)$", job_url)
            if title_match:
                title = title_match.group(1).replace("-", " ").title()

        # --- YC batch ---
        yc_batch = self._extract_yc_batch(page_text)

        # --- Sections: use improved extraction ---
        company_description = self._extract_section(
            page_text, ["About", "About the company", "About us", "Who we are", "What we do"]
        )
        # Filter out garbage (nav menus, breadcrumbs leaking in)
        company_description = self._clean_scraped_text(company_description)

        description = self._extract_section(
            page_text, ["About the role", "What you'll do", "The role", "Role description",
                        "Job description", "Description", "Responsibilities"]
        )
        description = self._clean_scraped_text(description)

        requirements = self._extract_section(
            page_text, ["Requirements", "Qualifications", "What we're looking for",
                        "You should have", "What you bring", "Skills", "Minimum qualifications"]
        )
        requirements = self._clean_scraped_text(requirements)

        culture_notes = self._extract_section(
            page_text, ["Culture", "Values", "Who you are", "You are",
                        "Ideal candidate", "What we offer", "Benefits", "Perks"]
        )
        culture_notes = self._clean_scraped_text(culture_notes)

        # --- Metadata: location, salary, job type ---
        meta = await self._extract_metadata(page_text)

        # Also try extracting company size and industry from page text
        company_size = self._extract_company_size(page_text)
        company_industry = self._extract_industry(page_text)

        # --- Founders ---
        founders = await self._extract_founders()

        # --- Company website ---
        company_website = await self._extract_company_website(company_name)

        company = Company(
            name=company_name or "Unknown",
            description=company_description,
            yc_batch=yc_batch,
            industry=company_industry,
            size=company_size,
            url=job_url,
            website=company_website,
            founders=founders,
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
            await random_delay(0.3, 0.8)

            # Try clicking any "load more" or "show more" button
            for btn_selector in [selectors.LOAD_MORE_BUTTON, selectors.SHOW_MORE_JOBS]:
                try:
                    btn = await self._page.query_selector(btn_selector)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await random_delay(0.3, 0.8)
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

    def _extract_yc_batch(self, page_text: str) -> str:
        """Extract YC batch like (W24) or (S21) from page text."""
        match = re.search(r"\(([WS]\d{2})\)", page_text)
        return match.group(1) if match else ""

    def _extract_section(self, page_text: str, headers: list[str]) -> str:
        """Extract a section of text following one of the given headers.

        Tries multiple regex strategies to handle different page layouts.
        """
        for header in headers:
            # Strategy 1: Header on its own line, content follows until next header-like line
            pattern = re.compile(
                rf"(?:^|\n)\s*{re.escape(header)}\s*\n([\s\S]*?)(?=\n\s*(?:About|Requirements|Qualifications|Culture|Values|Benefits|Perks|What you|The role|Who you|Skills|Responsibilities|Apply|Already)\b|\Z)",
                re.IGNORECASE,
            )
            match = pattern.search(page_text)
            if match:
                text = match.group(1).strip()
                if text and len(text) > 10:
                    return text[:1000] if len(text) > 1000 else text

            # Strategy 2: Header followed by colon or as part of a line
            pattern2 = re.compile(
                rf"{re.escape(header)}\s*:?\s*\n?([\s\S]*?)(?=\n\s*(?:About|Requirements|Qualifications|Culture|Values|Benefits|What you|The role|Who you|Skills|Apply)\b|\Z)",
                re.IGNORECASE,
            )
            match2 = pattern2.search(page_text)
            if match2:
                text = match2.group(1).strip()
                if text and len(text) > 10:
                    return text[:1000] if len(text) > 1000 else text

        return ""

    async def _extract_metadata(self, page_text: str = "") -> dict[str, str]:
        """Extract location, job type, and salary from the page.

        Tries DOM elements first, then falls back to regex on page text.
        """
        meta: dict[str, str] = {}

        # Strategy 1: Try various DOM selectors for metadata chips/tags
        chip_selectors = [
            "span[class*='tag']", "div[class*='chip']", "div[class*='detail']",
            "span[class*='label']", "div[class*='meta']", "span[class*='badge']",
            "li[class*='detail']", "div[class*='info'] span",
        ]
        try:
            for sel in chip_selectors:
                chips = await self._page.query_selector_all(sel)
                for chip in chips:
                    text = (await chip.inner_text()).strip()
                    if not text or len(text) > 100:
                        continue
                    lower = text.lower()
                    if not meta.get("location") and any(
                        loc in lower for loc in [
                            "remote", "san francisco", "sf", "new york", "nyc",
                            "los angeles", "la", "austin", "seattle", "boston",
                            "chicago", "denver", "miami", "india", "london",
                            "berlin", "toronto", "paris", "bangalore",
                        ]
                    ):
                        meta["location"] = text
                    elif not meta.get("job_type") and any(
                        t in lower for t in ["full-time", "part-time", "intern", "contract", "fulltime"]
                    ):
                        meta["job_type"] = text
                    elif not meta.get("salary") and ("$" in text or re.search(r"\d+k", lower)):
                        meta["salary"] = text
        except Exception as e:
            logger.debug("DOM metadata extraction failed: %s", e)

        # Strategy 2: Regex on full page text for location
        if not meta.get("location"):
            loc_patterns = [
                r"(?:Location|Based in|Office)[:\s]+([^\n]{3,50})",
                r"((?:San Francisco|New York|Remote|Austin|Seattle|Boston|Los Angeles|Chicago)[^\n]{0,30})",
            ]
            for pat in loc_patterns:
                match = re.search(pat, page_text, re.IGNORECASE)
                if match:
                    meta["location"] = match.group(1).strip()
                    break

        # Strategy 3: Regex for salary
        if not meta.get("salary"):
            salary_match = re.search(r"\$[\d,]+\s*[-–]\s*\$[\d,]+(?:\s*(?:per year|/yr|annually))?", page_text)
            if salary_match:
                meta["salary"] = salary_match.group(0)

        return meta

    def _extract_company_size(self, page_text: str) -> str:
        """Try to extract company size from page text."""
        patterns = [
            r"(\d+[-–]\d+)\s*(?:employees|people|team members)",
            r"(?:Team size|Company size|Size)[:\s]+(\d+[-–]\d+|\d+\+?)",
            r"(\d+\+?)\s*(?:employees|people|engineers)",
        ]
        for pat in patterns:
            match = re.search(pat, page_text, re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    def _extract_industry(self, page_text: str) -> str:
        """Try to extract industry/category from page text."""
        patterns = [
            r"(?:Industry|Sector|Category|Space)[:\s]+([^\n]{3,50})",
        ]
        for pat in patterns:
            match = re.search(pat, page_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # Try to match common YC industry tags
        industries = [
            "B2B", "SaaS", "Fintech", "Healthcare", "AI", "Developer Tools",
            "Infrastructure", "Security", "Education", "Consumer", "Biotech",
            "Climate", "Real Estate", "Logistics", "Legal", "Insurance",
        ]
        found = []
        for ind in industries:
            if re.search(rf"\b{re.escape(ind)}\b", page_text, re.IGNORECASE):
                found.append(ind)
        return ", ".join(found[:3]) if found else ""

    def _clean_scraped_text(self, text: str) -> str:
        """Remove nav menu garbage, breadcrumbs, and junk from scraped text."""
        if not text:
            return ""

        # Known garbage patterns that leak from nav menus / footers
        garbage_words = [
            "Companies", "Library", "Partners", "Resources", "Startup Jobs",
            "Sign up", "Log in", "Sign in", "Privacy", "Terms",
            "Connect directly with founders", "Y Combinator",
        ]

        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip empty lines and lines that are just nav items
            if not stripped:
                continue
            if stripped in garbage_words:
                continue
            # Skip very short lines that look like nav links (single words < 15 chars with no spaces)
            if len(stripped) < 15 and " " not in stripped and stripped.isalpha():
                # Could be a nav item — skip unless it looks like real content
                if stripped.lower() in ("remote", "onsite", "hybrid"):
                    cleaned_lines.append(stripped)
                continue
            cleaned_lines.append(stripped)

        result = "\n".join(cleaned_lines).strip()

        # If after cleaning we have almost nothing, return empty
        if len(result) < 15:
            return ""
        return result

    async def _extract_founders(self) -> list[Founder]:
        """Try to extract founder names and LinkedIn URLs from the page."""
        founders: list[Founder] = []

        try:
            # Strategy 1: Look for LinkedIn links with founder-like context
            all_links = await self._page.query_selector_all("a[href*='linkedin.com/in/']")
            for link in all_links:
                href = await link.get_attribute("href") or ""
                name = (await link.inner_text()).strip()

                # Filter out generic LinkedIn links (too short, or our own link)
                if not name or len(name) < 3 or len(name) > 50:
                    continue
                # Skip if it looks like a button or generic text
                if name.lower() in ("linkedin", "connect", "view profile", "follow"):
                    continue

                founders.append(Founder(name=name, linkedin=href))

            # Strategy 2: Look for text patterns like "Founded by X" or "Founders: X, Y"
            if not founders:
                page_text = await self._page.inner_text("body")
                founder_patterns = [
                    r"(?:Founded by|Founder[s]?)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+(?:\s*(?:,|and)\s*[A-Z][a-z]+ [A-Z][a-z]+)*)",
                    r"(?:CEO|CTO|Co-founder)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)",
                ]
                seen_names: set[str] = set()
                for pat in founder_patterns:
                    matches = re.findall(pat, page_text)
                    for match_text in matches:
                        # Split "Alice Smith and Bob Jones" or "Alice Smith, Bob Jones"
                        names = re.split(r"\s*(?:,|and)\s*", match_text)
                        for name in names:
                            name = name.strip()
                            if name and name not in seen_names and len(name.split()) >= 2:
                                seen_names.add(name)
                                founders.append(Founder(name=name))

        except Exception as e:
            logger.debug("Founder extraction failed: %s", e)

        return founders[:5]  # Cap at 5 founders

    async def _extract_company_website(self, company_name: str) -> str:
        """Try to extract the company's website URL from the page."""
        try:
            # Strategy 1: Look for explicit website links
            all_links = await self._page.query_selector_all("a[href]")
            for link in all_links:
                text = (await link.inner_text()).strip().lower()
                href = await link.get_attribute("href") or ""

                # Look for links labeled "website", "site", or the company domain
                if text in ("website", "site", "homepage", "visit site", "visit website"):
                    return href

                # Link text that looks like a domain
                if re.match(r"^https?://(?!.*(?:linkedin|twitter|github|ycombinator|workatastartup))", href):
                    if text and ("." in text) and len(text) < 50:
                        return href

            # Strategy 2: Look for external links that aren't social media
            page_text = await self._page.inner_text("body")
            url_match = re.search(
                r"(https?://(?:www\.)?(?!linkedin|twitter|github|ycombinator|workatastartup)[a-z0-9-]+\.[a-z]{2,}(?:/[^\s]*)?)",
                page_text,
                re.IGNORECASE,
            )
            if url_match:
                return url_match.group(1)

            # Strategy 3: Construct YC company page URL
            if company_name and company_name != "Unknown":
                slug = company_name.lower().replace(" ", "-")
                return f"https://www.ycombinator.com/companies/{slug}"

        except Exception as e:
            logger.debug("Website extraction failed: %s", e)

        return ""

    @staticmethod
    def _extract_job_id(url: str) -> str | None:
        """Extract numeric job ID from a URL like /jobs/12345."""
        match = re.search(r"/jobs/(\d+)", url)
        return match.group(1) if match else None
