# HMHA

Automated job application tool for YC's [Work at a Startup](https://www.workatastartup.com). Scrapes job listings, generates personalized founder messages using Claude, and lets you review each one before sending.

## How It Works

```
Scrape filtered jobs → Extract company/role details → Generate tailored message (Claude)
    → Review in terminal (approve/edit/skip) → Submit application → Log to CSV
```

The tool uses Playwright to drive a real browser with your logged-in session. Claude reads each company's description and role requirements, then writes a short, specific message that references what the company actually builds. You review every message before it's sent.

## Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/settings/keys)
- A [Work at a Startup](https://www.workatastartup.com) account

## Setup

```bash
# Clone and install
git clone https://github.com/yourusername/hmha.git
cd hmha
pip install -r requirements.txt
playwright install chromium

# Configure
cp config.example.yaml config.yaml    # Edit with your profile
cp .env.example .env                   # Add your ANTHROPIC_API_KEY

# Login (opens browser - sign in manually, session is saved)
python main.py --login-only
```

## Usage

```bash
# Test run - scrapes jobs and generates messages but doesn't send
python main.py --dry-run

# Full run with review mode (default: up to 25 applications)
python main.py

# Limit to 5 applications
python main.py --max-applications 5

# Verify selectors still match the WAAS page
python main.py --check-selectors

# Debug mode
python main.py --verbose
```

### Review Mode

For each job, you'll see the company context and a generated message in your terminal:

```
============================================================
 Job 3/25
============================================================

Role:    Full-Stack Software Engineer
Company: Wanderlog (W19)
About:   Travel planner for researching, organizing, and mapping your trip...
Culture: Engineering-heavy team, work-life balance, quarterly offsites...

--- Generated Message (87 words, 423 chars) ---
Hi! I've been using Wanderlog to plan trips and love how it...
-------------------------------

[A]pprove  [E]dit  [S]kip  [Q]uit >
```

- **Approve** - Send the message as-is
- **Edit** - Opens in `$EDITOR` (or inline input) to modify
- **Skip** - Move to the next job
- **Quit** - Stop the session

## Configuration

Edit `config.yaml` with your details. See `config.example.yaml` for the full template.

Key sections:
- **user_profile** - Your name, education, experience, skills, resume highlights
- **search_filters** - Job type, roles, location, company size
- **message_style** - Tone guidance for Claude (e.g., "conversational but professional")
- **settings** - Application cap, delays between submissions, browser options

Your API key goes in `.env`, never in the YAML file.

## Architecture

```
main.py                  # CLI + orchestration loop
hmha/
├── browser.py           # Playwright persistent context (login survives across runs)
├── scraper.py           # Job listing + detail page extraction
├── applicant.py         # Apply modal: click Apply → fill textarea → send
├── ai.py                # Claude prompt engineering + message generation
├── reviewer.py          # Terminal review UI with color formatting
├── tracker.py           # CSV logging + deduplication (never re-apply)
├── config_loader.py     # YAML config validation
├── models.py            # Job, Company, Application dataclasses
├── selectors.py         # All CSS selectors in one place (easy to update)
├── filters.py           # WAAS URL query parameter builder
└── utils.py             # Logging, random delays, retry decorator
```

### Why Persistent Browser Context?

WAAS auth goes through `account.ycombinator.com` with complex session handling. Using Playwright's `launch_persistent_context` preserves cookies, local storage, and service workers across runs. You log in once, and every future run re-uses that session.

### Selector Maintenance

WAAS is a React SPA - selectors may break when they update their frontend. All selectors live in `selectors.py`. Run `python main.py --check-selectors` to verify them, and update as needed using browser DevTools.

## Application Log

Every application attempt is logged to `data/applications.csv`:

| job_id | company_name | job_title | url | message_sent | status | timestamp | notes |
|--------|-------------|-----------|-----|-------------|--------|-----------|-------|
| 12345 | Wanderlog | Full-Stack Engineer | ... | Hi! I've been... | sent | 2026-02-10T... | |

## Disclaimer

This tool is for educational and personal use. Be respectful of rate limits. The review mode exists so you can ensure every message is genuine and appropriate before sending.

## License

MIT
