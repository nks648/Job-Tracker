# 🚀 Job Tracker — Setup Guide

Monitors 35 company career pages daily and emails you when new jobs appear.
Runs for **free** on GitHub Actions.

---

## 📁 Files

```
job_tracker/
├── checker.py                        ← main script
├── requirements.txt                  ← Python dependencies
├── .github/
│   └── workflows/
│       └── job_tracker.yml           ← GitHub Actions schedule
└── README.md
```

---

## 🔧 One-Time Setup (15 minutes)

### Step 1 — Create a Gmail App Password

> You need this so the script can send email on your behalf.
> It's a separate 16-character password — NOT your Gmail login.

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** (required)
3. Search for **"App Passwords"** in the search bar
4. Create a new app password:
   - App name: `Job Tracker`
5. Copy the 16-character password (e.g. `abcd efgh ijkl mnop`)

---

### Step 2 — Create a GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Create a **private** repository called `job-tracker`
3. Upload all three files:
   - `checker.py`
   - `requirements.txt`
   - `.github/workflows/job_tracker.yml`

---

### Step 3 — Add GitHub Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these 3 secrets:

| Secret Name         | Value                                      |
|---------------------|--------------------------------------------|
| `GMAIL_USER`        | your Gmail address (e.g. `you@gmail.com`)  |
| `GMAIL_APP_PASSWORD`| the 16-char app password from Step 1       |
| `NOTIFY_EMAIL`      | email to receive alerts (can be same)      |

---

### Step 4 — Test It Manually

1. Go to your repo → **Actions** tab
2. Click **"Daily Job Tracker"**
3. Click **"Run workflow"** → **"Run workflow"**
4. Watch the logs — on the first run it saves a baseline (no email)
5. Run it a **second time** to confirm email delivery works

> 💡 Tip: On the second manual run you won't get an email unless a page actually changed. To force a test email, temporarily edit `checker.py` line near the bottom to `if True:` instead of `if changed:`, run once, then revert.

---

## ⏰ Schedule

The workflow runs every day at **07:00 UTC**.

To change the time, edit `.github/workflows/job_tracker.yml`:
```yaml
- cron: "0 7 * * *"
#        │ │ │ │ └─ day of week (*)
#        │ │ │ └─── month (*)
#        │ │ └───── day of month (*)
#        │ └─────── hour in UTC (7 = 07:00 UTC = 08:00 CET / 09:00 CEST)
#        └───────── minute (0)
```

Common times (UTC):
- `0 6 * * *` → 06:00 UTC (07:00 CET)
- `0 7 * * *` → 07:00 UTC (08:00 CET) ← default
- `0 8 * * *` → 08:00 UTC (09:00 CEST in summer)

---

## 📧 What the Email Looks Like

**Subject:** 🚨 Job Alert: 3 career page(s) updated – 14 Mar 2025

**Body:**
> Changes were detected on **3** career page(s). Check them out before the listings disappear!
>
> | Company        | Link                     |
> |----------------|--------------------------|
> | Marvel Fusion  | Open careers page →      |
> | Constellr      | Open careers page →      |
> | Mynaric        | Open careers page →      |

---

## ➕ Adding or Removing Companies

Edit the `COMPANIES` list in `checker.py`:

```python
# Add a company:
{"name": "New Company", "url": "https://example.com/careers"},

# Remove a company:
# Just delete its line from the list
```

---

## ⚠️ Known Limitations

- **JavaScript-heavy pages**: Some sites load jobs via JavaScript (e.g. Workday). 
  The script still detects *something changed* but may not extract individual job titles.
  This is fine — it tells you to go check the page manually.

- **First run = baseline**: On the very first run no email is sent. 
  The script just saves the current state as the baseline.

- **GitHub Actions free tier**: 2,000 minutes/month free for private repos.
  This job uses ~2 minutes/day = ~60 min/month. Well within limits.

---

## 🛠 Troubleshooting

| Problem | Solution |
|---------|----------|
| No email received | Check Gmail spam. Verify secrets are correct in GitHub. |
| Workflow not running | Confirm the `.yml` file is in `.github/workflows/` exactly |
| App password rejected | Regenerate it — spaces are fine, copy all 16 chars |
| Page always shows as changed | The site randomises its content (e.g. ads). Add it to an exclusion list in `checker.py` |
