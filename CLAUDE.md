# CLAUDE.md — Job Tracker

AI assistant guide for the Job-Tracker repository.

## Project Overview

A lightweight GitHub Actions–powered job scraper. It monitors 35 company career pages daily,
detects new Project Manager / Program Manager postings in the Munich/Nuremberg area, and sends
email alerts with an attached CSV database of all findings. No server, no database — just Python
and GitHub's free CI infrastructure.

## Repository Structure

```
Job-Tracker/
├── checker.py                        # Entire application (~444 lines)
├── requirements.txt                  # Python dependencies (3 packages)
├── README.md                         # User-facing setup guide
├── CLAUDE.md                         # This file
└── .github/
    └── workflows/
        └── job_tracker.yml           # GitHub Actions schedule & pipeline
```

**Runtime-generated files** (not committed, persisted via GitHub Actions cache):
```
job_state.json       # SHA256 fingerprints + known job titles per company
jobs_database.csv    # Append-only historical record of all found jobs
```

## Technology Stack

- **Language:** Python 3.11
- **Dependencies:** `requests==2.31.0`, `beautifulsoup4==4.12.3`, `lxml==5.1.0`
- **Infrastructure:** GitHub Actions (schedule + manual dispatch)
- **State persistence:** GitHub Actions cache (`actions/cache@v4`)
- **Email:** Gmail SMTP via `smtplib.SMTP_SSL` (port 465)
- **Data storage:** CSV file (stdlib `csv` module, no ORM, no SQL)

## Core Architecture

### Single-File Application (`checker.py`)

All logic lives in one file with clearly separated sections:

| Section | Lines | Purpose |
|---------|-------|---------|
| Filter config | 34–52 | `ROLE_KEYWORDS`, `SENIORITY_EXCLUDE`, `LOCATION_KEYWORDS` |
| Company list | 58–94 | `COMPANIES` — 35 `{name, url}` dicts |
| Config / env vars | 97–113 | Environment variable reads, constants |
| Matching helpers | 117–140 | `ci()`, `contains_any()`, `is_relevant_role()`, `is_relevant_location()`, `extract_location_hint()` |
| CSV database | 144–184 | `init_db()`, `load_db()`, `append_to_db()`, `append_page_change_to_db()` |
| Job extraction | 188–226 | `extract_jobs()` — BeautifulSoup HTML parser |
| State helpers | 230–254 | `load_state()`, `save_state()`, `fetch()`, `page_fingerprint()` |
| Email | 258–361 | `send_email()` — MIME multipart HTML+plain+CSV attachment |
| Main | 365–443 | `main()` — orchestration loop |

### State Machine Per Company

Each run, for every company:

```
fetch HTML
    │
    ├─ first_run (no saved hash)?
    │       → save baseline, skip email
    │
    ├─ hash unchanged?
    │       → no action
    │
    ├─ hash changed + new parseable jobs?
    │       → add to results, write to CSV, trigger email
    │
    └─ hash changed + no parseable jobs (JS-rendered)?
            → log "⚠️ Page changed — check manually", write to CSV
```

### Deduplication Logic

Two-layer deduplication prevents repeat alerts:
1. **In-memory:** `known` set from `job_state.json` — tracks job titles seen in previous runs per company
2. **CSV:** `existing_db` set of `(company.lower(), title.lower())` tuples — prevents duplicate CSV rows

### HTML Parsing Strategy (`extract_jobs`)

1. **Primary:** Scan all `<a href>` tags, filter by role/location keywords
2. **Fallback:** Scan `<li>`, `<div>`, `<article>` containers if no links matched
3. **Dedup:** Case-insensitive title deduplication before returning

### Page Fingerprinting (`page_fingerprint`)

