#!/usr/bin/env python3
"""
Daily Salesforce Developer job alert — Pune & Hyderabad.
Searches LinkedIn public job listings (past 24h), reads each job description,
filters by experience / relevance, and emails an HTML digest.

Env vars:
  GMAIL_USER          sender Gmail address
  GMAIL_APP_PASSWORD  16-char Gmail App Password (NOT your normal password)
  TO_EMAIL            recipient (default adamjays96@gmail.com)
  MIN_EXP / MAX_EXP   experience window to keep (default 4 / 8)
Usage:
  python job_alert.py            # search + send email
  python job_alert.py --dry-run  # search + write digest.html, no email
"""
import os, re, sys, json, time, csv, smtplib, datetime as dt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from html import escape
import requests
from bs4 import BeautifulSoup

TO_EMAIL = os.getenv("TO_EMAIL") or os.getenv("GMAIL_USER") or "adamjays96@gmail.com"
QUIET = os.getenv("QUIET_LOGS", "false").lower() == "true"
MIN_EXP = int(os.getenv("MIN_EXP", "4"))
MAX_EXP = int(os.getenv("MAX_EXP", "8"))
WINDOW_HOURS = float(os.getenv("WINDOW_HOURS", "1"))       # look-back window; seen_jobs.json prevents repeats
SEND_IF_EMPTY = os.getenv("SEND_IF_EMPTY", "false").lower() == "true"
SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_jobs.json")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
MAX_WINDOW_HOURS = float(os.getenv("MAX_WINDOW_HOURS", "1.25"))


def compute_window():
    """Look back to the last successful run (+30 min overlap), at least WINDOW_HOURS, at most MAX_WINDOW_HOURS.
    So the first run of the morning also catches jobs posted overnight."""
    try:
        last = json.load(open(STATE_FILE)).get("last_run", 0)
    except Exception:
        last = 0
    if not last:
        return WINDOW_HOURS
    since = (time.time() - last) / 3600 + 0.05
    return round(min(MAX_WINDOW_HOURS, max(WINDOW_HOURS, since)), 2)


def mark_run_ok():
    json.dump({"last_run": time.time(), "last_run_ist": dt.datetime.now().strftime("%Y-%m-%d %H:%M")},
              open(STATE_FILE, "w"))

LOCATIONS = {"Pune": "Pune, Maharashtra, India", "Hyderabad": "Hyderabad, Telangana, India"}
KEYWORDS = ["Salesforce Developer", "Senior Salesforce Developer", "Apex Developer",
            "LWC Developer", "Salesforce Technical Lead", "SFDC Developer",
            "Salesforce Consultant", "Salesforce CPQ Developer", "Salesforce MuleSoft"]

# title must match one of these ...
TITLE_OK = re.compile(r"salesforce|sfdc|apex|lwc|lightning|cpq|mulesoft|agentforce|vlocity|omnistudio|force\.com", re.I)
# ... and not these
TITLE_BAD = re.compile(r"architect|admin|administrator|business analyst|\bBA\b|sales (executive|manager|officer)|"
                       r"account (executive|manager)|marketing cloud|tester|\bQA\b|payroll|accountant|recruit|"
                       r"intern|fresher|director|oracle apex|\bSAP\b|oracle cpq|dynamics|servicenow|zoho|veeva", re.I)
# description must look like a Salesforce dev job
DESC_OK = re.compile(r"\bapex\b|\blwc\b|lightning web component|salesforce", re.I)
# staffing-agency / spam signals
AGENCY = re.compile(r"consultan(cy|ts)\b|staffing|recruit|hiring solutions|placement|manpower|talent|peoplefy|fittment|job ?fit|headhunt|executive search|\bsearch\b|career|jobs\b|hr solutions|"
                    r"\bHR\b|codersbrain|fusion plus|people staffing", re.I)

SKILLS = ["Apex", "LWC", "Aura", "Visualforce", "SOQL", "Flows", "REST", "SOAP", "MuleSoft", "Sales Cloud",
          "Service Cloud", "Experience Cloud", "CPQ", "Revenue Cloud", "Field Service", "Agentforce", "Data Cloud",
          "OmniStudio", "Vlocity", "Health Cloud", "Financial Services Cloud", "Copado", "Gearset", "SFDX",
          "CI/CD", "Git", "JavaScript", "Triggers", "Batch Apex", "Integration"]
SKILL_RX = {s: re.compile(r"\b" + re.escape(s).replace("Flows", "Flows?").replace("Integration", "Integrations?") + r"\b", re.I)
            for s in SKILLS}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
S = requests.Session(); S.headers.update(UA)


def get(url, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, timeout=25)
            if r.status_code == 200 and len(r.text) > 1500:
                return r.text
            if r.status_code == 200:  # empty page = no more results
                return r.text
        except requests.RequestException:
            pass
        time.sleep(3 * (i + 1))
    return ""


