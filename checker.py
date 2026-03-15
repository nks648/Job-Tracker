"""
Job Tracker - Checks company career pages daily for new postings.
Filters for: Project Manager / Program Manager (Senior or Mid-level)
Locations:   Munich area  |  Nuremberg area
Logs all findings to jobs_database.csv
Sends alerts to multiple recipients
"""

import os
import json
import re
import hashlib
import smtplib
import csv
import logging
import time
from datetime import datetime, date, timedelta
from urllib.parse import urlparse, quote_plus
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import requests
from bs4 import BeautifulSoup

try:
    import google.generativeai as _genai
    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# FILTER CONFIG
# ══════════════════════════════════════════════════════════════════════════════

ROLE_KEYWORDS = [
    "project manager", "program manager", "programme manager",
    "projektmanager", "projektleiter", "programm manager",
]

SENIORITY_EXCLUDE = [
    "junior", "jr.", "jr ", "intern", "internship",
    "werkstudent", "praktikum", "praktikant",
    "entry level", "entry-level", "graduate", "trainee", "assistant",
]

LOCATION_KEYWORDS = [
    "munich", "münchen", "munchen", "taufkirchen", "ottobrunn",
    "garching", "unterschleißheim", "unterschleissheim",
    "oberpfaffenhofen", "dachau", "freising", "starnberg", "germering",
    "nuremberg", "nürnberg", "nurnberg", "erlangen",
    "fürth", "furth", "schwabach", "herzogenaurach",
    "remote", "hybrid", "germany", "deutschland", "bavaria", "bayern",
]

# ══════════════════════════════════════════════════════════════════════════════
# COMPANY LIST
# ══════════════════════════════════════════════════════════════════════════════

COMPANIES = [
    {"name": "OHB AG",             "url": "https://career-ohb.csod.com/ux/ats/careersite/4/home?c=career-ohb&cfdd%5B0%5D%5Bid%5D=16&cfdd%5B0%5D%5Boptions%5D%5B0%5D=29&lq=Munich%252C%2520Germany&pl=ChIJ2V-Mo_l1nkcRfZixfUq4DAE&lang=en-GB"},
    {"name": "Ariane Group",        "url": "https://arianegroup.wd3.myworkdayjobs.com/fr-FR/EXTERNALALL?locations=a18ef726d665016eab2a92b8fa1c0dbb"},
    {"name": "GE Aerospace",        "url": "https://careers.geaerospace.com/global/en/search-results"},
    {"name": "MTU Aerospace",       "url": "https://www.mtu.de/careers/online-job-market/"},
    {"name": "Mynaric",             "url": "https://mynaric.com/careers/all-open-positions/"},
    {"name": "Marvel Fusion",       "url": "https://job-boards.eu.greenhouse.io/marvelfusion"},
    {"name": "Hensoldt",            "url": "https://jobs.hensoldt.net/search/?createNewAlert=false&q=&optionsFacetsDD_country=DE&optionsFacetsDD_location=Taufkirchen%2C+DE%2C+82024&optionsFacetsDD_customfield1=Professionals"},
    {"name": "Airbus",              "url": "https://ag.wd3.myworkdayjobs.com/Airbus?locationCountry=dcc5b7608d8644b3a93716604e78e995&locations=f5811cef9cb50199bf69196b4c0a674b"},
    {"name": "DeltaVision",         "url": "https://deltavision.space/job-openings/"},
    {"name": "Exploration Company", "url": "https://www.exploration.space/careers#job-application"},
    {"name": "SES Sat",             "url": "https://careers.ses.com/search/?createNewAlert=false&q=&locationsearch=Munich"},
    {"name": "AMD Munich",          "url": "https://careers.amd.com/careers-home/jobs?stretchUnit=MILES&stretch=10&location=Munich,%20Germany&woe=7&regionCode=DE"},
    {"name": "Applied Materials",   "url": "https://careers.appliedmaterials.com/careers?domain=appliedmaterials.com&triggerGoButton=false&start=0&pid=790303658171&sort_by=timestamp&filter_country=Germany"},
    {"name": "Infineon",            "url": "https://jobs.infineon.com/careers?query=Project%20Management&location=Munich%2C%20BY%2C%20Germany&pid=563808959485350&domain=infineon.com&sort_by=relevance"},
    {"name": "Siemens",             "url": "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/?42386=%5B812132%5D&42386_format=17546&42387=%5B813141%5D&42387_format=17547&listFilterMode=1"},
    {"name": "Rheinmetall",         "url": "https://www.rheinmetall.com/en/career/vacancies?9dc11c304b4c06c2f71c48cc6574e7e5filter=%257B%2522countries%2522%253A%255B%2522Germany%2522%255D%252C%2522cities%2522%253A%255B%2522M%25C3%25BCnchen%2522%255D%257D"},
    {"name": "Bosch",               "url": "https://jobs.bosch.com/en?pages=1&country=de&location=M%C3%BCnchen+-+Mitte#"},
    {"name": "KNDS",                "url": "https://jobs.knds.de/content/search/?locale=de_DE&currentPage=1&pageSize=12&addresses%252Fname=M%C3%BCnchen"},
    {"name": "Avilus",              "url": "https://www.avilus.com/career"},
    {"name": "MBDA",                "url": "https://www.mbda-careers.de/ema/?_locations%5B%5D=Ottobrunn&_order=ASC&_page=1"},
    {"name": "KraussMaffei",        "url": "https://jobs.kraussmaffei.com/search/?createNewAlert=false&q=&locationsearch=Parsdorf"},
    {"name": "Puma",                "url": "https://about.puma.com/en/careers/job-openings?area=all&location=441"},
    {"name": "Huber+Suhner",        "url": "https://recruiting.hubersuhner.com/Jobs/All"},
    {"name": "SAP AG",              "url": "https://jobs.sap.com/search/?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_country=DE"},
    {"name": "Bundesagentur",       "url": "https://www.arbeitsagentur.de/jobsuche/suche?angebotsart=1&wo=M%C3%BCnchen&umkreis=25&veroeffentlichtseit=0&was=Projektmanager%252Fin"},
    {"name": "Renk",                "url": "https://www.renk.com/en/career/job-opportunities/opportunities-in-europe"},
    {"name": "Spire Defense",       "url": "https://spire.com/careers/job-openings/?location=munich"},
    {"name": "Auterion Defense",    "url": "https://auterion.com/company/careers/"},
    {"name": "LHIND (Lufthansa)",   "url": "https://apply.lufthansagroup.careers/index.php?ac=search_result&search_criterion_channel%5B%5D=12&search_criterion_target_group%5B%5D=4&language=2"},
    {"name": "Cesium Astro",        "url": "https://jobs.lever.co/CesiumAstro?location=Munich"},
    {"name": "Constellr",           "url": "https://constellr.recruitee.com"},
    {"name": "Stark",               "url": "https://stark.jobs.personio.com/?filters=eyJvZmZpY2VfaWQiOlsyNzQzNjkyXX0="},
    {"name": "Tytan",               "url": "https://tytantechnologiesgmbh.recruitee.com"},
    {"name": "Hypersonica",         "url": "https://jobs.lever.co/hypersonica-prod?location=Munich%20or%20Remote"},
    {"name": "Reverion",            "url": "https://reverion.jobs.personio.de/?language=en"},
]

