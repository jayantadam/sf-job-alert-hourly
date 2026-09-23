# ⏰ Hourly Salesforce Job Alert (8 job portals) + Auto-apply to Recruiter Emails

Every hour this bot:
1. Searches **LinkedIn, Naukri, Foundit, Shine, Cutshort, Talent.com, TimesJobs and Instahyre** for Salesforce Developer / Senior Developer / Apex / LWC / Technical Lead / CPQ / MuleSoft jobs in **Pune & Hyderabad** posted **in the last 1 hour only**. Every job's posting time is checked, e.g. LinkedIn "35 minutes ago", Naukri/Foundit/Cutshort exact timestamps, Shine "x minutes/hours ago".
2. Reads each job ad: experience, skills, salary, work mode, applicants, **recruiter email**.
3. Removes staffing agencies, architect/admin roles, duplicates (including the same job on both sites), jobs outside 4–8 yrs, and **anything it already sent you**.
4. If a job post contains a recruiter email, it **emails that recruiter your resume** with a cover note written for the job. You get a BCC copy.
5. Runs **every hour** and sends **you one email** with the jobs posted in that hour (grouped by city, newest first), 👉 Apply / ⚡ Easy Apply / ✉️ Email HR buttons, a list of recruiters auto-emailed, and a CSV.
   **If nothing was posted in the last hour, no email is sent.**

> This is a separate repo from your daily digest. You can run both.

---

## 📁 What's in this folder
| File | What it is |
|---|---|
| `job_alert.py` | Main script (search, filter, auto-apply, email) |
| `naukri_source.py` | Naukri search (uses a headless Chrome browser) |
| `other_sources.py` | Foundit, TimesJobs, Shine, Instahyre, Cutshort |
| `requirements.txt` | Python packages |
| `.github/workflows/hourly-job-alert.yml` | The hourly schedule + settings |
| `profile.json` | **Your details** used in the cover emails (fill this in) |
| `resume/` | Put **resume.pdf** here |
| `seen_jobs.json`, `applied_jobs.json`, `state.json` | Bot memory (auto-managed) |

---

# 🛠️ Detailed setup for a PUBLIC repo (about 20 minutes, one time)

> Public repo = GitHub Actions is **free and unlimited** (₹0), so it can run every hour 24×7.
> Anyone can see the files and logs, so **your resume, profile and email go into GitHub Secrets** (encrypted, never visible).
> **Do not** upload a filled-in `profile.json` or your resume file to this repo.

## STEP 1: Gmail App Password
1. Open **https://myaccount.google.com/security** → turn **2-Step Verification ON**.
2. Open **https://myaccount.google.com/apppasswords** → name it `Hourly Job Alert` → **Create**.
3. Copy the 16-letter password (you can reuse the one from your daily repo).

## STEP 2: Prepare your profile text (on your computer, NOT uploaded)
1. Open `profile.json` from the zip in Notepad.
2. Replace every `YOUR ...` value (name, phone, LinkedIn, experience, notice period, CTCs, one-line achievement, current employer under `skip_companies`).
3. Keep the file open; you'll paste its **entire contents** into a secret in Step 5.
4. After that, **don't upload this filled copy** to GitHub. The repo keeps only the blank template.

## STEP 3: Turn your resume into text (for a secret)
GitHub Secrets can only hold text, so the resume is converted to Base64 text:
- **Windows**: open **PowerShell** in the folder with your resume and run:
  ```powershell
  [Convert]::ToBase64String([IO.File]::ReadAllBytes("resume.pdf")) | Set-Clipboard
  ```
- **Mac**: open **Terminal** in that folder and run:
  ```bash
  base64 -i resume.pdf | tr -d '\n' | pbcopy
  ```