_AGO_RX = re.compile(r"(\d+|an?|one)\s*(second|sec|minute|min|hour|hr|day|week|month)s?\s*ago", re.I)


def ago_hours(label):
    """'35 minutes ago' -> 0.58 ; '2 hours ago' -> 2 ; unknown -> None"""
    m = _AGO_RX.search(label or "")
    if not m:
        return 0.0 if re.search(r"just now|moments? ago", label or "", re.I) else None
    n = 1 if m.group(1).lower() in ("a", "an", "one") else int(m.group(1))
    return n * {"second": 1/3600, "sec": 1/3600, "minute": 1/60, "min": 1/60, "hour": 1, "hr": 1,
                "day": 24, "week": 168, "month": 720}[m.group(2).lower()]


def search(city, loc):
    jobs = {}
    for kw in KEYWORDS:
        for start in (0, 25):
            url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                   f"?keywords={requests.utils.quote(kw)}&location={requests.utils.quote(loc)}"
                   f"&f_TPR=r{int(WINDOW_HOURS * 3600)}&start={start}")
            html = get(url)
            cards = BeautifulSoup(html, "html.parser").select("div.base-card")
            for c in cards:
                jid = c.get("data-entity-urn", "").split(":")[-1]
                t = c.select_one(".base-search-card__title")
                co = c.select_one(".base-search-card__subtitle")
                lo = c.select_one(".job-search-card__location")
                tm = c.select_one("time")
                if not jid or not t:
                    continue
                jobs[jid] = dict(id=jid, city=city, title=t.get_text(strip=True),
                                 company=co.get_text(strip=True) if co else "",
                                 location=lo.get_text(strip=True) if lo else city,
                                 date=tm.get("datetime", "") if tm else "",
                                 ago=tm.get_text(strip=True) if tm else "")
            time.sleep(1.2)
            if len(cards) < 25:
                break
    return jobs


def parse_exp(text):
    """Return (min_years, label) from description, or (None, '')."""
    pats = [r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years|yrs|year)",
            r"(\d{1,2})\s*(?:\+|plus)\s*(?:years|yrs|year)",
            r"(?:minimum|min\.?|at least)\s*(?:of\s*)?(\d{1,2}(?:\.\d)?)\s*(?:years|yrs|year)",
            r"(\d{1,2})\s*(?:years|yrs|year)s?[’']?\s*(?:of\s*)?(?:hands-on\s*|relevant\s*|total\s*)?(?:experience|exp)"]
    for p in pats:
        for m in re.finditer(p, text, re.I):
            nums = [float(g) for g in m.groups() if g]
            if not nums or nums[0] > 20:
                continue  # skip "22 years of company history", "15 years education"
            ctx = text[max(0, m.start() - 12): m.end() + 25].lower()
            if "education" in ctx or "founded" in ctx or "company" in ctx:
                continue
            lo = nums[0]
            label = f"{int(lo)}–{int(nums[1])} yrs" if len(nums) > 1 else f"{lo:g}+ yrs"
            return lo, label
    return None, ""


def work_mode(text):
    t = text.lower()
    if "remote" in t and "hybrid" not in t:
        return "Remote"
    if "hybrid" in t and "hybrid cloud" not in t:
        return "Hybrid"
    if re.search(r"work from office|\bwfo\b|on-?site|5 days", t):
        return "Onsite"
    return ""


def enrich(job):
    html = get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job['id']}")
    s = BeautifulSoup(html, "html.parser")
    d = s.select_one(".show-more-less-html__markup")
    text = d.get_text(" ", strip=True) if d else ""
    job["closed"] = bool(re.search(r"no longer accepting applications", html, re.I))
    job["desc_ok"] = bool(DESC_OK.search(text)) if text else True
    job["exp_min"], job["exp"] = parse_exp(text)
    job["skills"] = [k for k, rx in SKILL_RX.items() if rx.search(text)]
    sal = re.search(r"(?:₹|\bINR\b|\bRs\.?)\s?\d[\d,.]*\s*(?:L|LPA|lakhs?|lacs?|K)?\b(?:\s*(?:-|–|to)\s*(?:₹|INR|Rs\.?)?\s?\d[\d,.]*\s*(?:L|LPA|lakhs?|lacs?|K)?\b)?"
                    r"|\b\d{1,2}(?:\.\d)?\s*(?:-|–|to)\s*\d{1,2}(?:\.\d)?\s*(?:LPA|lakhs?|lacs?)\b", text, re.I)
    job["salary"] = sal.group(0) if sal else "Not disclosed"
    mode = work_mode(text)
    job["mode"] = f"{job['city']} – {mode}" if mode else job["location"].split(",")[0]
    ap = s.select_one(".num-applicants__caption, .num-applicants__figure")
    job["applicants"] = ap.get_text(strip=True) if ap else ""
    job["url"] = f"https://www.linkedin.com/jobs/view/{job['id']}"
    job["emails"] = extract_emails(text)
    job["easy_apply"] = ("apply-button--default" in html) and ("offsite-apply" not in html)
    job["apply_type"] = "Email" if job["emails"] else ("Easy Apply" if job["easy_apply"] else "Company site")
    time.sleep(1.5)
    return job


EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_BAD_CTX = re.compile(r"accommodat|disabilit|privacy|fraud|scam|grievance|ethics|complain|data protection|"
                           r"unsubscribe|noreply|no-reply|legal|compliance|whistle", re.I)
EMAIL_GOOD_CTX = re.compile(r"resume|\bcv\b|profile|share|send|apply|mail|contact|reach|interested", re.I)


def extract_emails(text):
    """Recruiter/HR emails where the post asks candidates to send a resume."""
    out = []
    for m in EMAIL_RX.finditer(text):
        e = m.group(0).rstrip(".").lower()
        ctx = text[max(0, m.start() - 160): m.end() + 40]
        if EMAIL_BAD_CTX.search(ctx) or EMAIL_BAD_CTX.search(e):
            continue
        if not EMAIL_GOOD_CTX.search(ctx):
            continue
        if e not in out:
            out.append(e)
    return out


def keep(job):
    if not TITLE_OK.search(job["title"]) or TITLE_BAD.search(job["title"]):
        return False
    if AGENCY.search(job["company"]):
        return False
    return True


def norm_company(c):
    c = c.lower()
    c = re.sub(r"\b(private|pvt|ltd|limited|inc|llc|india|technologies|technology|solutions|services|group|corp|"
               r"corporation|in india|north america and apac|global|software|systems|consulting)\b", " ", c)
    return re.sub(r"[^a-z0-9]+", "", c)


def norm_title(t):
    t = t.lower().replace("sfdc", "salesforce").replace("sr.", "senior").replace("sr ", "senior ")
    return re.sub(r"[^a-z]+", "", t)


def enrich_naukri(j):
    text = j.pop("text", "")
    j["skills"] = [k for k, rx in SKILL_RX.items() if rx.search(text)]
    j["emails"] = extract_emails(text)
    j["easy_apply"] = j.get("source") == "Naukri" and not j.get("company_site_apply")
    j["apply_type"] = "Email" if j["emails"] else (f"{j.get('source')} Apply" if j["easy_apply"] else "Portal / company site")
    j["closed"] = False
    j["desc_ok"] = bool(DESC_OK.search(text + " " + j["title"]))
    return j


