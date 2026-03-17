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
from datetime import datetime
from urllib.parse import urlparse, urljoin
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

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
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
# Multiple recipients: comma-separated in the secret
# e.g. "nagarjun@gmail.com,friend@gmail.com"
NOTIFY_EMAILS  = [e.strip() for e in os.environ.get("NOTIFY_EMAIL", GMAIL_USER).split(",")]
STATE_FILE     = os.environ.get("STATE_FILE", "job_state.json")
DB_FILE        = "jobs_database.csv"

DB_COLUMNS = ["Date Recorded", "Company", "Job Title", "Location", "Job URL", "Career Page", "Status"]

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
        pattern = re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)[^\n,|•·]{{0,40}}", re.IGNORECASE)
        m = pattern.search(text)
        if m:
            return m.group(0).strip()[:60]
    return None

# ── CSV Database ───────────────────────────────────────────────────────────────

def init_db():
    """Create CSV with headers if it doesn't exist."""
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=DB_COLUMNS)
            writer.writeheader()
        log.info("Created new jobs_database.csv")

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
        jobs.append({"title": title, "location": location, "url": abs_url(a["href"])})

    if not jobs:
        for tag in soup.find_all(["li", "div", "article"]):
            text = tag.get_text(" ", strip=True)
            if not is_relevant_role(text[:200]): continue
            if not is_relevant_location(text): continue
            inner = tag.find("a", href=True)
            title_text = inner.get_text(strip=True) if inner else text[:100]
            location   = extract_location_hint(text) or "See posting"
            jobs.append({"title": title_text, "location": location,
                         "url": abs_url(inner["href"] if inner else None)})

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

# ── Email ──────────────────────────────────────────────────────────────────────

def send_email(results, db_updated):
    total_jobs   = sum(len(r["new_jobs"]) for r in results)
    page_changes = sum(1 for r in results if r["page_changed"] and not r["new_jobs"])
    date_str     = datetime.today().strftime("%d %b %Y")

    subject = (
        f"🚨 Job Alert: {total_jobs} new role(s) found"
        + (f" + {page_changes} page change(s)" if page_changes else "")
        + f" — {date_str}"
    )

    # HTML job rows
    job_rows = ""
    for r in results:
        for j in r["new_jobs"]:
            job_rows += (
                f"<tr style='border-bottom:1px solid #f3f4f6'>"
                f"<td style='padding:12px 14px 12px 0;font-weight:600;font-size:14px'>{r['company']}</td>"
                f"<td style='padding:12px 14px 12px 0;font-size:14px'>{j['title']}</td>"
                f"<td style='padding:12px 14px 12px 0;color:#6b7280;font-size:13px'>{j['location']}</td>"
                f"<td style='padding:12px 0'>"
                f"<a href='{j['url']}' style='background:#2563eb;color:#fff;padding:5px 14px;"
                f"border-radius:5px;text-decoration:none;font-size:13px;font-weight:600'>Apply →</a>"
                f"</td></tr>"
            )

    page_rows = ""
    for r in results:
        if r["page_changed"] and not r["new_jobs"]:
            page_rows += (
                f"<tr style='border-bottom:1px solid #f3f4f6'>"
                f"<td style='padding:10px 14px 10px 0;font-weight:600'>{r['company']}</td>"
                f"<td colspan='2' style='padding:10px 14px 10px 0;color:#6b7280;font-size:13px'>"
                f"Page updated — likely JS-rendered, check manually</td>"
                f"<td><a href='{r['company_url']}' style='color:#2563eb;font-size:13px'>Visit →</a></td>"
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

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASSWORD)
        s.sendmail(GMAIL_USER, NOTIFY_EMAILS, msg.as_string())  # ← send to all
    log.info("✉  Email sent to: %s", ", ".join(NOTIFY_EMAILS))

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

        html = fetch(url)
        if not html:
            continue

        fp        = page_fingerprint(html)
        old_fp    = state.get(f"{name}__hash")
        known     = set(state.get(f"{name}__jobs", []))
        first_run = old_fp is None
        changed   = (not first_run) and (fp != old_fp)

        found    = extract_jobs(html, url)
        new_jobs = [j for j in found if ci(j["title"]) not in known] if changed else []
        log.info("  → %d matching / %d new", len(found), len(new_jobs))

        # Save new jobs to DB
        for j in new_jobs:
            db_key = (name.lower(), ci(j["title"]))
            if db_key not in existing_db:
                new_db_rows.append({
                    "Date Recorded": datetime.today().strftime("%Y-%m-%d"),
                    "Company":       name,
                    "Job Title":     j["title"],
                    "Location":      j["location"],
                    "Job URL":       j["url"],
                    "Career Page":   url,
                    "Status":        "New",
                })
                existing_db.add(db_key)

        # Log page changes with no parseable jobs (truly JS-rendered — nothing extracted)
        if not first_run and changed and not found:
            append_page_change_to_db(name, url, existing_db)

        if first_run:
            log.info("  → First run: baseline saved")
        elif new_jobs:
            log.info("  🆕 New: %s", [j["title"] for j in new_jobs])
        elif changed:
            log.info("  📄 Page changed, no parseable new jobs")

        state[f"{name}__hash"] = fp
        state[f"{name}__jobs"] = [ci(j["title"]) for j in found]

        if not first_run and (new_jobs or changed):
            results.append({
                "company":      name,
                "company_url":  url,
                "new_jobs":     new_jobs,
                "page_changed": changed,
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