# ── Config ─────────────────────────────────────────────────────────────────────
GMAIL_USER        = os.environ["GMAIL_USER"]
GMAIL_PASSWORD    = os.environ["GMAIL_APP_PASSWORD"]
# Multiple recipients: comma-separated in the secret
# e.g. "nagarjun@gmail.com,friend@gmail.com"
NOTIFY_EMAILS     = [e.strip() for e in os.environ.get("NOTIFY_EMAIL", GMAIL_USER).split(",")]
BCC_EMAILS        = [e.strip() for e in os.environ.get("BCC_EMAIL", "").split(",") if e.strip()]
STATE_FILE        = os.environ.get("STATE_FILE", "job_state.json")
DB_FILE           = "jobs_database.csv"
GEMINI_API_KEY      = os.environ.get("GEMINI_API_KEY", "")
AI_ENABLED          = _GEMINI_AVAILABLE and bool(GEMINI_API_KEY)
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED    = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
LINKEDIN_VALIDATE   = os.environ.get("LINKEDIN_VALIDATE", "true").lower() == "true"
LINKEDIN_MAX_AGE    = int(os.environ.get("LINKEDIN_MAX_AGE_DAYS", "3"))  # days

DB_COLUMNS = ["Date Recorded", "Date Posted", "Company", "Job Title", "Location", "Job URL", "Career Page", "Status"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Matching helpers ───────────────────────────────────────────────────────────

def ci(text):
    return text.lower()

def contains_any(text, keywords):
    t = ci(text)
    return any(ci(kw) in t for kw in keywords)

def is_relevant_role(title):
    if not contains_any(title, ROLE_KEYWORDS):
        return False
    if contains_any(title, SENIORITY_EXCLUDE):
        return False
    return True

def is_relevant_location(loc_text):
    return contains_any(loc_text, LOCATION_KEYWORDS)

def extract_location_hint(text):
    for kw in LOCATION_KEYWORDS:
        pattern = re.compile(rf"\b{re.escape(kw)}\b[^\n,|•·]{0,40}", re.IGNORECASE)
        m = pattern.search(text)
        if m:
            return m.group(0).strip()[:60]
    return None

# ── Date helpers ───────────────────────────────────────────────────────────────

def _parse_date_str(s):
    """Parse ISO (2026-03-14, 2026-03-14T...) or European (14.03.2026) date strings."""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


def _relative_to_date(text):
    """Parse relative date text: 'today', 'yesterday', 'X days ago', 'heute', 'gestern'."""
    t = text.lower()
    today = date.today()
    if any(w in t for w in ("today", "heute", "just posted", "new today")):
        return today
    if any(w in t for w in ("yesterday", "gestern")):
        return today - timedelta(days=1)
    # "1 hour ago", "2 hours ago" → still today
    if re.search(r'\d+\s*(?:hour|stunde|minute|min)\b', t):
        return today
    # "2 days ago" / "vor 2 Tagen" / "vor 2 Tage"
    m = re.search(r'(\d+)\s*(?:day|tag)\b', t)
    if m:
        n = int(m.group(1))
        if n <= 30:
            return today - timedelta(days=n)
    # "1 week ago" / "vor 1 Woche"
    m = re.search(r'(\d+)\s*(?:week|woche)\b', t)
    if m:
        n = int(m.group(1))
        if n <= 4:
            return today - timedelta(weeks=n)
    return None


def _parse_jsonld_dates(html):
    """Return {url: date, title_lower: date} from JSON-LD JobPosting blocks.
    Used by Greenhouse, Lever, Recruitee, and most modern job boards."""
    soup = BeautifulSoup(html, "html.parser")
    dates = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") not in ("JobPosting", "jobPosting"):
                    continue
                d = _parse_date_str(item.get("datePosted", ""))
                if not d:
                    continue
                url   = item.get("url", "")
                title = (item.get("title") or item.get("name") or "").strip()
                if url:
                    dates[url] = d
                if title:
                    dates[title.lower()] = d
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    return dates


def _tag_date(tag):
    """Search a BeautifulSoup tag for a date using multiple HTML patterns."""
    if tag is None:
        return None
    # 1. <time datetime="2026-03-14">
    time_el = tag.find("time", attrs={"datetime": True})
    if time_el:
        d = _parse_date_str(time_el["datetime"])
        if d:
            return d
    # 2. <meta itemprop="datePosted" content="2026-03-14">  or  <span itemprop="datePosted">
    for el in tag.find_all(attrs={"itemprop": "datePosted"}):
        val = el.get("content") or el.get_text(strip=True)
        d = _parse_date_str(val)
        if d:
            return d
    # 3. data-date / data-posted / data-dateposted attributes anywhere in the container
    for attr in ("data-date", "data-posted", "data-dateposted", "data-created"):
        el = tag.find(attrs={attr: True})
        if el:
            d = _parse_date_str(el[attr])
            if d:
                return d
    # 4. CSS class heuristics — look for a date string inside likely elements
    for cls_pattern in ("date-posted", "posting-date", "job-date", "posted-on",
                        "published-date", "listdate", "date_posted"):
        el = tag.find(class_=re.compile(cls_pattern, re.I))
        if el:
            d = _parse_date_str(el.get_text(strip=True)) or _relative_to_date(el.get_text(strip=True))
            if d:
                return d
    # 5. aria-label containing "posted" + a recognisable date
    for el in tag.find_all(attrs={"aria-label": re.compile(r"posted", re.I)}):
        label = el.get("aria-label", "")
        m = re.search(r'\d{4}-\d{2}-\d{2}', label)
        if m:
            d = _parse_date_str(m.group())
            if d:
                return d
    # 6. Relative date text anywhere in the container
    return _relative_to_date(tag.get_text(" ", strip=True))


def is_recent(d):
    """True if posting date is within the last 2 days, or unknown (None → include).
    2-day window provides safety buffer when 3x-daily runs overlap day boundaries."""
    if d is None:
        return True
    return d >= date.today() - timedelta(days=2)


# ── CSV Database ───────────────────────────────────────────────────────────────

def init_db():
    """Create CSV with headers if it doesn't exist."""
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=DB_COLUMNS)
            writer.writeheader()
        log.info("Created new jobs_database.csv")

