"""Scrape job listings and detail pages from WAAS.

Handles the React SPA: scrolls to load jobs, extracts job cards,
and navigates to individual job pages for full details.
"""

from __future__ import annotations

import asyncio
import logging
import re

from playwright.async_api import Page

from hmha import selectors
from hmha.models import Company, Founder, Job

logger = logging.getLogger("hmha")


class JobScraper:
    """Discovers and scrapes jobs from the WAAS listing and detail pages."""

    def __init__(self, page: Page):
        self._page = page

    async def scrape_job_listings(self, url: str, max_jobs: int = 100) -> list[dict]:
        """Navigate to filtered jobs URL and extract job stubs.

        Returns a list of lightweight dicts: {job_id, title, company_name, company_blurb, url}.
        These are used to decide which jobs to visit in detail.

        On the /companies page, the layout is:
          - Company cards, each containing a company name/link + its job postings.
          - Job links are a[href*='/jobs/'] inside each card.
          - Company name can be found by traversing up from the job link
            to find the nearest heading or a[href*='/companies/'] link.

        Filters are applied via URL params (built by filters.py), not by
        interacting with sidebar dropdowns.
        """
        logger.info("Navigating to jobs page: %s", url)
        await self._page.goto(url, wait_until="domcontentloaded")

        # Scroll to load more jobs (the page uses infinite scroll / load-more)
        await self._scroll_to_load_all(max_scrolls=25)

        # Use a single JS call to extract ALL job stubs with their company context.
        # For each job link, we traverse up the DOM to find the parent company card
        # and extract the company name + blurb from it.
        raw_stubs = await self._page.evaluate("""() => {
            const results = [];
            const jobLinks = document.querySelectorAll("a[href*='/jobs/']");

            for (const link of jobLinks) {
                const href = link.getAttribute('href') || '';
                const title = (link.textContent || '').trim();

                if (!href.includes('/jobs/')) continue;

                // Extract company name by traversing up to find the company card
                let companyName = '';
                let companyBlurb = '';
                let node = link;

                // Strategy 1: Look for a[href*='/companies/'] link in an ancestor
                for (let i = 0; i < 15; i++) {
                    node = node.parentElement;
                    if (!node) break;

                    // Look for a company name link (usually links to /companies/slug)
                    if (!companyName) {
                        const compLink = node.querySelector("a[href*='/companies/']");
                        if (compLink) {
                            // The company link text is the company name
                            const name = (compLink.textContent || '').trim();
                            // Filter out long text (probably not just the name)
                            if (name && name.length > 0 && name.length < 80) {
                                companyName = name;
                            }
                            // Also try getting company name from the href slug
                            if (!companyName) {
                                const slugMatch = compLink.href.match(/\\/companies\\/([^/]+)/);
                                if (slugMatch) {
                                    companyName = slugMatch[1].replace(/-/g, ' ');
                                }
                            }
                        }
                    }

                    // Look for a blurb in <p> tags
                    if (!companyBlurb) {
                        const paragraphs = node.querySelectorAll('p');
                        for (const p of paragraphs) {
                            const t = p.textContent.trim();
                            if (t.length > 15 && t.length < 200 && t.includes(' ')
                                && !t.match(/^(fulltime|parttime|intern|remote|contract)/i)) {
                                companyBlurb = t;
                                break;
                            }
                        }
                    }

                    if (companyName && companyBlurb) break;
                }

                // Strategy 2: Extract company name from the href itself
                // URL pattern: /companies/company-slug/jobs/ID
                if (!companyName) {
                    const hrefMatch = href.match(/\\/companies\\/([^/]+)/);
                    if (hrefMatch) {
                        companyName = hrefMatch[1].replace(/-/g, ' ');
                    }
                }

                results.push({
                    href: href,
                    title: title,
                    companyName: companyName,
                    companyBlurb: companyBlurb,
                });
            }
            return results;
        }""")

        logger.info("Found %d job links on listing page.", len(raw_stubs))

        jobs: list[dict] = []
        seen_ids: set[str] = set()

        for stub in raw_stubs[:max_jobs]:
            href = stub.get("href", "")
            title = stub.get("title", "").strip()
            company_name = stub.get("companyName", "").strip()
            company_blurb = stub.get("companyBlurb", "").strip()

            # Extract job ID
            job_id = self._extract_job_id(href)
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Build full URL
            full_url = href if href.startswith("http") else f"https://www.workatastartup.com{href}"

            # Title-case the company name if it looks like a slug
            if company_name and "-" not in company_name and company_name[0].islower():
                company_name = company_name.title()

            jobs.append({
                "job_id": job_id,
                "title": title,
                "company_name": company_name,
                "company_blurb": company_blurb,
                "url": full_url,
            })

        logger.info("Extracted %d unique job stubs.", len(jobs))
        return jobs

    async def scrape_job_detail(self, job_url: str) -> Job:
        """Navigate to a job detail page and extract full information.

        Returns a fully populated Job dataclass with company info,
        description, requirements, and culture signals.
        """
        logger.info("Scraping job detail: %s", job_url)
        await self._page.goto(job_url, wait_until="domcontentloaded")

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

        # Known section headers that are NOT job titles
        _section_headers = {
            "about", "about us", "about you", "about the company", "about the role",
            "the role", "description", "overview", "requirements",
            "qualifications", "apply", "benefits", "culture", "values",
            "what you'll do", "what we're looking for", "responsibilities",
            "who we are", "who you are", "what you bring",
            "interview process", "other jobs", "similar jobs",
            "our stack", "tech stack", "perks", "compensation",
        }

        # Try getting from a heading that isn't the company name or a section header
        all_h1s = await self._page.query_selector_all("h1, h2")
        for heading in all_h1s:
            text = (await heading.inner_text()).strip()
            if not text or text == company_name or len(text) > 100:
                continue
            if text.lower() in _section_headers:
                continue
            title = text
            break

        # Fallback: extract from URL slug
        # Handles both /jobs/ID-slug-title and /jobs/84041 formats
        if not title:
            title_match = re.search(r"/jobs/[A-Za-z0-9]+-(.+)$", job_url)
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

    async def _scroll_to_load_all(self, max_scrolls: int = 25) -> None:
        """Scroll the page and click 'Load more' to reveal all job cards."""
        for i in range(max_scrolls):
            previous_height = await self._page.evaluate("document.body.scrollHeight")
            await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.0)  # wait for lazy-loaded content to render

            # Try clicking any "load more" or "show more" button
            for btn_selector in [selectors.LOAD_MORE_BUTTON, selectors.SHOW_MORE_JOBS]:
                try:
                    btn = await self._page.query_selector(btn_selector)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(1.5)  # wait for new content after button click
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

        Uses a single JS call to gather all chip/tag text, then filters in Python.
        Validates location text to avoid garbage like 'assistance' or 'compensation'.
        """
        meta: dict[str, str] = {}

        # Known location keywords — only accept text containing these
        _LOCATION_KEYWORDS = [
            "remote", "san francisco", "sf", "new york", "nyc",
            "los angeles", "la", "austin", "seattle", "boston",
            "chicago", "denver", "miami", "india", "london",
            "berlin", "toronto", "paris", "bangalore", "bengaluru",
            "bay area", "palo alto", "mountain view", "sunnyvale",
            "cupertino", "menlo park", "redwood city",
            "washington", "dc", "portland", "atlanta", "dallas",
            "houston", "philadelphia", "san jose", "san diego",
            "united states", "us", "usa", "canada", "uk",
            ", ca", ", ny", ", tx", ", wa",
        ]

        def _is_valid_location(text: str) -> bool:
            """Check if text actually looks like a location."""
            lower = text.lower()
            return any(loc in lower for loc in _LOCATION_KEYWORDS)

        # Single JS call — get all text from metadata-like elements at once
        try:
            chip_texts = await self._page.evaluate("""() => {
                const sels = [
                    "span[class*='tag']", "div[class*='chip']", "div[class*='detail']",
                    "span[class*='label']", "div[class*='meta']", "span[class*='badge']",
                    "li[class*='detail']", "div[class*='info'] span"
                ];
                const texts = [];
                for (const sel of sels) {
                    for (const el of document.querySelectorAll(sel)) {
                        const t = (el.textContent || '').trim();
                        if (t && t.length <= 100) texts.push(t);
                    }
                }
                return texts;
            }""")

            for text in chip_texts:
                lower = text.lower()
                if not meta.get("location") and _is_valid_location(text):
                    meta["location"] = text
                elif not meta.get("job_type") and any(
                    t in lower for t in ["full-time", "part-time", "intern", "contract", "fulltime"]
                ):
                    meta["job_type"] = text
                elif not meta.get("salary") and ("$" in text or re.search(r"\d+k", lower)):
                    meta["salary"] = text
        except Exception as e:
            logger.debug("DOM metadata extraction failed: %s", e)

        # Regex fallback for location — only accept known location patterns
        if not meta.get("location"):
            loc_patterns = [
                # Only match if the captured text contains a known location keyword
                r"(?:Location|Based in|Office)[:\s]+([^\n]{3,50})",
                r"((?:San Francisco|New York|Remote|Austin|Seattle|Boston|Los Angeles|Chicago|Palo Alto|Mountain View)[^\n]{0,30})",
            ]
            for pat in loc_patterns:
                match = re.search(pat, page_text, re.IGNORECASE)
                if match:
                    candidate = match.group(1).strip()
                    if _is_valid_location(candidate):
                        meta["location"] = candidate
                        break

        # Regex fallback for salary
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
        """Try to extract founder names and LinkedIn URLs from the page.

        Uses a single JS call to extract all LinkedIn link data at once (fast).
        """
        founders: list[Founder] = []

        _junk_names = {
            "linkedin", "connect", "view profile", "follow", "similar jobs",
            "apply", "share", "save", "back", "next", "previous", "sign up",
            "log in", "sign in", "view all jobs", "see all jobs", "all jobs",
        }

        try:
            # Single JS call — grab all LinkedIn links' href + textContent at once
            raw = await self._page.evaluate("""() => {
                return Array.from(document.querySelectorAll("a[href*='linkedin.com/in/']"))
                    .map(a => ({ href: a.href, name: (a.textContent || '').trim() }));
            }""")

            seen_hrefs: set[str] = set()
            for item in raw:
                href = item.get("href", "")
                name = item.get("name", "").strip()

                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)

                if not name or len(name) < 3 or len(name) > 50:
                    continue

                name_normalized = " ".join(name.lower().split())
                if name_normalized in _junk_names:
                    continue
                if any(junk in name_normalized for junk in _junk_names):
                    continue

                words = name.split()
                if len(words) < 2 or len(words) > 4:
                    continue
                if not all(w.isalpha() for w in words):
                    continue

                founders.append(Founder(name=name, linkedin=href))

            # Strategy 2: regex fallback on page_text (already extracted earlier)
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
                        names = re.split(r"\s*(?:,|and)\s*", match_text)
                        for name in names:
                            name = name.strip()
                            if name and name not in seen_names and len(name.split()) >= 2:
                                seen_names.add(name)
                                founders.append(Founder(name=name))

        except Exception as e:
            logger.debug("Founder extraction failed: %s", e)

        return founders[:5]

    async def _extract_company_website(self, company_name: str) -> str:
        """Try to extract the company's actual website URL from the page.

        Uses a single JS call to get all link data, then filters in Python (fast).
        """
        _social_domains = (
            "linkedin.com", "twitter.com", "x.com", "github.com",
            "facebook.com", "instagram.com", "youtube.com", "medium.com",
        )
        _excluded_domains = _social_domains + (
            "ycombinator.com", "workatastartup.com", "crunchbase.com",
            "glassdoor.com", "indeed.com", "lever.co", "greenhouse.io",
            "bamboohr.com", "ashbyhq.com", "google.com", "apple.com",
        )

        def _is_excluded(url: str) -> bool:
            lower = url.lower()
            return any(d in lower for d in _excluded_domains)

        def _is_social(url: str) -> bool:
            lower = url.lower()
            return any(d in lower for d in _social_domains)

        try:
            # Single JS call — get all links' href + textContent at once
            raw = await self._page.evaluate("""() => {
                return Array.from(document.querySelectorAll("a[href]"))
                    .map(a => ({ href: a.href, text: (a.textContent || '').trim() }));
            }""")

            # Strategy 1: Icon row — find a non-social link next to a social link
            for i, item in enumerate(raw):
                href = item.get("href", "")
                if not href.startswith("http"):
                    continue

                has_social_neighbour = False
                for offset in (-2, -1, 1, 2):
                    ni = i + offset
                    if 0 <= ni < len(raw):
                        neighbour_href = raw[ni].get("href", "")
                        if _is_social(neighbour_href):
                            has_social_neighbour = True
                            break

                if has_social_neighbour and not _is_excluded(href):
                    return href

            # Strategy 2: Explicitly labeled "website"
            for item in raw:
                text = item.get("text", "").lower()
                href = item.get("href", "")
                if text in ("website", "site", "homepage", "visit site", "visit website"):
                    if href.startswith("http") and not _is_excluded(href):
                        return href

            # Strategy 3: Text looks like a bare domain
            for item in raw:
                text = item.get("text", "")
                href = item.get("href", "")
                if not href.startswith("http") or _is_excluded(href):
                    continue
                if re.match(r"^(?:https?://)?(?:www\.)?[a-z0-9-]+\.[a-z]{2,}/?$", text, re.IGNORECASE):
                    return href

        except Exception as e:
            logger.debug("Website extraction failed: %s", e)

        return ""

    @staticmethod
    def _extract_job_id(url: str) -> str | None:
        """Extract job ID from a URL like /companies/foo/jobs/2B4RxLG-title or /jobs/12345.

        WAAS uses alphanumeric IDs (e.g. 2B4RxLG, 8uytDI0) not just numeric ones.
        The URL pattern is: /jobs/{ID}-{slug} or /jobs/{ID}
        """
        # Match the full alphanumeric ID segment after /jobs/
        match = re.search(r"/jobs/([A-Za-z0-9]+)", url)
        return match.group(1) if match else None
