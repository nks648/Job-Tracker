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
import html as html_mod
import hashlib
import smtplib
import csv
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, parse_qs, quote
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# FILTER CONFIG
# ══════════════════════════════════════════════════════════════════════════════

ROLE_KEYWORDS = [
    "project manager", "program manager", "programme manager",
    "projektmanager", "projektleiter", "programm manager",
    "project lead", "project leader", "projektleitung",
    "delivery manager", "technical project manager", "technical program manager",
    "pmo manager", "it project manager",
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
    "parsdorf",
    "nuremberg", "nürnberg", "nurnberg", "erlangen",
    "fürth", "furth", "schwabach", "herzogenaurach",
    "remote", "hybrid", "germany", "deutschland", "bavaria", "bayern",
]
# Compiled once at import time — reused across all calls to extract_location_hint()
_LOCATION_REGEXES = [
    re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)[^\n,|•·]{{0,40}}", re.IGNORECASE)
    for kw in LOCATION_KEYWORDS
]

# ══════════════════════════════════════════════════════════════════════════════
# COMPANY LIST
# ══════════════════════════════════════════════════════════════════════════════

COMPANIES = [
    {"name": "OHB AG",             "url": "https://career-ohb.csod.com/ux/ats/careersite/4/home?c=career-ohb&cfdd%5B0%5D%5Bid%5D=16&cfdd%5B0%5D%5Boptions%5D%5B0%5D=29&lq=Munich%252C%2520Germany&pl=ChIJ2V-Mo_l1nkcRfZixfUq4DAE&lang=en-GB"},
    {"name": "Ariane Group",        "url": "https://arianegroup.wd3.myworkdayjobs.com/fr-FR/EXTERNALALL?locations=a18ef726d665016eab2a92b8fa1c0dbb"},
    {"name": "GE Aerospace",        "url": "https://careers.geaerospace.com/global/en/search-results?keywords=project+manager&location=Munich%2C+Germany&locationRadius=50mi"},
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
    {"name": "Siemens",             "url": "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/?42414=%5B812132%5D&42414_format=17570&42415=%5B813141%5D&42415_format=17571&listFilterMode=1&folderRecordsPerPage=20"},
    {"name": "Siemens Energy",      "url": "https://jobs.siemens-energy.com/en_US/jobs/Jobs/?29454=964485&29454_format=11381&29455=964685&29455_format=11382&listFilterMode=1&folderRecordsPerPage=20"},
    {"name": "Rheinmetall",         "url": "https://www.rheinmetall.com/en/career/vacancies?9dc11c304b4c06c2f71c48cc6574e7e5filter=%257B%2522countries%2522%253A%255B%2522Germany%2522%255D%252C%2522cities%2522%253A%255B%2522M%25C3%25BCnchen%2522%255D%257D"},
    {"name": "Bosch",               "url": "https://jobs.bosch.com/en?pages=1&country=de&location=M%C3%BCnchen+-+Mitte#"},
    {"name": "KNDS",                "url": "https://jobs.knds.de/content/search/?locale=de_DE&currentPage=1&pageSize=50&addresses%252Fname=M%C3%BCnchen"},
    {"name": "Avilus",              "url": "https://www.avilus.com/career"},
    {"name": "MBDA",                "url": "https://www.mbda-careers.de/ema/?_locations%5B%5D=Ottobrunn&_order=ASC&_page=1"},
    {"name": "KraussMaffei",        "url": "https://jobs.kraussmaffei.com/search/?createNewAlert=false&q=&locationsearch=Parsdorf"},
    {"name": "Puma",                "url": "https://about.puma.com/en/careers/job-openings?area=all&location=441"},
    {"name": "Huber+Suhner",        "url": "https://recruiting.hubersuhner.com/Jobs/All"},
    {"name": "SAP AG",              "url": "https://jobs.sap.com/search/?createNewAlert=false&q=project+manager&locationsearch=Munich&optionsFacetsDD_country=DE"},
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
    {"name": "Isar Aerospace",      "url": "https://www.isarspace.com/careers#jobs"},
    {"name": "Rohde & Schwarz",     "url": "https://www.rohde-schwarz.com/us/jobs/search-jobs_109605.html?filters=countries_Germany"},
    {"name": "BMW",                 "url": "https://www.bmwgroup.jobs/de/en/jobfinder.html?location=munich&department=project-management"},
    {"name": "Munich Re",           "url": "https://www.munichre.com/en/company/careers/job-opportunities.html?location=munich"},
    {"name": "Linde",               "url": "https://jobs.linde.com/en/jobs?country=Germany&city=Pullach"},
    {"name": "MAN Energy Solutions","url": "https://www.man-es.com/company/careers/job-offerings?location=Germany"},
]