def load_db():
    """Load existing records to avoid duplicates.
    Returns a set of (company, title) tuples for job dedup
    plus (company, '__page_change_today__') for same-day page-change dedup."""
    existing = set()
    today = datetime.today().strftime("%Y-%m-%d")
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add((row["Company"].lower(), row["Job Title"].lower()))
                if (row.get("Date Recorded") == today
                        and "page changed" in row.get("Job Title", "").lower()):
                    existing.add((row["Company"].lower(), "__page_change_today__"))
    return existing

def append_to_db(records):
    """Append new job records to the CSV database."""
    if not records:
        return
    with open(DB_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_COLUMNS)
        for r in records:
            writer.writerow(r)
    log.info("Appended %d new record(s) to jobs_database.csv", len(records))

def append_page_change_to_db(company, career_url):
    """Log a page change (JS-rendered, manual check needed)."""
    with open(DB_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_COLUMNS)
        writer.writerow({
            "Date Recorded": datetime.today().strftime("%Y-%m-%d"),
            "Date Posted":   "",
            "Company":       company,
            "Job Title":     "⚠️ Page changed — check manually",
            "Location":      "Unknown (JS-rendered)",
            "Job URL":       career_url,
            "Career Page":   career_url,
            "Status":        "Needs Manual Check",
        })

# ── Native API fetchers (Greenhouse & Lever) ───────────────────────────────────

def fetch_greenhouse_jobs(career_url):
    """Use the Greenhouse public board API instead of HTML scraping.
    Returns (fingerprint_str | None, jobs_list).
    Board token is the last path segment of the career URL."""
    board_token = urlparse(career_url).path.strip("/").split("/")[-1]
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("  ⚠  Greenhouse API error (%s): %s", career_url, exc)
        return None, []

    jobs = []
    for j in data.get("jobs", []):
        title    = j.get("title", "")
        location = j.get("location", {}).get("name", "See posting")
        if not is_relevant_role(title):
            continue
        if location != "See posting" and not is_relevant_location(location):
            continue
        # updated_at is the best available public date (created_at needs Harvest API auth)
        jobs.append({
            "title":       title,
            "location":    location,
            "url":         j.get("absolute_url", career_url),
            "date_posted": _parse_date_str(j.get("updated_at", "")),
        })

    # Fingerprint = sorted job IDs so state machine detects additions/removals
    fp = json.dumps(sorted(str(j.get("id", "")) for j in data.get("jobs", [])))
    log.info("  📡 Greenhouse API: %d total / %d matching", len(data.get("jobs", [])), len(jobs))
    return fp, jobs