def main():
    global WINDOW_HOURS
    dry = "--dry-run" in sys.argv
    WINDOW_HOURS = compute_window()
    print(f"Search window: last {WINDOW_HOURS:g} hours")
    seen = json.load(open(SEEN_FILE)) if os.path.exists(SEEN_FILE) else {}

    # ---------- LinkedIn ----------
    raw = {}
    if os.getenv("USE_LINKEDIN", "true").lower() == "true":
        for city, loc in LOCATIONS.items():
            raw.update(search(city, loc))
    print(f"LinkedIn: {len(raw)} raw listings")
    for j in raw.values():
        j["source"] = "LinkedIn"
    before = len(raw)
    raw = {k: j for k, j in raw.items() if (ago_hours(j.get("ago")) is None or ago_hours(j.get("ago")) <= WINDOW_HOURS)}
    print(f"LinkedIn: {len(raw)} of {before} posted in the last {WINDOW_HOURS:g}h")

    cand, keyset = [], set()
    for j in raw.values():
        k = (j["title"].lower(), j["company"].lower(), j["city"])
        if k in keyset or not keep(j) or j["id"] in seen:
            continue
        keyset.add(k); cand.append(j)
    print(f"LinkedIn: {len(cand)} candidates after title/agency/seen filter")

    results = []
    for j in cand:
        enrich(j)
        if j["closed"] or not j["desc_ok"]:
            continue
        if j["exp_min"] is not None and not (MIN_EXP - 1 <= j["exp_min"] <= MAX_EXP):
            continue
        results.append(j)

    # ---------- Naukri + other portals ----------
    cutoff_ts = (time.time() - WINDOW_HOURS * 3600) * 1000
    # date-only portals (TimesJobs, Instahyre) can't be filtered by hour: accept today/yesterday,
    # seen_jobs.json guarantees each job is emailed only once.
    date_cutoff = (dt.datetime.now() - dt.timedelta(hours=max(WINDOW_HOURS, 24))).strftime("%Y-%m-%d")

    extra = []
    if os.getenv("USE_NAUKRI", "true").lower() == "true":
        try:
            from naukri_source import fetch_naukri
            extra += fetch_naukri(job_age_days=1, pages=1)
        except Exception as e:
            print(f"Naukri skipped: {e}")
    enabled = [x.strip() for x in os.getenv("OTHER_SOURCES", "Foundit,Shine,Cutshort,Talent.com,TimesJobs,Instahyre").split(",") if x.strip()]
    if enabled:
        try:
            from other_sources import fetch_all
            extra += fetch_all(enabled)
        except Exception as e:
            print(f"Other portals skipped: {e}")

    # Portals that publish only a date (TimesJobs, Instahyre): a job counts as "posted in the last hour"
    # when it was NOT on the portal at the previous hourly check and is dated today.
    FIRST_SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "first_seen.json")
    try:
        first_seen = json.load(open(FIRST_SEEN_FILE))
    except Exception:
        first_seen = {}
    today = dt.date.today().isoformat()
    yday = (dt.date.today() - dt.timedelta(days=1)).isoformat()   # portals date in UTC / publish late
    fresh, seed = [], {}
    for j in extra:
        if j.get("date_only"):
            src = j["source"]
            known = first_seen.get(src)
            seed.setdefault(src, {})[j["id"]] = (known or {}).get(j["id"], today)
            if known is not None and j["id"] not in known and (j.get("date") or "")[:10] >= yday:
                j["created_ts"] = int(time.time() * 1000)
                j["ago"] = "new this hour"
                j["date"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
                fresh.append(j)
        elif j.get("created_ts", 0) >= cutoff_ts:
            fresh.append(j)
    for src, ids in seed.items():
        if src not in first_seen:
            print(f"{src}: first run, remembering {len(ids)} current jobs (new ones will be reported from the next hour)")
        # keep ids for 3 days so a job that briefly drops out isn't reported again
        old = {k: v for k, v in first_seen.get(src, {}).items() if v >= (dt.date.today() - dt.timedelta(days=3)).isoformat()}
        old.update(ids)
        first_seen[src] = old
    if not dry:
        json.dump(first_seen, open(FIRST_SEEN_FILE, "w"))
    from collections import Counter as _C
    print("Fresh in window by source:", dict(_C(j["source"] for j in fresh)))

    linkedin_ids = {r["id"] for r in results}
    keyset = set()
    for j in fresh:
        if j["id"] in seen or not keep(j):
            continue
        if j.get("linkedin_id") and (j["linkedin_id"] in linkedin_ids or j["linkedin_id"] in seen):
            continue                                   # Foundit copy of a LinkedIn job
        k = (norm_title(j["title"]), norm_company(j["company"]), j["city"])
        if k in keyset:
            continue
        keyset.add(k)
        enrich_naukri(j)
        if not j["desc_ok"]:
            continue
        lo, hi = j.get("exp_min"), j.get("exp_max")
        if lo == 0 and hi == 0:
            lo = hi = None; j["exp"] = ""
        # keep if the posted range overlaps MIN_EXP..MAX_EXP
        if lo is not None and hi is not None and (hi < MIN_EXP + 1 or lo > MAX_EXP):
            continue
        if lo is not None and hi is None and lo > MAX_EXP:
            continue
        # cross-portal dedupe: same company + similar title + city already in the list
        dup = next((r for r in results if r["city"] == j["city"]
                    and norm_company(r["company"]) == norm_company(j["company"])
                    and (norm_title(r["title"]) in norm_title(j["title"]) or norm_title(j["title"]) in norm_title(r["title"]))), None)
        if dup:
            dup.setdefault("also", []).append((j["source"], j["url"]))
            if dup.get("salary", "Not disclosed") == "Not disclosed" and j["salary"] != "Not disclosed":
                dup["salary"] = j["salary"]
            for e in j.get("emails", []):
                if e not in dup.setdefault("emails", []):
                    dup["emails"].append(e)
            seen[j["id"]] = dt.date.today().isoformat() if not dry else seen.get(j["id"])
            continue
        results.append(j)
    print("Kept by source:", dict(_C(r.get("source", "LinkedIn") for r in results)))

    # newest first inside each city
    def _k(x):
        return x.get("created_ts") or int(dt.datetime.fromisoformat(x["date"][:10]).timestamp() * 1000) if x.get("date") else 0
    results = sorted([r for r in results if r["city"] == "Pune"], key=_k, reverse=True) + \
              sorted([r for r in results if r["city"] == "Hyderabad"], key=_k, reverse=True)
    print(f"{len(results)} jobs kept in total")
    if not results and not SEND_IF_EMPTY:
        print("No new jobs this hour — no email sent (SEND_IF_EMPTY=false).")
        if not dry:
            mark_run_ok()
        return

    try:
        applied_today = auto_apply(results, dry)
    except Exception as e:
        print(f"Auto-apply skipped because of an error: {e.__class__.__name__}: {e}")
        applied_today = []
    html = build_html(results, applied_today)
    csv_path = write_csv(results)
    open(os.path.join(os.path.dirname(SEEN_FILE), "digest.html"), "w", encoding="utf-8").write(html)

    if dry:
        print("Dry run — wrote digest.html and jobs.csv, no email sent.")
        return
    send_email(html, csv_path, len(results))
    today = dt.date.today().isoformat()
    for r in results:
        seen[r["id"]] = today
    cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    json.dump(seen, open(SEEN_FILE, "w"), indent=0)
    mark_run_ok()


def posted_label(r):
    if r.get("source", "LinkedIn") == "LinkedIn":
        return r.get("ago") or r.get("date", "")
    d = r.get("date", "")
    if r.get("date_only") or len(d) <= 10:
        return ("today" if d[:10] == dt.date.today().isoformat() else d[5:10]) + " (date only)"
    return d[11:16] + (" today" if d[:10] == dt.date.today().isoformat() else " " + d[5:10])


SOURCE_COLORS = {"LinkedIn": "#0a66c2", "Naukri": "#275df5", "Foundit": "#6e00be", "TimesJobs": "#d62b2b",
                 "Shine": "#f5a623", "Instahyre": "#11a37f", "Cutshort": "#222222"}


def source_badge(r):
    src = r.get("source", "LinkedIn")
    return (f"<span style='background:{SOURCE_COLORS.get(src, '#555')};color:#fff;padding:2px 6px;"
            f"border-radius:3px;font-size:11px;white-space:nowrap'>{src}</span>")


BTN = ("display:inline-block;background:{bg};color:#ffffff;padding:7px 12px;border-radius:5px;"
       "text-decoration:none;font-weight:600;font-size:12px;white-space:nowrap;margin:2px 0")
LINK = "font-size:11px;color:#0176d3;white-space:nowrap"


def _profile_raw():
    if os.getenv("PROFILE_JSON", "").strip():
        try:
            return json.loads(os.environ["PROFILE_JSON"])
        except Exception:
            return {}
    try:
        return json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json"), encoding="utf-8"))
    except Exception:
        return {}


def manual_email_links(r):
    """mailto: + Gmail-compose links with a ready-written application for this job."""
    if not r.get("emails"):
        return ""
    p = _profile_raw()
    filled = p and "YOUR" not in json.dumps(p)
    to = r["emails"][0]
    if filled:
        subj, body = cover_email(r, p)
    else:
        subj = f"Application: {r['title']} – [Your Name]"
        body = (f"Dear Hiring Team,\n\nI would like to apply for the {r['title']} role at {r['company']} ({r['city']}).\n"
                f"I am a Salesforce Developer with [X] years of experience in "
                f"{', '.join(r['skills'][:6]) or 'Apex, LWC, SOQL, integrations'}.\n\n"
                f"Notice period: [ ]\nCurrent CTC: [ ] | Expected CTC: [ ]\n\n"
                f"Please find my resume attached.\n\nJob link: {r['url']}\n\nRegards,\n[Your Name]\n[Phone]")
    body += "\n\n(Remember to attach your resume before sending.)"
    q = requests.utils.quote
    mailto = f"mailto:{to}?subject={q(subj)}&body={q(body)}"
    gmail = f"https://mail.google.com/mail/?view=cm&fs=1&to={q(to)}&su={q(subj)}&body={q(body)}"
    return (f"<a href='{escape(mailto)}' style='{BTN.format(bg='#dd7a01')}'>✉️ Email HR</a><br>"
            f"<a href='{escape(gmail)}' style='{LINK}'>open in Gmail</a>")


def apply_cell(r):
    """Manual Apply button (always) + extra quick actions."""
    src = r.get("source", "LinkedIn")
    if src == "Naukri":
        label, bg = ("Apply on Naukri", "#275df5") if r.get("easy_apply") else ("Apply on company site", "#0176d3")
    elif src == "LinkedIn":
        label, bg = ("⚡ Easy Apply", "#2e844a") if r.get("easy_apply") else ("Apply Now", "#0176d3")
    else:
        label, bg = f"Apply on {src}", SOURCE_COLORS.get(src, "#0176d3")
    parts = []
    if r.get("auto_applied"):
        parts.append("<div style='color:#2e844a;font-weight:bold;font-size:12px'>✅ Auto-applied by email</div>")
    parts.append(f"<a href='{escape(r['url'])}' style='{BTN.format(bg=bg)}'>👉 {label}</a>")
    if r.get("emails") and not r.get("auto_applied"):
        parts.append(manual_email_links(r))
    for src2, url2 in r.get("also", []):
        parts.append(f"<a href='{escape(url2)}' style='{LINK}'>also on {escape(src2)}</a>")
    return "<br>".join(parts)


def build_html(rows, applied_today=None):
    today = dt.datetime.now().strftime("%d %b %Y, %I:%M %p IST")
    from collections import Counter
    sk = Counter(s for r in rows for s in r["skills"]).most_common(10)
    co = Counter(r["company"] for r in rows).most_common(8)

    def table(city):
        rs = [r for r in rows if r["city"] == city]
        if not rs:
            return f"<h2 style='color:#0176d3'>📍 {city} (0)</h2><p>No new matching jobs posted in the last hour.</p>"
        h = [f"<h2 style='color:#0176d3;margin-top:28px'>📍 {city} ({len(rs)})</h2>",
             "<table style='border-collapse:collapse;width:100%;font-size:13px'>",
             "<tr style='background:#0176d3;color:#fff'>" + "".join(
                 f"<th style='padding:8px;text-align:left'>{c}</th>" for c in
                 ["#", "Source", "Posted", "Title", "Company", "Location / Mode", "Exp", "Key skills", "Salary", "Applicants", "HR email", "Apply (click)"]) + "</tr>"]
        for i, r in enumerate(rs, 1):
            bg = "#f4f8fc" if i % 2 else "#ffffff"
            hot = " 🔥" if re.search(r"first 25|^\s*([0-9]|1[0-9]|2[0-4])\s", r["applicants"] or "") else ""
            h.append(f"<tr style='background:{bg}'>" + "".join(
                f"<td style='padding:7px;border-bottom:1px solid #e3e8ee;vertical-align:top'>{v}</td>" for v in [
                    i, source_badge(r), escape(posted_label(r)), f"<b>{escape(r['title'])}</b>",
                    escape(r["company"]), escape(r["mode"]), escape(r["exp"] or "Not listed"),
                    escape(", ".join(r["skills"][:8]) or "—"), escape(r["salary"]),
                    escape((r["applicants"] or "").replace("Be among the first 25 applicants", "<25")) + hot,
                    "<br>".join(f"<a href='mailto:{e}'>{escape(e)}</a>" for e in r.get("emails", [])) or "—",
                    apply_cell(r)
                ]) + "</tr>")
        h.append("</table>")
        return "".join(h)

    applied_today = applied_today or []
    ea = [r for r in rows if r.get("easy_apply") and not r.get("auto_applied")]
    auto = ("<h2 style='color:#2e844a;margin-top:28px'>✅ Auto-applied today by email (" + str(len(applied_today)) + ")</h2>" +
            ("<ul>" + "".join(f"<li><b>{escape(a['title'])}</b> — {escape(a['company'])} → {escape(a['to'])}</li>" for a in applied_today) + "</ul>"
             if applied_today else "<p>None today (no jobs with a recruiter email, or auto-apply is off).</p>") +
            f"<p>⚡ <b>{len(ea)} quick-apply jobs</b> (LinkedIn Easy Apply / Naukri Apply) are marked below. Each takes about 1 minute.</p>")
    src = Counter(r.get("source", "LinkedIn") for r in rows)
    summ = ("<h2 style='color:#0176d3;margin-top:28px'>📊 Summary</h2>"
            f"<p><b>By source:</b> {' · '.join(f'{k} {v}' for k, v in src.most_common()) or '—'}</p>"
            f"<p><b>Top skills:</b> {', '.join(f'{k} ({v})' for k, v in sk) or '—'}</p>"
            f"<p><b>Most active companies:</b> {', '.join(f'{k} ({v})' for k, v in co) or '—'}</p>")
    return f"""<html><body style="font-family:Segoe UI,Arial,sans-serif;color:#1b1b1b;max-width:1100px">
<h1 style="margin-bottom:4px">⏰ New Salesforce Developer Jobs — {today}</h1>
<p style="color:#555;margin-top:0">LinkedIn · Naukri · Foundit · Shine · Cutshort · Talent.com · TimesJobs · Instahyre — Pune &amp; Hyderabad · posted in the last hour ({(dt.datetime.now() - dt.timedelta(hours=WINDOW_HOURS)):%I:%M %p} to {dt.datetime.now():%I:%M %p} IST) · {MIN_EXP}–{MAX_EXP} yrs experience ·
<b>{len(rows)} new jobs</b> (already-sent jobs are skipped)</p>
<p style="font-size:12px;color:#444;background:#f3f3f3;padding:8px 10px;border-radius:6px">
<b>How to apply:</b> 👉 <b>Apply Now</b> / <b>Apply on company site</b> opens the job page ·
⚡ <b>Easy Apply</b> is LinkedIn one-click apply · <b>Apply on Naukri</b> uses your Naukri profile ·
✉️ <b>Email HR</b> opens a ready-written application email to the recruiter (attach your resume, then Send).</p>
{auto}{table('Pune')}{table('Hyderabad')}{summ}
<p style="color:#888;font-size:12px;margin-top:24px">Sources: LinkedIn, Naukri, Foundit, TimesJobs, Shine, Instahyre, Cutshort public listings. Only jobs with a verifiable posting time within the last hour are included (TimesJobs &amp; Instahyre publish only a date, so their jobs are included the first hour they appear). Indeed &amp; Glassdoor block automated access; use their own alerts. Staffing agencies, architect/admin roles and duplicates filtered out.
Also check Naukri with: ("Salesforce Developer" OR "Apex Developer" OR "LWC Developer" OR "Salesforce Technical Lead") AND (Pune OR Hyderabad)</p>
</body></html>"""


def write_csv(rows):
    p = os.path.join(os.path.dirname(SEEN_FILE), "jobs.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Source", "City", "Posted", "Title", "Company", "Location/Mode", "Experience", "Skills", "Salary", "Applicants", "HR email", "Apply type", "Auto-applied", "Link"])
        for r in rows:
            w.writerow([r.get("source", "LinkedIn"), r["city"], r["date"], r["title"], r["company"], r["mode"], r["exp"],
                        ", ".join(r["skills"]), r["salary"], r["applicants"], "; ".join(r.get("emails", [])),
                        r.get("apply_type", ""), "Yes" if r.get("auto_applied") else "", r["url"]])
    return p