The long text is now on your clipboard. You'll paste it in Step 5.
(If your file isn't named `resume.pdf`, change the name in the command, and set `"resume_file"` in your profile to the same name.)

## STEP 4: Create the PUBLIC repo and upload the code
1. **https://github.com** → **+** → **New repository**
2. Name: `sf-job-alert-hourly` → choose **🌐 Public** → **Create repository**.
3. Click **"uploading an existing file"** and drag in everything from the unzipped folder:
   `job_alert.py`, `naukri_source.py`, `other_sources.py`, `requirements.txt`, `README.md`,
   `profile.json` (**the blank template from the zip, not your filled copy**), `seen_jobs.json`, `applied_jobs.json`, `state.json`,
   the `resume` folder (only contains `PUT_RESUME_HERE.txt`), **and the `.github` folder**.
   > The `.github` folder is hidden. **Windows:** Explorer → View → Show → ✅ Hidden items. **Mac:** `Cmd + Shift + .` in Finder.
   > Or create it on GitHub: **Add file → Create new file** → name `.github/workflows/hourly-job-alert.yml` → paste contents → Commit.
4. Click **Commit changes**. Confirm the repo shows `.github/workflows/hourly-job-alert.yml`.

## STEP 5: Add the 5 secrets
Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** (repeat 5 times):

| Name | Value |
|---|---|
| `GMAIL_USER` | `adamjays96@gmail.com` |
| `GMAIL_APP_PASSWORD` | the 16-letter App Password (Step 1) |
| `TO_EMAIL` | `adamjays96@gmail.com` (where alerts go; comma-separate for more) |
| `PROFILE_JSON` | paste the **entire** filled `profile.json` text (Step 2), from `{` to `}` |
| `RESUME_BASE64` | paste the long resume text from your clipboard (Step 3) |

Secrets are encrypted. Nobody (including you) can view them again after saving, only replace them.

## STEP 6: First test (auto-apply still OFF)
1. **Actions** tab → if prompted, **"I understand my workflows, go ahead and enable them"**.
2. **Hourly Salesforce Job Alert** → **Run workflow** → **Run workflow**.
3. After ~5–7 minutes open the run log. You should see each portal's count, e.g.
   ```
   Search window: last 1 hours
   LinkedIn: 40 raw listings
   Naukri: 110 raw listings
   Foundit: 20 raw listings
   Shine: 61 raw listings
   Cutshort: 100 raw listings
   LinkedIn: 12 of 40 posted in the last 1h
   Fresh in window by source: {'Naukri': 6, 'Foundit': 3, 'Shine': 1}
   Kept by source: {'LinkedIn': 2, 'Naukri': 3, 'Foundit': 1}
   6 jobs kept in total
   Alert email sent        (or: No new jobs this hour — no email sent)
   ```
   (Logs are public, so `QUIET_LOGS` hides company and recruiter names; the details are only in your email.)
4. **No email if nothing was posted in the last hour.** To get a test email right away, temporarily set `WINDOW_HOURS: "24"`, `MAX_WINDOW_HOURS: "24"` and `SEND_IF_EMPTY: "true"`, run it, then set them back (`"1"` / `"1.25"` / `"false"`).
5. Check inbox + **Spam** (mark "Not spam" once).

## STEP 7: Recruiter auto-emails (ON by default)
`AUTO_APPLY` is already `"true"`. Whenever a job posted in the last hour contains a recruiter email, the bot emails that recruiter your resume + a cover note written for the job, and you get a **BCC copy**.
- It only sends once the `PROFILE_JSON` (no `YOUR ...` left) and `RESUME_BASE64` secrets are set; otherwise it skips safely.
- Want to check the first one yourself? Set `MAX_AUTO_APPLY_PER_RUN: "1"` for a day, read the BCC copy, then set it back to `"5"`.
- To pause recruiter emails, set `AUTO_APPLY: "false"`.

✅ Done. It now runs **every hour, 24×7, for free**, and emails you only when there are new jobs.

---

## 🌐 Job portals covered
| Portal | Posting time | Notes |
|---|---|---|
| LinkedIn | ~exact ("35 minutes ago") | Easy Apply detected; full description read for recruiter emails |
| Naukri | exact timestamp | Often shows salary. Uses headless Chrome |
| Foundit (ex-Monster) | exact timestamp | Copies of LinkedIn jobs are removed automatically |
| Shine | "x hours ago" | |
| Cutshort | exact timestamp | Almost always shows salary; fewer Salesforce posts |
| Talent.com (aggregator of company career sites and other boards) | "x hours ago" | Picks up jobs from sites we can't read directly |
| TimesJobs | date only | Reported in the **first hour it appears** (the bot remembers what was already listed) |
| Instahyre | date only | Same as TimesJobs; only Pune/Hyderabad jobs |
| ❌ Indeed, Glassdoor, SimplyHired, Jooble, Adzuna, Wellfound, Hirist, Apna | — | Blocked by bot protection or no posting time. For Indeed/Glassdoor, turn on their own email job alerts |

> **First run:** TimesJobs/Instahyre only *remember* the current listings (log: `first run, remembering N current jobs`). New ones are reported from the next hour.

- **Same job on several portals?** It appears **once**, with "also on Naukri / Foundit / …" links underneath the Apply button, and the salary copied from whichever portal shows it.
- Turn a portal off by removing it from `OTHER_SOURCES` in the workflow (`USE_LINKEDIN` / `USE_NAUKRI` for those two).
- If a portal fails or blocks a run, the others still work. The log shows `Fresh in window by source: {...}` and `Kept by source: {...}`.

## ⏱️ Schedule & GitHub free minutes
Default schedule: **every hour, 24×7** (`17 * * * *`), which is free on a **public** repo.
On a private repo switch to `17 3-17 * * *` (8:47 AM to 10:47 PM IST) to stay within the free minutes.
The first run of the morning automatically looks back over the whole night, so no jobs are missed.

| Repo type | Free minutes | What to use |
|---|---|---|
| **Public** (your setup) | Unlimited, ₹0 | 24×7 hourly ✅. Keep resume/profile in **Secrets**, not files (see below) |
| Private | 2,000 min/month | Each run now takes ~5–6 min, so use `17 3-17 * * *` or every 2 hours |

Check usage: GitHub profile picture → **Settings → Billing and plans → Usage**.
If you run low: change the cron to every 2 hours: `cron: "17 3-17/2 * * *"`.

GitHub doesn't run scheduled jobs at the exact minute. A 5–20 minute delay is normal.

---

## ⚙️ Settings (in `.github/workflows/hourly-job-alert.yml`)
| Setting | Default | Meaning |
|---|---|---|
| `cron` | `17 3-17 * * *` | When it runs (UTC). IST = UTC + 5:30 |
| `MIN_EXP` / `MAX_EXP` | 4 / 8 | Experience range to keep |
| `WINDOW_HOURS` | 1 | Only jobs posted within this many hours |
| `MAX_WINDOW_HOURS` | 1.25 | Small stretch if GitHub starts a run late, so no job falls in a gap |
| `SEND_IF_EMPTY` | false | `false` = no email when nothing was posted in the last hour |
| `USE_LINKEDIN` / `USE_NAUKRI` | true | Turn a source on/off |
| `OTHER_SOURCES` | Foundit,Shine,Cutshort,Talent.com,TimesJobs,Instahyre | Extra portals (remove any you don't want) |
| `AUTO_APPLY` | true | Email recruiters your resume |
| `MAX_AUTO_APPLY_PER_RUN` | 5 | Max recruiter emails per hourly run |
| `MAX_AUTO_APPLY_PER_DAY` | 15 | Max recruiter emails per day (all runs combined) |
| `TO_EMAIL` | adamjays96@gmail.com | Where alerts go (comma-separate for more) |

To add cities or roles, edit `LOCATIONS` / `KEYWORDS` in `job_alert.py` and `NAUKRI_CITIES` / `NAUKRI_KEYWORDS` in `naukri_source.py`.

---

## 🛡️ Auto-apply safety rules
- Only jobs that passed all filters (4–8 yrs, real Salesforce dev role, not a staffing agency).
- Only if the post itself asks candidates to send a resume to that email (accommodation/fraud/privacy emails are ignored).
- Never the same job twice, and **never the same recruiter email twice** (even for a different job).
- Skips `skip_companies` (your current employer).
- Only if the job needs one of your `must_have_any_skill`.
- 20-second gap between emails; per-run and per-day caps.
- You get a BCC copy of every application.
- LinkedIn Easy Apply / Naukri Apply are **not** automated. Bots that log into those accounts break their terms and get accounts banned. The email gives you one-click buttons instead.

---

## 🧯 Troubleshooting
| Problem | Fix |
|---|---|
| `Username and Password not accepted` | Wrong App Password or 2-Step Verification off. Redo Step 1 and update the `GMAIL_APP_PASSWORD` secret |
| No workflow in the Actions tab | The `.github/workflows/hourly-job-alert.yml` file is missing or in the wrong folder (Step 4.7) |
| Workflow never runs by itself | Actions tab → check it isn't disabled. GitHub disables schedules after 60 days of no repo activity; click **Enable workflow** |
| One portal shows `0 raw listings` or `failed` | That site changed or blocked the run. The other portals still work; remove it from `OTHER_SOURCES` if it keeps failing |
| `Naukri: access denied` in the log | Naukri blocked GitHub's server that hour. LinkedIn jobs are still sent; it usually works again next run |
| `profile.json still has placeholder values` | Some `YOUR ...` text is left in `profile.json` |
| `No resume found in resume/` | Upload `resume/resume.pdf` (Step 3) |
| Alert email in Spam | Mark as "Not spam" once, or create a Gmail filter: from `adamjays96@gmail.com`, subject contains `Salesforce job`, Never send to Spam |
| Too many emails | Use the 2-hour cron, or raise `MIN_EXP` |
| Want to stop everything | Actions → Hourly Salesforce Job Alert → ⋯ → **Disable workflow** |

## 🧪 Run on your own computer (optional)
```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
python job_alert.py --dry-run        # searches, writes digest.html + jobs.csv, sends nothing
```