def fetch_lever_jobs(career_url):
    """Use the Lever public postings API instead of HTML scraping.
    Returns (fingerprint_str | None, jobs_list).
    Company slug is the first path segment of the career URL."""
    company_slug = urlparse(career_url).path.strip("/").split("/")[0]
    api_url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        postings = resp.json()
    except Exception as exc:
        log.warning("  ⚠  Lever API error (%s): %s", career_url, exc)
        return None, []

    jobs = []
    for j in postings:
        title = j.get("text", "")
        if not is_relevant_role(title):
            continue
        cats     = j.get("categories", {}) or {}
        location = cats.get("location", "") or ""
        if not location and isinstance(cats.get("allLocations"), list):
            location = cats["allLocations"][0] if cats["allLocations"] else ""
        if location and not is_relevant_location(location):
            continue
        # createdAt is Unix milliseconds (undocumented but present in practice)
        d = None
        created_ms = j.get("createdAt")
        if created_ms:
            try:
                from datetime import timezone
                d = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).date()
            except Exception:
                pass
        jobs.append({
            "title":       title,
            "location":    location or "See posting",
            "url":         j.get("hostedUrl", career_url),
            "date_posted": d,
        })

    fp = json.dumps(sorted(j.get("id", "") for j in postings))
    log.info("  📡 Lever API: %d total / %d matching", len(postings), len(jobs))
    return fp, jobs