def send_email(html, csv_path, n):
    user, pw = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    msg = MIMEMultipart()
    msg["Subject"] = (f"⏰ {n} new Salesforce job{'s' if n != 1 else ''} in the last hour — Pune & Hyderabad · {dt.datetime.now():%d %b %I:%M %p}"
                      if n else f"⏰ No new Salesforce jobs in the last hour · {dt.datetime.now():%d %b %I:%M %p}")
    msg["From"], msg["To"] = user, TO_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))
    with open(csv_path, "rb") as f:
        a = MIMEApplication(f.read(), Name="salesforce_jobs.csv")
    a["Content-Disposition"] = 'attachment; filename="salesforce_jobs.csv"'
    msg.attach(a)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [e.strip() for e in TO_EMAIL.split(",")], msg.as_string())
    print("Alert email sent" if QUIET else f"Email sent to {TO_EMAIL}")


# ─────────────────────────── AUTO-APPLY (email) ───────────────────────────
AUTO_APPLY = os.getenv("AUTO_APPLY", "false").lower() == "true"
MAX_AUTO_APPLY = int(os.getenv("MAX_AUTO_APPLY_PER_DAY", "15"))
MAX_AUTO_APPLY_PER_RUN = int(os.getenv("MAX_AUTO_APPLY_PER_RUN", "5"))
BASE = os.path.dirname(os.path.abspath(__file__))
APPLIED_FILE = os.path.join(BASE, "applied_jobs.json")
PROFILE_FILE = os.path.join(BASE, "profile.json")
RESUME_DIR = os.path.join(BASE, "resume")


