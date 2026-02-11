"""Centralized CSS selectors for the WAAS site.

All DOM selectors live here so they can be updated in one place
when the site changes its frontend. Run `main.py --check-selectors`
to verify these against the live page.

NOTE: These are best-effort selectors based on observed page structure.
You may need to update them after inspecting the live DOM with DevTools.
"""

# -- Job listing page ----------------------------------------------------------

# Each startup card on the listing page
STARTUP_CARD = "div[class*='ListItem']"

# Job rows within a startup card
JOB_ROW = "a[href*='/jobs/']"
JOB_ROW_TITLE = "a[href*='/jobs/']"

# "View job" button on each job row
VIEW_JOB_BUTTON = "a:has-text('View job')"

# Pagination / load more
LOAD_MORE_BUTTON = "button:has-text('Load more')"
SHOW_MORE_JOBS = "button:has-text('Show more')"

# -- Job detail page -----------------------------------------------------------

# Company info section
COMPANY_NAME = "h1"
COMPANY_BATCH = "span[class*='batch']"
COMPANY_ABOUT = "div[class*='company-description'], div[class*='about']"

# Job details
JOB_TITLE = "h1"
JOB_DESCRIPTION = "div[class*='description'], div[class*='job-details']"
JOB_REQUIREMENTS = "div[class*='requirements'], div[class*='qualifications']"

# The primary Apply button on the job detail page
APPLY_BUTTON = "button:has-text('Apply'), a:has-text('Apply')"

# -- Application modal ---------------------------------------------------------

MODAL = "div[role='dialog'], div[class*='modal']"
MODAL_TEXTAREA = "textarea"
SEND_BUTTON = "button:has-text('Send')"
CLOSE_BUTTON = "button:has-text('Close')"

# -- Auth state ----------------------------------------------------------------

LOGGED_IN_INDICATOR = "a:has-text('My profile'), a[href*='profile']"
LOGIN_BUTTON = "a:has-text('Log in'), a:has-text('Sign in')"

# -- Already applied -----------------------------------------------------------

ALREADY_APPLIED = "text='Applied'"

# -- Bot detection -------------------------------------------------------------

CAPTCHA_INDICATORS = [
    "#challenge-running",
    "iframe[src*='captcha']",
    "iframe[src*='challenge']",
    "div[class*='captcha']",
]