def fetch_workday_jobs(career_url):
    """Use the unofficial Workday CXS POST API to get jobs with real postedOn dates.
    Company slug = subdomain; site = first path segment of the career URL."""
    parsed     = urlparse(career_url)
    company    = parsed.hostname.split(".")[0]          # e.g. "ag" or "arianegroup"
    site       = parsed.path.strip("/").split("/")[0]   # e.g. "Airbus" or "EXTERNALALL"
    # Strip locale prefix if present (e.g. "fr-FR/EXTERNALALL" → "EXTERNALALL")
    if re.match(r'^[a-z]{2}-[A-Z]{2}$', site):
        parts = parsed.path.strip("/").split("/")
        site = parts[1] if len(parts) > 1 else site
    api_url = f"https://{parsed.hostname}/wday/cxs/{company}/{site}/jobs"
    try:
        resp = requests.post(api_url, json={"appliedFacets": {}, "limit": 100, "offset": 0,
                                            "searchText": ""},
                             headers={**HEADERS, "Content-Type": "application/json"}, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("  ⚠  Workday CXS API error (%s): %s", career_url, exc)
        return None, []

    jobs = []
    for j in data.get("jobPostings", []):
        title    = j.get("title", "")
        location = j.get("locationsText", "See posting")
        if not is_relevant_role(title):
            continue
        if location != "See posting" and not is_relevant_location(location):
            continue
        ext_path = j.get("externalPath", "")
        job_url  = f"https://{parsed.hostname}{ext_path}" if ext_path else career_url
        jobs.append({
            "title":       title,
            "location":    location,
            "url":         job_url,
            "date_posted": _parse_date_str(j.get("postedOn", "")),
        })

    all_postings = data.get("jobPostings", [])
    fp = json.dumps(sorted(j.get("title", "") + j.get("postedOn", "") for j in all_postings))
    log.info("  📡 Workday CXS API: %d total / %d matching", len(all_postings), len(jobs))
    return fp, jobs


def fetch_recruitee_jobs(career_url):
    """Use the Recruitee public offers API. Company slug = subdomain."""
    company = urlparse(career_url).hostname.split(".")[0]
    api_url = f"https://{company}.recruitee.com/api/offers/"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("  ⚠  Recruitee API error (%s): %s", career_url, exc)
        return None, []

    jobs = []
    for j in data.get("offers", []):
        title    = j.get("title", "")
        location = j.get("location", "") or j.get("city", "") or "See posting"
        if not is_relevant_role(title):
            continue
        if location != "See posting" and not is_relevant_location(location):
            continue
        jobs.append({
            "title":       title,
            "location":    location,
            "url":         j.get("careers_url", career_url),
            "date_posted": _parse_date_str(j.get("created_at", "") or j.get("published_at", "")),
        })

    all_offers = data.get("offers", [])
    fp = json.dumps(sorted(str(j.get("id", "")) for j in all_offers))
    log.info("  📡 Recruitee API: %d total / %d matching", len(all_offers), len(jobs))
    return fp, jobs


# ── Job extraction ─────────────────────────────────────────────────────────────

def extract_jobs(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    base = urlparse(page_url)
    jsonld_dates = _parse_jsonld_dates(html)  # {url/title_lower: date} from JSON-LD

    def abs_url(href):
        if not href: return page_url
        if href.startswith("http"): return href
        if href.startswith("/"): return f"{base.scheme}://{base.netloc}{href}"
        return page_url

    def resolve_date(job_url, title, container):
        """Date lookup: JSON-LD by URL → JSON-LD by title → HTML time tag → relative text."""
        return (jsonld_dates.get(job_url)
                or jsonld_dates.get(title.lower())
                or _tag_date(container))

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        if not (5 < len(title) < 160): continue
        if not is_relevant_role(title): continue
        parent = a.find_parent()
        ctx = parent.get_text(" ", strip=True) if parent else ""
        location = extract_location_hint(ctx) or "See posting"
        if location != "See posting" and not is_relevant_location(location): continue
        job_url = abs_url(a["href"])
        jobs.append({"title": title, "location": location, "url": job_url,
                     "date_posted": resolve_date(job_url, title, parent)})

    if not jobs:
        for tag in soup.find_all(["li", "div", "article"]):
            text = tag.get_text(" ", strip=True)
            if not is_relevant_role(text[:200]): continue
            if not is_relevant_location(text): continue
            inner = tag.find("a", href=True)
            title_text = inner.get_text(strip=True) if inner else text[:100]
            location   = extract_location_hint(text) or "See posting"
            job_url    = abs_url(inner["href"] if inner else None)
            jobs.append({"title": title_text, "location": location, "url": job_url,
                         "date_posted": resolve_date(job_url, title_text, tag)})

    seen, unique = set(), []
    for j in jobs:
        key = ci(j["title"])
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique

# ── State helpers ──────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def fetch(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        log.warning("  ⚠  Could not fetch %s: %s", url, exc)
        return None

def page_fingerprint(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script","style","nav","header","footer","noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return hashlib.sha256(text.encode()).hexdigest()

# ── AI Helpers ─────────────────────────────────────────────────────────────────

def get_page_text(html):
    """Strip boilerplate tags and return clean page text for AI consumption."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def _gemini_model():
    """Return a configured Gemini Flash model (lazy init)."""
    _genai.configure(api_key=GEMINI_API_KEY)
    return _genai.GenerativeModel("gemini-2.0-flash")


def ai_validate_jobs(jobs, company_name):
    """Use Gemini to contextually filter keyword-matched jobs, removing false positives
    and surfacing semantic variants the keyword list might miss."""
    if not jobs:
        return jobs

    titles = [j["title"] for j in jobs]
    prompt = (
        f"You are filtering job listings for someone seeking Senior or Mid-level "
        f"Project Manager / Program Manager roles in Munich or Nuremberg, Germany.\n\n"
        f"Company: {company_name}\n"
        f"Evaluate the following job titles. Return ONLY a JSON array of 0-based indices "
        f"for titles that are genuinely relevant:\n"
        f"- KEEP: Senior/Mid PM, Program Manager, IT Project Manager, Technical Project Manager, "
        f"PMO Lead, Delivery Manager, Projektmanager, Projektleiter, and close semantic equivalents.\n"
        f"- DROP: Junior/Intern/Trainee/Graduate, pure engineering roles that incidentally mention "
        f"'project', administrative or coordinator roles far below PM level.\n\n"
        f"Titles:\n{json.dumps(titles, indent=2)}\n\n"
        f"Return only the JSON array of indices to keep, e.g. [0, 2]. No explanation."
    )

    try:
        response = _gemini_model().generate_content(prompt)
        raw = response.text.strip().strip("```json").strip("```").strip()
        keep = json.loads(raw)
        if isinstance(keep, list):
            filtered = [jobs[i] for i in keep if isinstance(i, int) and i < len(jobs)]
            log.info("  🤖 AI validation: %d → %d job(s)", len(jobs), len(filtered))
            return filtered
    except Exception as exc:
        log.warning("  ⚠  AI validation failed (%s), keeping keyword results", exc)
    return jobs


def ai_extract_jobs(text, page_url, company_name):
    """Use Gemini to extract relevant jobs from raw page text.
    Sends up to 15 000 chars — enough to cover most static career pages in full.
    Returns [] for truly JS-rendered pages (empty static HTML after script removal)."""
    if len(text.strip()) < 200:
        log.info("  🤖 AI extraction skipped — page text is empty (JS-rendered, no static content)")
        return []

    prompt = (
        f"You are analyzing a career page for job listings.\n\n"
        f"Company: {company_name}\nPage URL: {page_url}\n\n"
        f"Page text:\n{text[:15000]}\n\n"
        f"Extract EVERY job listing that meets ALL of these criteria:\n"
        f"1. Role: Project Manager, Program Manager, or a close equivalent "
        f"(e.g. Delivery Manager, PMO, IT Project Lead, Projektleiter, "
        f"Programm Manager, Scrum Master if PM-adjacent).\n"
        f"2. Seniority: NOT junior / intern / trainee / graduate / werkstudent / praktikant.\n"
        f"3. Location: Munich, Nuremberg, Bavaria, Germany, Remote, or Hybrid "
        f"(include if location is unspecified — don't exclude on lack of location alone).\n\n"
        f"Return a JSON array of objects with keys: title (string), location (string), url (string).\n"
        f"If a direct job URL is not visible in the text, set url to an empty string.\n"
        f"If no relevant jobs are found, return [].\n"
        f"Return ONLY the JSON array, no explanation."
    )

    try:
        response = _gemini_model().generate_content(prompt)
        raw = response.text.strip().strip("```json").strip("```").strip()
        extracted = json.loads(raw)
        if isinstance(extracted, list):
            for j in extracted:
                if not j.get("url"):
                    j["url"] = page_url
                if not j.get("location"):
                    j["location"] = "See posting"
            log.info("  🤖 AI extraction: found %d job(s) from %d chars of page text",
                     len(extracted), len(text))
            return extracted
    except Exception as exc:
        log.warning("  ⚠  AI extraction failed (%s)", exc)
    return []


def ai_job_brief(job_url, job_title, company_name):
    """Fetch the job page and ask Gemini for a 3-bullet application brief.
    Returns a short HTML string or empty string if AI is disabled / fetch fails."""
    if not AI_ENABLED:
        return ""
    html = fetch(job_url)
    if not html:
        return ""
    text = get_page_text(html)
    if len(text.strip()) < 100:
        return ""
    prompt = (
        f"You are a career coach helping a candidate apply for this job quickly and effectively.\n\n"
        f"Job title: {job_title}\nCompany: {company_name}\n\n"
        f"Job description (truncated):\n{text[:6000]}\n\n"
        f"Return a JSON object with exactly these keys:\n"
        f"  'requirements': list of 3 strings — the most important requirements from the JD\n"
        f"  'lead_with': string — one sentence: the single strongest angle this candidate should lead with\n"
        f"  'keywords': list of 4-5 resume/cover-letter keywords from the JD\n"
        f"Return ONLY the JSON object, no explanation."
    )
    try:
        response = _gemini_model().generate_content(prompt)
        raw = response.text.strip().strip("```json").strip("```").strip()
        brief = json.loads(raw)
        reqs = "".join(f"<li style='margin:2px 0'>{r}</li>" for r in brief.get("requirements", []))
        kws  = ", ".join(f"<code>{k}</code>" for k in brief.get("keywords", []))
        lead = brief.get("lead_with", "")
        return (
            f"<div style='margin-top:8px;padding:10px 14px;background:#f8fafc;"
            f"border-left:3px solid #2563eb;border-radius:0 6px 6px 0;font-size:12px'>"
            f"<strong style='color:#1d4ed8'>Key requirements:</strong>"
            f"<ul style='margin:4px 0 6px 0;padding-left:16px;color:#374151'>{reqs}</ul>"
            f"<strong style='color:#1d4ed8'>Lead with:</strong> "
            f"<span style='color:#374151'>{lead}</span><br>"
            f"<strong style='color:#1d4ed8'>Keywords:</strong> {kws}"
            f"</div>"
        )
    except Exception as exc:
        log.warning("  ⚠  AI job brief failed for %s: %s", job_title, exc)
        return ""


def send_telegram(jobs_by_company):
    """Send an instant Telegram message for each new job found."""
    if not TELEGRAM_ENABLED or not jobs_by_company:
        return
    lines = ["🚨 *New job alert*\n"]
    for company, jobs in jobs_by_company:
        for j in jobs:
            posted = j["date_posted"].strftime("%d %b") if j.get("date_posted") else "today"
            lines.append(f"*{company}* — {j['title']}")
            lines.append(f"📍 {j['location']}  |  📅 {posted}")
            lines.append(f"[Apply →]({j['url']})\n")
    text = "\n".join(lines)
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=15,
        )
        log.info("📱 Telegram alert sent")
    except Exception as exc:
        log.warning("  ⚠  Telegram send failed: %s", exc)


# ── LinkedIn age-check ────────────────────────────────────────────────────────
#
# After a job is found on a company's own career page we cross-check LinkedIn.
# Logic:
#   • NOT on LinkedIn          → brand new, include it
#   • On LinkedIn, ≤ MAX days  → still fresh, include it
#   • On LinkedIn, > MAX days  → already circulating, skip
#   • Any error / LinkedIn 999 → fail open (always include)

_LI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _linkedin_check(job_title, company_name):
    """Search LinkedIn for job_title + company_name.

    Returns (posted_date, is_repost) for the best matching card, or (None, False)
    when not found / request blocked (caller must fail open).

    LinkedIn shows "Reposted X days ago" for ghost jobs recycled from months ago.
    The datetime attribute reflects the repost date (recent), not the original,
    so we detect the word "repost" in the visible label text instead.
    """
    query = f"{job_title} {company_name}"
    url   = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobView"
        f"?keywords={quote_plus(query)}&location=Munich%2C+Germany&start=0"
    )
    try:
        resp = requests.get(url, headers=_LI_HEADERS, timeout=15)
        if resp.status_code != 200:
            log.debug("  LinkedIn returned %d for '%s'", resp.status_code, job_title)
            return None, False

        soup = BeautifulSoup(resp.text, "lxml")
        for card in soup.select(".base-card, .job-search-card"):
            title_el   = card.select_one(".base-search-card__title")
            company_el = card.select_one(".base-search-card__subtitle")
            time_el    = card.select_one("time[datetime]")
            if not (title_el and company_el and time_el):
                continue
            # Loose match: first 15 chars of title + first 10 of company name
            if (ci(job_title[:15]) in ci(title_el.get_text()) and
                    ci(company_name[:10]) in ci(company_el.get_text())):
                is_repost = "repost" in ci(time_el.get_text())
                try:
                    return date.fromisoformat(time_el["datetime"][:10]), is_repost
                except (ValueError, KeyError):
                    return None, is_repost
    except Exception as exc:
        log.debug("  LinkedIn check error for '%s': %s", job_title, exc)
    return None, False


def linkedin_is_fresh(job_title, company_name):
    """Return True if the job should be alerted (fresh or unseen on LinkedIn).

    Skips when:
      • Found on LinkedIn AND is_repost=True  → ghost job, already circulated
      • Found on LinkedIn AND age > LINKEDIN_MAX_AGE days → stale listing
    Includes (fail open) when not found or any error occurs.
    """
    if not LINKEDIN_VALIDATE:
        return True
    posted, is_repost = _linkedin_check(job_title, company_name)
    if posted is None and not is_repost:
        return True   # not on LinkedIn yet = brand new, or check failed = include
    if is_repost:
        log.info("  ⏭  Skipping '%s' — reposted on LinkedIn (ghost job)", job_title)
        return False
    age = (date.today() - posted).days
    if age > LINKEDIN_MAX_AGE:
        log.info("  ⏭  Skipping '%s' — already on LinkedIn (%d days old)", job_title, age)
        return False
    return True


# ── Email ──────────────────────────────────────────────────────────────────────

def send_email(results, db_updated):
    total_jobs   = sum(len(r["new_jobs"]) for r in results)
    page_changes = sum(1 for r in results if r["page_changed"] and not r["new_jobs"])
    date_str     = datetime.today().strftime("%d %b %Y")

    subject = (
        f"🚨 Job Alert: {total_jobs} new role(s)"
        + (f" + {page_changes} to check" if page_changes else "")
        + f" — {date_str}"
    )

    # HTML job rows
    job_rows = ""
    for r in results:
        for j in r["new_jobs"]:
            posted = j["date_posted"].strftime("%d %b") if j.get("date_posted") else "—"
            job_rows += (
                f"<tr style='border-bottom:1px solid #f3f4f6'>"
                f"<td style='padding:12px 14px 12px 0;font-weight:600;font-size:14px'>{r['company']}</td>"
                f"<td style='padding:12px 14px 12px 0;font-size:14px'>{j['title']}</td>"
                f"<td style='padding:12px 14px 12px 0;color:#6b7280;font-size:13px'>{j['location']}</td>"
                f"<td style='padding:12px 14px 12px 0;color:#6b7280;font-size:13px'>{posted}</td>"
                f"<td style='padding:12px 0'>"
                f"<a href='{j['url']}' style='background:#2563eb;color:#fff;padding:5px 14px;"
                f"border-radius:5px;text-decoration:none;font-size:13px;font-weight:600'>Apply →</a>"
                f"</td></tr>"
            )

    page_rows = ""
    for r in results:
        if r["page_changed"] and not r["new_jobs"]:
            note = ("JS-rendered — no static content for AI to parse"
                    if r.get("js_rendered")
                    else "Page updated — AI found no matching roles")
            page_rows += (
                f"<tr style='border-bottom:1px solid #f3f4f6'>"
                f"<td style='padding:12px 14px 12px 0;font-weight:600;font-size:14px'>"
                f"<a href='{r['company_url']}' style='color:#111;text-decoration:none'>{r['company']}</a>"
                f"</td>"
                f"<td style='padding:12px 14px 12px 0;font-size:13px;color:#6b7280'>{note}</td>"
                f"<td style='padding:12px 14px 12px 0;color:#6b7280;font-size:13px'>—</td>"
                f"<td style='padding:12px 14px 12px 0;color:#6b7280;font-size:13px'>—</td>"
                f"<td style='padding:12px 0'>"
                f"<a href='{r['company_url']}' style='background:#f59e0b;color:#fff;padding:5px 14px;"
                f"border-radius:5px;text-decoration:none;font-size:13px;font-weight:600'>Check →</a>"
                f"</td></tr>"
            )

    db_note = (
        "<p style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;"
        "padding:10px 14px;font-size:13px;color:#166534;margin-top:24px'>"
        "📊 <strong>jobs_database.csv</strong> has been updated with today's findings. "
        "Check your GitHub repo's Actions artifacts to download the latest version."
        "</p>"
    ) if db_updated else ""

    html = f"""<html><body style="font-family:'Segoe UI',Arial,sans-serif;color:#111;max-width:720px;margin:auto;padding:24px">
  <div style="background:linear-gradient(135deg,#1d4ed8,#1e40af);border-radius:10px;padding:22px 28px;margin-bottom:28px">
    <h2 style="color:#fff;margin:0 0 6px">🚨 Job Alert — {date_str}</h2>
    <p style="color:#bfdbfe;margin:0;font-size:14px">
      <strong style="color:#fff">Roles:</strong> Project Manager · Program Manager (Senior / Mid-level) &nbsp;|&nbsp;
      <strong style="color:#fff">Areas:</strong> Munich · Nuremberg
    </p>
  </div>

  <table style='border-collapse:collapse;width:100%'>
    <thead><tr style='border-bottom:2px solid #e5e7eb'>
      <th style='text-align:left;padding:8px 14px 8px 0;font-size:13px;color:#6b7280'>COMPANY</th>
      <th style='text-align:left;padding:8px 14px 8px 0;font-size:13px;color:#6b7280'>ROLE</th>
      <th style='text-align:left;padding:8px 14px 8px 0;font-size:13px;color:#6b7280'>LOCATION</th>
      <th style='text-align:left;padding:8px 14px 8px 0;font-size:13px;color:#6b7280'>POSTED</th>
      <th></th>
    </tr></thead>
    <tbody>{job_rows}{page_rows}</tbody>
  </table>

  {db_note}

  <p style="margin-top:32px;font-size:12px;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:16px">
    Sent by your GitHub Actions Job Tracker ·
    Edit <code>ROLE_KEYWORDS</code> / <code>LOCATION_KEYWORDS</code> in <code>checker.py</code> to adjust filters.
  </p>
</body></html>"""

    # Plain text
    lines = [f"Job Alert — {date_str}", "=" * 50,
             "Filters: Project/Program Manager | Senior & Mid | Munich & Nuremberg\n"]
    for r in results:
        for j in r["new_jobs"]:
            posted = j["date_posted"].strftime("%Y-%m-%d") if j.get("date_posted") else "unknown date"
            lines += [f"[{r['company']}] {j['title']}", f"  Posted:   {posted}",
                      f"  Location: {j['location']}", f"  {j['url']}", ""]
    for r in results:
        if r["page_changed"] and not r["new_jobs"]:
            lines += [f"[{r['company']}] Career page updated — check for new positions",
                      f"  {r['company_url']}", ""]
    plain = "\n".join(lines)

    # Build message
    msg = MIMEMultipart("mixed")
    all_bcc = NOTIFY_EMAILS + BCC_EMAILS
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = GMAIL_USER          # sender only in To — all recipients are hidden in Bcc
    msg["Bcc"]     = ", ".join(all_bcc)

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(plain, "plain"))
    body.attach(MIMEText(html, "html"))
    msg.attach(body)

    # Attach the CSV database
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition",
                            f"attachment; filename=jobs_database_{datetime.today().strftime('%Y%m%d')}.csv")
            msg.attach(part)
        log.info("Attached jobs_database.csv to email")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASSWORD)
        s.sendmail(GMAIL_USER, all_bcc, msg.as_string())
    log.info("✉  Email sent (BCC) to: %s", ", ".join(all_bcc))

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("── Job Tracker starting %s ──", datetime.now().isoformat())
    if AI_ENABLED:
        log.info("AI contextual search: ENABLED (Gemini Flash)")
    else:
        log.warning("AI contextual search: DISABLED — add GEMINI_API_KEY as a GitHub Actions secret "
                    "(Settings → Secrets → New secret → name: GEMINI_API_KEY)")
    init_db()
    existing_db = load_db()
    state       = load_state()
    results     = []
    new_db_rows = []

    for company in COMPANIES:
        name, url = company["name"], company["url"]
        log.info("Checking: %s", name)

        # Route to native API or HTML scraping depending on the platform
        html      = None
        fp_source = None
        if "greenhouse.io" in url:
            fp_source, found = fetch_greenhouse_jobs(url)
        elif "lever.co" in url:
            fp_source, found = fetch_lever_jobs(url)
        elif "myworkdayjobs.com" in url:
            fp_source, found = fetch_workday_jobs(url)
        elif "recruitee.com" in url:
            fp_source, found = fetch_recruitee_jobs(url)
        else:
            html = fetch(url)
            if not html:
                continue
            fp_source = html
            found = extract_jobs(html, url)

        if fp_source is None:
            continue  # API or fetch error — skip this company

        # Fingerprint: hash HTML (boilerplate-stripped) or the API response string
        fp        = page_fingerprint(fp_source) if html else hashlib.sha256(fp_source.encode()).hexdigest()
        old_fp    = state.get(f"{name}__hash")
        known     = set(state.get(f"{name}__jobs", []))
        first_run = old_fp is None
        changed   = (not first_run) and (fp != old_fp)

        # AI layer 1: contextually validate keyword-matched jobs
        if AI_ENABLED and found:
            found = ai_validate_jobs(found, name)

        # AI layer 2: fallback extraction when keyword matching found nothing.
        # Runs on every check (not just first_run/changed) — same jobs won't re-alert
        # because they'll already be in the `known` set from a previous run.
        # Skipped for API-sourced companies (they already return structured data).
        if AI_ENABLED and html and not found:
            found = ai_extract_jobs(get_page_text(html), url, name)

        # Jobs not yet in the known-titles set (unseen across all previous runs)
        new_to_known = [j for j in found if ci(j["title"]) not in known]

        # Date filter: only alert on jobs posted today or yesterday.
        # Unknown date (None) is included — never silently drop a job we can't date.
        new_jobs = [j for j in new_to_known if is_recent(j.get("date_posted"))]

        # LinkedIn validation: cross-check each job against LinkedIn.
        # Jobs already circulating on LinkedIn for > LINKEDIN_MAX_AGE days are skipped.
        # Not found on LinkedIn = brand new on the company site = include.
        # Fails open on any network/parsing error.
        if LINKEDIN_VALIDATE and new_jobs:
            validated = []
            for j in new_jobs:
                if linkedin_is_fresh(j["title"], name):
                    validated.append(j)
                time.sleep(1)   # gentle throttle — avoid hammering LinkedIn
            new_jobs = validated

        skipped = len(new_to_known) - len(new_jobs)
        log.info("  → %d matching / %d unseen / %d recent%s",
                 len(found), len(new_to_known), len(new_jobs),
                 f" ({skipped} skipped — older posting date)" if skipped else "")

        # Persist new jobs to CSV (all recent unseen ones)
        for j in new_jobs:
            db_key = (name.lower(), ci(j["title"]))
            if db_key not in existing_db:
                new_db_rows.append({
                    "Date Recorded": datetime.today().strftime("%Y-%m-%d"),
                    "Date Posted":   j["date_posted"].strftime("%Y-%m-%d") if j.get("date_posted") else "",
                    "Company":       name,
                    "Job Title":     j["title"],
                    "Location":      j["location"],
                    "Job URL":       j["url"],
                    "Career Page":   url,
                    "Status":        "New",
                })
                existing_db.add(db_key)

        # Log page changes with no parseable jobs — at most once per company per day
        page_change_today = (name.lower(), "__page_change_today__")
        if not first_run and changed and not new_jobs and page_change_today not in existing_db:
            append_page_change_to_db(name, url)
            existing_db.add(page_change_today)

        if first_run and new_jobs:
            log.info("  🆕 First run — alerting on %d recent job(s): %s",
                     len(new_jobs), [j["title"] for j in new_jobs])
        elif first_run:
            log.info("  → First run: baseline saved (no recent postings)")
        elif new_jobs:
            log.info("  🆕 New: %s", [j["title"] for j in new_jobs])
        elif changed:
            log.info("  📄 Page changed, no parseable new jobs")

        # Always update known titles with everything found (prevents stale re-alerts)
        state[f"{name}__hash"] = fp
        state[f"{name}__jobs"] = list(known | {ci(j["title"]) for j in found})

        page_text_len = len(get_page_text(html).strip()) if html else 0
        if new_jobs or (not first_run and changed):
            results.append({
                "company":      name,
                "company_url":  url,
                "new_jobs":     new_jobs,
                "page_changed": changed,
                "js_rendered":  html is not None and page_text_len < 200,
            })

    # Write new rows to CSV
    if new_db_rows:
        append_to_db(new_db_rows)

    save_state(state)

    if results:
        log.info("Sending email to %d recipient(s)…", len(NOTIFY_EMAILS))
        send_email(results, db_updated=bool(new_db_rows))
    else:
        log.info("No new matching roles today.")

    log.info("── Done ──")

if __name__ == "__main__":
    main()