def load_profile():
    if os.getenv("PROFILE_JSON", "").strip():
        p = json.loads(os.environ["PROFILE_JSON"])
    elif os.path.exists(PROFILE_FILE):
        p = json.load(open(PROFILE_FILE, encoding="utf-8"))
    else:
        return None
    if "YOUR" in json.dumps(p):
        print("profile.json still has placeholder values — auto-apply skipped.")
        return None
    return p


def find_resume(profile):
    """1) a resume file uploaded in the repo's resume/ folder, 2) the RESUME_BASE64 secret."""
    path = _find_resume_file(profile)
    if path:
        print(f"Resume: using {os.path.basename(path)} from the resume/ folder")
        return path
    b64 = "".join(os.getenv("RESUME_BASE64", "").split())       # tolerate spaces / line breaks
    if b64:
        import base64, tempfile
        name = os.path.basename((profile.get("resume_file") or "").replace("\\", "/")) or "resume.pdf"
        if not name.lower().endswith((".pdf", ".docx")):
            name = "resume.pdf"
        try:
            data = base64.b64decode(b64 + "=" * (-len(b64) % 4))
        except Exception as e:
            print(f"RESUME_BASE64 secret is not valid Base64 ({e.__class__.__name__}) — auto-apply skipped.")
            return None
        if len(data) < 1000:
            print("RESUME_BASE64 secret looks too small to be a resume — auto-apply skipped.")
            return None
        folder = os.path.join(tempfile.gettempdir(), "resume_secret")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(data)
        print("Resume: using the RESUME_BASE64 secret")
        return path
    return None