Removes `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>`, `<noscript>` tags, normalizes
whitespace, returns SHA256 of remaining text. Stable across re-renders, sensitive to content changes.

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GMAIL_USER` | Yes | — | Gmail address used to send alerts |
| `GMAIL_APP_PASSWORD` | Yes | — | 16-char Gmail app password (not your login) |
| `NOTIFY_EMAIL` | No | `GMAIL_USER` | Comma-separated recipient list |
| `STATE_FILE` | No | `job_state.json` | Path for state persistence file |

All are set as **GitHub Actions repository secrets** — never stored in the repo.

## CSV Database Schema

**File:** `jobs_database.csv`

| Column | Example | Notes |
|--------|---------|-------|
| `Date Recorded` | `2025-03-14` | ISO date, `%Y-%m-%d` |
| `Company` | `Marvel Fusion` | Exact name from `COMPANIES` list |
| `Job Title` | `Senior Project Manager` | Raw text from page |
| `Location` | `Munich, Germany` | Extracted hint or `"See posting"` |
| `Job URL` | `https://...` | Direct job link or career page URL |
| `Career Page` | `https://...` | Company career page URL |
| `Status` | `New` / `Needs Manual Check` | `New` for extracted jobs; `Needs Manual Check` for JS pages |

The CSV is **append-only** — rows are never deleted or updated.

## GitHub Actions Workflow

**File:** `.github/workflows/job_tracker.yml`

**Triggers:**
- `schedule: "0 7 * * *"` — daily at 07:00 UTC
- `workflow_dispatch` — manual trigger

**Key pipeline steps:**
1. Checkout code
2. Setup Python 3.11 with pip cache
3. Restore `job_state.json` from cache (key: `job-state-{run_id}`, restore-key: `job-state-`)
4. Restore `jobs_database.csv` from cache (key: `jobs-db-{run_id}`, restore-key: `jobs-db-`)
5. Run `python checker.py`
6. Save updated `job_state.json` back to cache
7. Save updated `jobs_database.csv` back to cache
8. Upload `jobs_database.csv` as artifact (90-day retention)

## Development Conventions

### Adding a Company

Append to the `COMPANIES` list in `checker.py` (lines 58–94):

```python
{"name": "Company Name", "url": "https://example.com/careers"},
```

Use a direct filtered URL (pre-filtered by location/role if the site supports it) to improve extraction accuracy.

### Modifying Filters

Three filter lists at the top of `checker.py`:

```python
ROLE_KEYWORDS      # Must match (any) — line 34
SENIORITY_EXCLUDE  # Must NOT match (any) — line 39
LOCATION_KEYWORDS  # Must match (any) — line 45
```

All comparisons are case-insensitive via `ci(text)` → `text.lower()`.

### No Tests

There is no test suite. Manual testing is done by:
1. Running `python checker.py` locally with env vars set
2. Using `workflow_dispatch` in GitHub Actions

### No Linting Config

No `.pylintrc`, `pyproject.toml`, or `.flake8` — keep code style consistent with the existing file
(snake_case, 100-char lines, stdlib imports first, then third-party).

## Key Behaviours to Know

- **First run is always a baseline** — no email is sent; state is saved for comparison.
- **JS-rendered pages** that change but yield no parseable jobs are flagged with a `"Needs Manual Check"` CSV row and mentioned in emails.
- **Email includes a CSV attachment** of all historical findings (`jobs_database.csv`).
- **Multiple recipients** supported: set `NOTIFY_EMAIL` to a comma-separated string.
- **No retry logic** in `fetch()` — a failed request is silently skipped with a warning log.
- **State keys** in `job_state.json` follow the pattern `{company_name}__hash` and `{company_name}__jobs`.

## Common Tasks

### Run Locally

```bash
pip install -r requirements.txt
export GMAIL_USER="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export NOTIFY_EMAIL="you@gmail.com"
python checker.py
```

### Reset State (force re-baseline)

Delete or clear `job_state.json` before the next run. The next run will treat all companies as
first-run and save a new baseline without sending email.

### Force a Test Email

Temporarily change `main()` line 434:
```python
# from:
if results:
# to:
if True:
```
Run once, then revert. Do not commit this change.

### Change Schedule

Edit `.github/workflows/job_tracker.yml` line 4:
```yaml
- cron: "0 7 * * *"   # minute hour day month weekday (UTC)
```

### Download Historical Database

Go to GitHub repo → **Actions** → select a completed run → **Artifacts** → download
`jobs-database-{N}`.