# ── Config ─────────────────────────────────────────────────────────────────────
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
# Multiple recipients: comma-separated in the secret
# e.g. "nagarjun@gmail.com,friend@gmail.com"
NOTIFY_EMAILS  = [e.strip() for e in os.environ.get("NOTIFY_EMAIL", GMAIL_USER).split(",")]
STATE_FILE     = os.environ.get("STATE_FILE", "job_state.json")
DB_FILE           = "jobs_database.csv"
MAX_JOB_AGE_DAYS  = 3   # only alert on jobs posted within this many days

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
    for pattern in _LOCATION_REGEXES:
        m = pattern.search(text)
        if m:
            return m.group(0).strip()[:60]
    return None

# ── CSV Database ───────────────────────────────────────────────────────────────

def init_db():
    """Create CSV with headers if it doesn't exist; migrate schema if needed."""
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=DB_COLUMNS).writeheader()
        log.info("Created new jobs_database.csv")
        return
    # Migrate: rewrite header + rows if a column is missing
    with open(DB_FILE, newline="", encoding="utf-8") as f:
        reader     = csv.DictReader(f)
        existing   = set(reader.fieldnames or [])
        old_rows   = list(reader) if not existing.issuperset(DB_COLUMNS) else None
    if old_rows is not None:
        with open(DB_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=DB_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in old_rows:
                writer.writerow({col: row.get(col, "") for col in DB_COLUMNS})
        log.info("Migrated jobs_database.csv to updated schema")

def load_db():
    """Load existing records as a set of (company, title) tuples to avoid duplicates."""
    existing = set()
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add((row["Company"].lower(), row["Job Title"].lower()))
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

def append_page_change_to_db(company, career_url, existing_db):
    """Log a page change (JS-rendered, manual check needed). One row per company per day."""
    today = datetime.today().strftime("%Y-%m-%d")
    db_key = (company.lower(), f"⚠️ page changed — check manually ({today})")
    if db_key in existing_db:
        return
    existing_db.add(db_key)
    with open(DB_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_COLUMNS)
        writer.writerow({
            "Date Recorded": today,
            "Date Posted":   "",
            "Company":       company,
            "Job Title":     "⚠️ Page changed — check manually",
            "Location":      "Unknown (JS-rendered)",
            "Job URL":       career_url,
            "Career Page":   career_url,
            "Status":        "Needs Manual Check",
        })

# ── Job extraction ─────────────────────────────────────────────────────────────

def extract_jobs(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    base = urlparse(page_url)

    def abs_url(href):
        if not href: return page_url
        return urljoin(page_url, href)

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        if not (5 < len(title) < 160): continue
        if not is_relevant_role(title): continue
        parent = a.find_parent()
        ctx = parent.get_text(" ", strip=True) if parent else ""
        location = extract_location_hint(ctx) or "See posting"
        if location != "See posting" and not is_relevant_location(location): continue
        jobs.append({"title": title, "location": location, "url": abs_url(a["href"]),
                     "posted_date": _parse_posted_ago(ctx)})

    if not jobs:
        for tag in soup.find_all(["li", "div", "article"]):
            text = tag.get_text(" ", strip=True)
            if not is_relevant_role(text[:200]): continue
            if not is_relevant_location(text): continue
            inner = tag.find("a", href=True)
            title_text = inner.get_text(strip=True) if inner else text[:100]
            location   = extract_location_hint(text) or "See posting"
            jobs.append({"title": title_text, "location": location,
                         "url": abs_url(inner["href"] if inner else None),
                         "posted_date": _parse_posted_ago(text)})

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
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("⚠  State file unreadable (%s) — starting fresh baseline", exc)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def fetch(url):
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)  # 1s, 2s
            else:
                log.warning("  ⚠  Could not fetch %s: %s", url, exc)
    return None

def page_fingerprint(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script","style","nav","header","footer","noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return hashlib.sha256(text.encode()).hexdigest()

# ── Email ──────────────────────────────────────────────────────────────────────

def send_email(results, db_updated):
    total_jobs   = sum(len(r["new_jobs"]) for r in results)
    page_changes = sum(1 for r in results if r["page_changed"] and not r["new_jobs"])
    now          = datetime.today()
    date_str     = now.strftime("%d %b %Y")
    time_str     = now.strftime("%H:%M")

    subject = (
        f"🚨 Job Alert: {total_jobs} new role(s) found"
        + (f" + {page_changes} page change(s)" if page_changes else "")
        + f" — {date_str} {time_str}"
    )

    # HTML job rows
    job_rows = ""
    for r in results:
        for j in r["new_jobs"]:
            company  = html_mod.escape(r["company"])
            title    = html_mod.escape(j["title"])
            location = html_mod.escape(j["location"])
            job_url  = html_mod.escape(j["url"], quote=True)
            job_rows += (
                f"<tr style='border-bottom:1px solid #f3f4f6'>"
                f"<td style='padding:12px 14px 12px 0;font-weight:600;font-size:14px'>{company}</td>"
                f"<td style='padding:12px 14px 12px 0;font-size:14px'>{title}</td>"
                f"<td style='padding:12px 14px 12px 0;color:#6b7280;font-size:13px'>{location}</td>"
                f"<td style='padding:12px 0'>"
                f"<a href='{job_url}' style='background:#2563eb;color:#fff;padding:5px 14px;"
                f"border-radius:5px;text-decoration:none;font-size:13px;font-weight:600'>Apply →</a>"
                f"</td></tr>"
            )

    page_rows = ""
    for r in results:
        if r["page_changed"] and not r["new_jobs"]:
            company     = html_mod.escape(r["company"])
            company_url = html_mod.escape(r["company_url"], quote=True)
            page_rows += (
                f"<tr style='border-bottom:1px solid #f3f4f6'>"
                f"<td style='padding:10px 14px 10px 0;font-weight:600'>{company}</td>"
                f"<td colspan='2' style='padding:10px 14px 10px 0;color:#6b7280;font-size:13px'>"
                f"Page updated — likely JS-rendered, check manually</td>"
                f"<td><a href='{company_url}' style='color:#2563eb;font-size:13px'>Visit →</a></td>"
                f"</tr>"
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

  {"<h3 style='color:#1d4ed8;margin:0 0 10px'>✅ " + str(total_jobs) + " New Matching Role(s)</h3><table style='border-collapse:collapse;width:100%'><thead><tr style='border-bottom:2px solid #e5e7eb'><th style='text-align:left;padding:8px 14px 8px 0;font-size:13px;color:#6b7280'>COMPANY</th><th style='text-align:left;padding:8px 14px 8px 0;font-size:13px;color:#6b7280'>ROLE</th><th style='text-align:left;padding:8px 14px 8px 0;font-size:13px;color:#6b7280'>LOCATION</th><th></th></tr></thead><tbody>" + job_rows + "</tbody></table>" if job_rows else ""}

  {"<h3 style='color:#f59e0b;margin:28px 0 6px'>⚠️ Pages Changed — Manual Check Needed</h3><p style='color:#6b7280;font-size:13px;margin:0 0 10px'>These pages updated but jobs couldn't be auto-extracted (JS-rendered sites).</p><table style='border-collapse:collapse;width:100%'><tbody>" + page_rows + "</tbody></table>" if page_rows else ""}

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
            lines += [f"[{r['company']}] {j['title']}", f"  Location: {j['location']}", f"  {j['url']}", ""]
    for r in results:
        if r["page_changed"] and not r["new_jobs"]:
            lines.append(f"PAGE CHANGED: {r['company']} — {r['company_url']}")
    plain = "\n".join(lines)

    # Build message
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = ", ".join(NOTIFY_EMAILS)   # ← multiple recipients

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

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASSWORD)
            s.sendmail(GMAIL_USER, NOTIFY_EMAILS, msg.as_string())
        log.info("✉  Email sent to: %s", ", ".join(NOTIFY_EMAILS))
    except smtplib.SMTPRecipientsRefused as exc:
        log.error("✉  Delivery failed for one or more recipients: %s", exc.recipients)
    except smtplib.SMTPAuthenticationError:
        log.error("✉  SMTP authentication failed — check GMAIL_USER / GMAIL_APP_PASSWORD")
    except Exception as exc:
        log.error("✉  Failed to send email: %s", exc)

# ── Posting-date helpers ───────────────────────────────────────────────────────

_DATE_FMTS = (
    "%d-%b-%Y",                  # 16-Mar-2026
    "%Y-%m-%d",                  # 2026-03-16
    "%Y-%m-%dT%H:%M:%S.%fZ",    # 2026-03-16T10:30:00.000Z     (UTC literal Z)
    "%Y-%m-%dT%H:%M:%SZ",       # 2026-03-16T10:30:00Z          (UTC literal Z)
    "%Y-%m-%dT%H:%M:%S.%f%z",   # 2026-03-16T10:30:00.000+0000 (e.g. SmartRecruiters)
    "%Y-%m-%dT%H:%M:%S%z",      # 2026-03-16T10:30:00+01:00    (e.g. Personio)
)

def parse_posted_date(raw):
    """Return datetime.date from various date/timestamp strings, or None."""
    if not raw:
        return None
    raw = str(raw).strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None

def _parse_workday_posted_on(text):
    """Convert Workday's relative 'Posted N Days Ago' strings to a date.

    Expects a clean, isolated string (e.g. the `postedOn` field from the
    Workday API).  Do NOT pass a full job-card blob — use _parse_posted_ago
    instead for untrusted freeform context text.
    """
    if not text:
        return None
    t = text.lower()
    today = datetime.today().date()
    # Check numeric pattern first so "Posted 30+ Days Ago — Closes Today"
    # resolves to 30 days ago rather than today.
    m = re.search(r"(\d+)\+?\s*day", t)
    if m:
        return today - timedelta(days=int(m.group(1)))
    if "today" in t:
        return today
    if "yesterday" in t:
        return today - timedelta(days=1)
    return None

def _parse_posted_ago(text):
    """Extract a 'posted N days ago' date from freeform job-card context.

    Stricter than _parse_workday_posted_on: the digit must be preceded by
    'posted' within the same phrase so that unrelated text such as
    '45 day probation period' or '2 business days response time' does NOT
    produce a false date that would cause valid new jobs to be discarded.
    """
    if not text:
        return None
    t = text.lower()
    today = datetime.today().date()
    # "posted today" / "posted: today"
    if re.search(r"posted\b.{0,20}\btoday\b", t):
        return today
    # "posted yesterday"
    if re.search(r"posted\b.{0,20}\byesterday\b", t):
        return today - timedelta(days=1)
    # "posted 6 days ago", "posted 30+ days ago"
    m = re.search(r"posted\b.{0,20}?(\d+)\+?\s*days?\s+ago", t)
    if m:
        return today - timedelta(days=int(m.group(1)))
    return None

def fetch_posting_date(job_url):
    """Fetch a job detail page and extract its posting date (best-effort)."""
    html = fetch(job_url)
    if not html:
        return None
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    # "Posted since: 16-Mar-2026"  (Siemens / Phenom)
    m = re.search(r"posted\s+since[:\s]+(\d{1,2}-\w{3}-\d{4})", text, re.IGNORECASE)
    if m:
        return parse_posted_date(m.group(1))
    # ISO date near "posted"
    m = re.search(r"posted[^:]*?:\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if m:
        return parse_posted_date(m.group(1))
    return None

def is_recent(job):
    """Return True if the job was posted within MAX_JOB_AGE_DAYS (or date unknown)."""
    d = job.get("posted_date")
    if d is None:
        return True   # no date available — don't discard
    return (datetime.today().date() - d).days <= MAX_JOB_AGE_DAYS

# ── ATS API fetchers ───────────────────────────────────────────────────────────

def fetch_greenhouse_jobs(url):
    """Fetch jobs from Greenhouse ATS via its public JSON API."""
    parsed = urlparse(url)
    slug   = parsed.path.strip("/")
    if "eu.greenhouse.io" in url:
        api_url = f"https://job-boards.eu.greenhouse.io/v1/boards/{slug}/jobs"
    else:
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("  ⚠  Greenhouse API error (%s): %s", url, exc)
        return None
    jobs = []
    for job in data.get("jobs", []):
        title    = job.get("title", "")
        location = (job.get("location") or {}).get("name", "") or ""
        job_url  = job.get("absolute_url", url)
        if not is_relevant_role(title):
            continue
        if location and not is_relevant_location(location):
            continue
        jobs.append({
            "title": title, "location": location or "See posting", "url": job_url,
            "posted_date": parse_posted_date(job.get("first_published_at", "")),
        })
    return jobs

def fetch_lever_jobs(url):
    """Fetch jobs from Lever ATS via its public JSON API."""
    parsed  = urlparse(url)
    slug    = parsed.path.strip("/")
    qs      = parse_qs(parsed.query)
    location_param = qs.get("location", [None])[0]
    api_url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    if location_param:
        api_url += f"&location={quote(location_param)}"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("  ⚠  Lever API error (%s): %s", url, exc)
        return None
    jobs = []
    for posting in data:
        title      = posting.get("text", "")
        categories = posting.get("categories", {})
        location   = categories.get("location", "") or ""
        job_url    = posting.get("hostedUrl", url)
        if not is_relevant_role(title):
            continue
        if location and not is_relevant_location(location):
            continue
        created_ms  = posting.get("createdAt")
        posted_date = (datetime.fromtimestamp(created_ms / 1000).date() if created_ms else None)
        jobs.append({
            "title": title, "location": location or "See posting", "url": job_url,
            "posted_date": posted_date,
        })
    return jobs

def fetch_recruitee_jobs(url):
    """Fetch jobs from Recruitee ATS via its public JSON API."""
    parsed    = urlparse(url)
    subdomain = parsed.netloc.split(".")[0]
    api_url   = f"https://{subdomain}.recruitee.com/api/offers/"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("  ⚠  Recruitee API error (%s): %s", url, exc)
        return None
    jobs = []
    for offer in data.get("offers", []):
        title    = offer.get("title", "")
        location = offer.get("location", "") or offer.get("city", "") or ""
        job_url  = offer.get("careers_url", url)
        if not is_relevant_role(title):
            continue
        if location and not is_relevant_location(location):
            continue
        jobs.append({
            "title": title, "location": location or "See posting", "url": job_url,
            "posted_date": parse_posted_date(offer.get("published_at", "")),
        })
    return jobs

def fetch_personio_jobs(url):
    """Fetch jobs from Personio ATS via its public JSON API."""
    parsed  = urlparse(url)
    base    = f"{parsed.scheme}://{parsed.netloc}"
    api_url = f"{base}/api/jobs"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("  ⚠  Personio API error (%s): %s", url, exc)
        return None
    jobs = []
    for job in data:
        title  = job.get("name", "") or ""
        # office can be a dict {"name": "Munich"} or a plain string
        office = job.get("office") or ""
        location = (office.get("name", "") if isinstance(office, dict) else str(office)).strip()
        # Build direct job link from id; fall back to career page
        job_id  = job.get("id")
        job_url = f"{base}/job/{job_id}" if job_id else url
        if not is_relevant_role(title):
            continue
        if location and not is_relevant_location(location):
            continue
        jobs.append({
            "title": title, "location": location or "See posting", "url": job_url,
            "posted_date": parse_posted_date(job.get("createdAt", "") or job.get("created_at", "")),
        })
    return jobs

_SR_COUNTRY_NAMES = {"DE": "Germany", "AT": "Austria", "CH": "Switzerland", "FR": "France"}

def fetch_smartrecruiters_jobs(url):
    """Fetch jobs from SmartRecruiters ATS via its public API.

    Auto-detects the company identifier from a jobs.smartrecruiters.com link
    embedded in the page source, then calls the documented public postings API.
    """
    html = fetch(url)
    if not html:
        return None
    # The page source always contains at least one canonical SR link of the form
    # jobs.smartrecruiters.com/{CompanyIdentifier}/...
    m = re.search(r'jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)', html)
    if not m:
        m = re.search(r'"companyIdentifier"\s*:\s*"([^"]+)"', html)
    if not m:
        log.warning("  ⚠  SmartRecruiters: could not detect company identifier (%s)", url)
        return None
    company_id = m.group(1)
    api_base   = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
    jobs, offset = [], 0
    while True:
        try:
            resp = requests.get(api_base, headers=HEADERS,
                                params={"limit": 100, "offset": offset}, timeout=25)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("  ⚠  SmartRecruiters API error (%s): %s", url, exc)
            break
        content = data.get("content", [])
        total   = data.get("totalFound", 0)
        for posting in content:
            title = posting.get("name", "") or ""
            loc   = posting.get("location") or {}
            city  = loc.get("city", "") or ""
            country = _SR_COUNTRY_NAMES.get(loc.get("country", ""), loc.get("country", ""))
            location = ", ".join(p for p in [city, country] if p)
            job_url  = posting.get("ref", url)
            if not is_relevant_role(title):
                continue
            if location and not is_relevant_location(location):
                continue
            jobs.append({
                "title": title, "location": location or "See posting", "url": job_url,
                "posted_date": parse_posted_date(posting.get("releasedDate", "")),
            })
        offset += len(content)
        if offset >= total or not content:
            break
    return jobs

def fetch_phenom_jobs(url):
    """Fetch jobs from Phenom People ATS via its search API.

    Extracts the domain from the URL's `domain=` query param (or falls back to
    the netloc), then calls the standard Phenom /api/jobs endpoint.
    """
    parsed = urlparse(url)
    qs     = parse_qs(parsed.query)
    domain = (qs.get("domain") or [None])[0] or parsed.netloc
    base   = f"{parsed.scheme}://{parsed.netloc}"
    api_url = f"{base}/api/jobs"
    jobs, start, rows = [], 0, 50
    while True:
        params = {"domain": domain, "query": "project manager",
                  "location": "Munich, Germany", "rows": rows, "start": start}
        try:
            resp = requests.get(api_url, headers=HEADERS, params=params, timeout=25)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("  ⚠  Phenom API error (%s): %s", url, exc)
            break
        batch = data.get("jobs", [])
        total = (data.get("meta") or {}).get("total", 0)
        for job in batch:
            title    = job.get("title", "") or ""
            location = job.get("location", "") or ""
            job_url  = job.get("applyUrl", "") or job.get("url", "") or url
            if not is_relevant_role(title):
                continue
            if location and not is_relevant_location(location):
                continue
            jobs.append({
                "title": title, "location": location or "See posting", "url": job_url,
                "posted_date": parse_posted_date(
                    job.get("datePosted", "") or job.get("postedDate", "")),
            })
        start += len(batch)
        if start >= total or not batch:
            break
    return jobs

def _workday_api_url(url):
    """Parse a Workday career page URL into (api_url, applied_facets, base_url)."""
    parsed = urlparse(url)
    tenant = parsed.netloc.split(".")[0]
    # Path may have an optional locale prefix like /fr-FR/ or /en-US/
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if path_parts and re.match(r'^[a-z]{2}[-_][A-Z]{2}$', path_parts[0]):
        path_parts = path_parts[1:]
    board   = path_parts[0] if path_parts else "careers"
    api_url = f"https://{parsed.netloc}/wday/cxs/{tenant}/{board}/jobs"
    base    = f"{parsed.scheme}://{parsed.netloc}"
    # Preserve location facets already encoded in the URL query string
    facets  = {k: v for k, v in parse_qs(parsed.query).items()}
    return api_url, facets, base

def fetch_workday_jobs(url):
    """Fetch jobs from Workday ATS via its internal JSON API."""
    api_url, facets, base = _workday_api_url(url)
    jobs, offset, limit = [], 0, 20
    while True:
        payload = {"appliedFacets": facets, "limit": limit, "offset": offset, "searchText": ""}
        try:
            resp = requests.post(
                api_url,
                json=payload,
                headers={**HEADERS, "Content-Type": "application/json"},
                timeout=25,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("  ⚠  Workday API error (%s): %s", url, exc)
            break   # return whatever we fetched so far rather than discarding it
        postings = data.get("jobPostings", [])
        total    = data.get("total", 0)
        for posting in postings:
            title    = posting.get("title", "")
            location = posting.get("locationsText", "") or ""
            ext_path = posting.get("externalPath", "")
            job_url  = (base + ext_path) if ext_path else url
            if not is_relevant_role(title):
                continue
            if location and not is_relevant_location(location):
                continue
            jobs.append({
                "title": title, "location": location or "See posting", "url": job_url,
                "posted_date": (_parse_workday_posted_on(posting.get("postedOn", ""))
                               or parse_posted_date(posting.get("postedOn", ""))),
            })
        offset += len(postings)
        if offset >= total or not postings:
            break
    return jobs

ATS_FETCHERS = {
    "greenhouse.io":              fetch_greenhouse_jobs,
    "lever.co":                   fetch_lever_jobs,
    "recruitee.com":              fetch_recruitee_jobs,
    "myworkdayjobs.com":          fetch_workday_jobs,
    "jobs.personio.com":          fetch_personio_jobs,
    "jobs.personio.de":           fetch_personio_jobs,
    # SmartRecruiters (custom career domains)
    "jobs.hensoldt.net":          fetch_smartrecruiters_jobs,
    "careers.ses.com":            fetch_smartrecruiters_jobs,
    "jobs.kraussmaffei.com":      fetch_smartrecruiters_jobs,
    # Phenom People
    "careers.appliedmaterials.com": fetch_phenom_jobs,
    "jobs.infineon.com":          fetch_phenom_jobs,
    "careers.amd.com":            fetch_phenom_jobs,
    "jobs.linde.com":             fetch_phenom_jobs,
}

def detect_ats_fetcher(url):
    for domain, fetcher in ATS_FETCHERS.items():
        if domain in url:
            return fetcher
    return None

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("── Job Tracker starting %s ──", datetime.now().isoformat())
    init_db()
    existing_db = load_db()
    state       = load_state()
    results     = []
    new_db_rows = []

    for company in COMPANIES:
        name, url = company["name"], company["url"]
        log.info("Checking: %s", name)

        ats_fetcher = detect_ats_fetcher(url)
        if ats_fetcher:
            # ── API path: structured data, no fingerprint needed ───────────────
            found     = ats_fetcher(url)
            if found is None:
                continue
            known     = set(state.get(f"{name}__jobs", []))
            first_run = f"{name}__jobs" not in state
            new_jobs  = [] if first_run else [j for j in found if ci(j["title"]) not in known]
            changed   = False
            log.info("  [API] → %d matching / %d new", len(found), len(new_jobs))
        else:
            # ── HTML scraping path: fingerprint-based change detection ─────────
            html = fetch(url)
            if not html:
                continue
            fp        = page_fingerprint(html)
            old_fp    = state.get(f"{name}__hash")
            known     = set(state.get(f"{name}__jobs", []))
            first_run = old_fp is None
            changed   = (not first_run) and (fp != old_fp)
            found     = extract_jobs(html, url)
            new_jobs  = [j for j in found if ci(j["title"]) not in known] if changed else []
            log.info("  → %d matching / %d new", len(found), len(new_jobs))
            state[f"{name}__hash"] = fp
            # Log page changes with no parseable jobs (JS-rendered)
            if not first_run and changed and not found:
                append_page_change_to_db(name, url, existing_db)
            # Enrich with posting dates from detail pages, fetched concurrently
            to_enrich = [j for j in new_jobs if j.get("posted_date") is None and j["url"] != url]
            if to_enrich:
                with ThreadPoolExecutor(max_workers=5) as pool:
                    futures = {pool.submit(fetch_posting_date, j["url"]): j for j in to_enrich}
                    for fut in as_completed(futures):
                        futures[fut]["posted_date"] = fut.result()

        # ── Common: apply recency filter, save to DB ──────────────────────────

        recent_jobs = [j for j in new_jobs if is_recent(j)]
        skipped     = len(new_jobs) - len(recent_jobs)
        if skipped:
            log.info("  ⏩ Skipped %d job(s) older than %d days", skipped, MAX_JOB_AGE_DAYS)

        for j in recent_jobs:
            db_key = (name.lower(), ci(j["title"]))
            if db_key not in existing_db:
                posted_str = j["posted_date"].isoformat() if j.get("posted_date") else ""
                new_db_rows.append({
                    "Date Recorded": datetime.today().strftime("%Y-%m-%d"),
                    "Date Posted":   posted_str,
                    "Company":       name,
                    "Job Title":     j["title"],
                    "Location":      j["location"],
                    "Job URL":       j["url"],
                    "Career Page":   url,
                    "Status":        "New",
                })
                existing_db.add(db_key)

        if first_run:
            log.info("  → First run: baseline saved")
        elif recent_jobs:
            log.info("  🆕 New: %s", [j["title"] for j in recent_jobs])
        elif changed:
            log.info("  📄 Page changed, no parseable new jobs")

        state[f"{name}__jobs"] = [ci(j["title"]) for j in found]

        if not first_run and (recent_jobs or changed):
            results.append({
                "company":      name,
                "company_url":  url,
                "new_jobs":     recent_jobs,
                "page_changed": changed,
            })

    # Write new rows to CSV
    if new_db_rows:
        append_to_db(new_db_rows)

    save_state(state)

    has_new_jobs = any(r["new_jobs"] for r in results)
    if has_new_jobs:
        log.info("Sending email to %d recipient(s)…", len(NOTIFY_EMAILS))
        send_email(results, db_updated=bool(new_db_rows))
    elif results:
        log.info("Only page changes detected — skipping email (already logged to CSV).")
    else:
        log.info("No new matching roles found.")

    log.info("── Done ──")

if __name__ == "__main__":
    main()