def _find_resume_file(profile):
    f = os.path.basename((profile.get("resume_file") or "").replace("\\", "/"))
    path = os.path.join(RESUME_DIR, f) if f else ""
    if path and os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    if os.path.isdir(RESUME_DIR):
        for n in sorted(os.listdir(RESUME_DIR)):
            full = os.path.join(RESUME_DIR, n)
            if n.lower().endswith((".pdf", ".docx")) and os.path.getsize(full) > 1000:
                return full
    return None


def cover_email(job, p):
    matched = [s for s in job["skills"] if s.lower() in {x.lower() for x in p.get("skills", [])}]
    skills = ", ".join((matched or p.get("skills", []))[:6])
    subject = f"Application: {job['title']} – {p['name']} ({p['total_experience']} yrs, {p.get('current_location','')})"
    body = f"""Dear Hiring Team,

I came across the {job['title']} opening at {job['company']} ({job['city']}) on {job.get('source', 'LinkedIn')} and would like to apply.

I am a Salesforce Developer with {p['total_experience']} years of experience, currently {p.get('current_role','')}. My hands-on skills closely match this role: {skills}.
{p.get('highlight','')}

Quick details:
• Total experience: {p['total_experience']} years
• Current location: {p.get('current_location','')} | Preferred: {job['city']}
• Notice period: {p.get('notice_period','')}
• Current CTC: {p.get('current_ctc','')} | Expected CTC: {p.get('expected_ctc','')}
• Certifications: {p.get('certifications','')}

Please find my resume attached. I would welcome the opportunity to discuss how I can contribute to your team.

Job link: {job['url']}

Best regards,
{p['name']}
{p.get('phone','')}
{p.get('email','')}
{p.get('linkedin','')}
"""
    return subject, body


