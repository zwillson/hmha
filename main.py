#!/usr/bin/env python3
"""HMHA - Automated YC Work at a Startup job applicant.

Usage:
    python main.py --login-only          # First-time login setup
    python main.py --check-selectors     # Verify DOM selectors work
    python main.py --dry-run             # Scrape + generate, don't send
    python main.py                       # Full run with review mode
    python main.py --max-applications 5  # Cap at 5 applications
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from hmha.ai import MessageGenerator
from hmha.applicant import JobApplicant
from hmha.browser import BrowserManager
from hmha.config_loader import load_config
from hmha.filters import build_jobs_url
from hmha.models import Application, ApplicationStatus
from hmha.reviewer import MessageReviewer, ReviewDecision
from hmha.scraper import JobScraper
from hmha.tracker import ApplicationTracker
from hmha.utils import random_delay, setup_logging

logger = logging.getLogger("hmha")


async def run_login_only(browser: BrowserManager) -> None:
    """Open the browser for manual login, then exit."""
    page = await browser.launch()
    if await browser.is_logged_in():
        logger.info("Already logged in! Session is saved.")
    else:
        success = await browser.wait_for_manual_login(timeout_minutes=5)
        if success:
            logger.info("Login successful. Session saved for future runs.")
        else:
            logger.error("Login timed out. Try again with: python main.py --login-only")


async def run_check_selectors(browser: BrowserManager) -> None:
    """Navigate to WAAS and report which selectors match."""
    from hmha import selectors

    page = await browser.launch()

    if not await browser.is_logged_in():
        logger.error("Not logged in. Run: python main.py --login-only")
        return

    # Check listing page selectors
    url = "https://www.workatastartup.com/jobs"
    logger.info("Checking listing page: %s", url)
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(3)

    listing_selectors = {
        "JOB_ROW": selectors.JOB_ROW,
        "LOAD_MORE_BUTTON": selectors.LOAD_MORE_BUTTON,
        "LOGGED_IN_INDICATOR": selectors.LOGGED_IN_INDICATOR,
    }

    for name, sel in listing_selectors.items():
        try:
            elements = await page.query_selector_all(sel)
            count = len(elements)
            status = "PASS" if count > 0 else "FAIL"
            print(f"  [{status}] {name}: {count} matches")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")

    # Find and check a single job detail page
    job_links = await page.query_selector_all(selectors.JOB_ROW)
    if job_links:
        href = await job_links[0].get_attribute("href")
        if href:
            detail_url = href if href.startswith("http") else f"https://www.workatastartup.com{href}"
            logger.info("\nChecking detail page: %s", detail_url)
            await page.goto(detail_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            detail_selectors = {
                "JOB_TITLE": selectors.JOB_TITLE,
                "APPLY_BUTTON": selectors.APPLY_BUTTON,
                "COMPANY_ABOUT": selectors.COMPANY_ABOUT,
            }

            for name, sel in detail_selectors.items():
                try:
                    elements = await page.query_selector_all(sel)
                    count = len(elements)
                    status = "PASS" if count > 0 else "FAIL"
                    print(f"  [{status}] {name}: {count} matches")
                except Exception as e:
                    print(f"  [ERROR] {name}: {e}")

    print("\nIf any selectors show FAIL, update hmha/selectors.py")
    print("Use browser DevTools (F12) to inspect the page and find correct selectors.")


async def run_main(args: argparse.Namespace) -> None:
    """Main orchestration loop: scrape -> generate -> review -> apply."""
    config_path = Path(args.config)
    config = load_config(config_path)

    tracker = ApplicationTracker(csv_path=Path("data/applications.csv"))
    reviewer = MessageReviewer()
    browser = BrowserManager(
        user_data_dir="browser_data",
        headless=config.browser_headless,
        slow_mo=config.browser_slow_mo,
    )
    generator = MessageGenerator(api_key=config.anthropic_api_key)

    try:
        page = await browser.launch()

        # Verify login
        if not await browser.is_logged_in():
            logger.info("Not logged in. Opening browser for login...")
            success = await browser.wait_for_manual_login()
            if not success:
                logger.error("Login failed. Exiting.")
                return

        # Build filtered URL
        url = build_jobs_url(
            job_type=config.search_filters.job_type,
            roles=config.search_filters.roles,
            remote=config.search_filters.remote,
            location=config.search_filters.location,
            company_size=config.search_filters.company_size,
            industries=config.search_filters.industries,
            visa_not_required=config.search_filters.visa_not_required,
            sort_by=config.search_filters.sort_by,
        )
        logger.info("Filtered URL: %s", url)

        # Scrape job listings
        scraper = JobScraper(page)
        max_to_fetch = args.max_applications * 3  # Fetch extra to account for skips
        job_stubs = await scraper.scrape_job_listings(url, max_jobs=max_to_fetch)

        if not job_stubs:
            logger.warning("No jobs found! Check your filters in config.yaml.")
            return

        # Filter out already-applied jobs
        fresh_jobs = [j for j in job_stubs if not tracker.has_applied(j["job_id"])]
        logger.info("%d jobs remaining after filtering applied ones.", len(fresh_jobs))

        if not fresh_jobs:
            logger.info("No new jobs to apply to. Try different filters or wait for new postings.")
            return

        # Apply to jobs
        applicant = JobApplicant(page, dry_run=args.dry_run)
        sent_count = 0
        total_to_process = min(len(fresh_jobs), args.max_applications)

        for i, stub in enumerate(fresh_jobs[:total_to_process], start=1):
            try:
                # Check for CAPTCHA
                if await browser.check_for_captcha():
                    await browser.handle_captcha()

                # Scrape full job details
                job = await scraper.scrape_job_detail(stub["url"])

                # Filter by allowed locations (skip international jobs)
                allowed = config.search_filters.allowed_locations
                if allowed and job.location:
                    location_lower = job.location.lower()
                    if not any(loc.lower() in location_lower for loc in allowed):
                        logger.info(
                            "Skipping %s at %s — location '%s' not in allowed list.",
                            job.title, job.company.name, job.location,
                        )
                        tracker.record(Application(
                            job=job, message="", status=ApplicationStatus.SKIPPED,
                            notes=f"location_filtered: {job.location}",
                        ))
                        continue

                # Check if already applied on the page itself
                if await applicant._is_already_applied():
                    logger.info("Already applied to %s (on-page). Skipping.", job.title)
                    tracker.record(Application(
                        job=job, message="", status=ApplicationStatus.SKIPPED,
                        notes="already_applied_on_site",
                    ))
                    continue

                # Summarize company/role info for display + generate message in parallel
                try:
                    import asyncio as _asyncio
                    (about_summary, desc_summary), message = await _asyncio.gather(
                        generator.summarize_for_display(job),
                        generator.generate_message(
                            job=job,
                            user_profile=config.user_profile,
                            style_notes=config.message_style,
                        ),
                    )
                    job.about_summary = about_summary
                    job.description_summary = desc_summary
                except Exception as e:
                    logger.warning("AI generation failed: %s. Using fallback.", e)
                    message = generator.generate_fallback(job, config.user_profile)

                # Review the message
                decision, final_message = reviewer.review(
                    job=job,
                    message=message,
                    job_number=i,
                    total_jobs=total_to_process,
                )

                if decision == ReviewDecision.QUIT:
                    logger.info("User quit. Stopping.")
                    break
                elif decision == ReviewDecision.SKIP:
                    tracker.record(Application(
                        job=job, message=final_message, status=ApplicationStatus.SKIPPED,
                        notes="user_skipped",
                    ))
                    continue
                elif decision in (ReviewDecision.APPROVE, ReviewDecision.EDIT):
                    # Apply
                    application = await applicant.apply_to_job(job, final_message)
                    tracker.record(application)
                    if application.status == ApplicationStatus.SENT:
                        sent_count += 1

                # Delay between applications
                if i < total_to_process:
                    await random_delay(config.delay_min_seconds, config.delay_max_seconds)

            except Exception as e:
                logger.error("Error processing job %s: %s", stub.get("url", "?"), e)
                continue

        # Session summary
        summary = tracker.get_summary()
        print(f"\n{'=' * 40}")
        print(f"  Session Complete")
        print(f"{'=' * 40}")
        print(f"  Sent:    {summary.get('sent', 0)}")
        print(f"  Skipped: {summary.get('skipped', 0)}")
        print(f"  Errors:  {summary.get('error', 0)}")
        print(f"  Dry Run: {summary.get('dry_run', 0)}")
        print(f"  Log:     data/applications.csv")
        print(f"{'=' * 40}\n")

    finally:
        await generator.close()
        await browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HMHA - Automated YC WAAS job applicant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="First run: python main.py --login-only\nThen test:  python main.py --dry-run",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Open browser for manual WAAS login, then exit.",
    )
    parser.add_argument(
        "--check-selectors",
        action="store_true",
        help="Verify CSS selectors match the live WAAS page.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape jobs and generate messages, but don't submit.",
    )
    parser.add_argument(
        "--max-applications",
        type=int,
        default=25,
        help="Maximum applications per session (default: 25).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config file (default: config.yaml).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(verbose=args.verbose)

    print(r"""
    __  __ __  ___ __  __ ___
   / / / /  |/  // / / //   |
  / /_/ / /|_/ // /_/ // /| |
 / __  / /  / // __  // ___ |
/_/ /_/_/  /_//_/ /_//_/  |_|
    """)
    print("  Automated YC Work at a Startup Applicant")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    if args.login_only:
        browser = BrowserManager(user_data_dir="browser_data")
        asyncio.run(run_login_only(browser))
        asyncio.run(browser.close())
    elif args.check_selectors:
        browser = BrowserManager(user_data_dir="browser_data")
        asyncio.run(run_check_selectors(browser))
        asyncio.run(browser.close())
    else:
        asyncio.run(run_main(args))


if __name__ == "__main__":
    main()