def auto_apply(results, dry=False):
    """Email resume to recruiter addresses found in job posts. Returns list of applications made."""
    for r in results:
        r["auto_applied"] = False
    if not AUTO_APPLY:
        return []
    profile = load_profile()
    if not profile:
        return []
    resume = find_resume(profile)
    if not resume:
        print("No resume found in resume/ — auto-apply skipped.")
        return []
    applied = json.load(open(APPLIED_FILE)) if os.path.exists(APPLIED_FILE) else {}
    applied_emails = {v.get("to") for v in applied.values()}
    skip_cos = [c.lower() for c in profile.get("skip_companies", [])]
    must = [k.lower() for k in profile.get("must_have_any_skill", [])]
    done = []
    today = dt.date.today().isoformat()
    already_today = sum(1 for v in applied.values() if v.get("date") == today)
    budget = max(0, min(MAX_AUTO_APPLY_PER_RUN, MAX_AUTO_APPLY - already_today))
    print(f"Auto-apply: {already_today} sent today, budget this run = {budget}")
    for r in results:
        if len(done) >= budget:
            break
        if not r.get("emails") or r["id"] in applied:
            continue
        if any(c in r["company"].lower() for c in skip_cos):
            continue
        if must and not any(s.lower() in must for s in r["skills"]):
            continue
        to = r["emails"][0]
        if to in applied_emails:        # never spam same recruiter twice
            continue
        subj, body = cover_email(r, profile)
        if dry:
            print(f"[DRY] would email {'<recruiter>' if QUIET else to}: {'<job>' if QUIET else subj}")
            r["auto_applied"] = True
            done.append(dict(title=r["title"], company=r["company"], to=to + " (dry run)"))
            continue
        try:
            send_application(to, subj, body, resume, profile)
            r["auto_applied"] = True
            applied[r["id"]] = dict(to=to, title=r["title"], company=r["company"], date=dt.date.today().isoformat())
            applied_emails.add(to)
            done.append(dict(title=r["title"], company=r["company"], to=to))
            print("Applied to 1 job (details in your email)" if QUIET else f"Applied: {r['title']} @ {r['company']} → {to}")
            time.sleep(20)
        except Exception as e:
            print(f"Failed to apply: {e.__class__.__name__}" if QUIET else f"Failed to apply to {to}: {e}")
    if not dry:
        json.dump(applied, open(APPLIED_FILE, "w"), indent=1)
    return done


def send_application(to, subject, body, resume_path, profile):
    user, pw = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    msg = MIMEMultipart()
    msg["Subject"], msg["From"], msg["To"] = subject, f"{profile['name']} <{user}>", to
    msg["Reply-To"] = profile.get("email", user)
    msg["Bcc"] = user                     # copy in your own inbox / Sent
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with open(resume_path, "rb") as f:
        a = MIMEApplication(f.read(), Name=os.path.basename(resume_path))
    a["Content-Disposition"] = f'attachment; filename="{os.path.basename(resume_path)}"'
    msg.attach(a)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [to, user], msg.as_string())


if __name__ == "__main__":
    main()
