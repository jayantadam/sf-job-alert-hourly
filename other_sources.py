"""
Extra job portals for the hourly Salesforce alert.

Portal       How                          Posting time precision
-----------  ---------------------------  ----------------------------------------
Foundit      JSON API (ex-Monster India)  exact timestamp
TimesJobs    JSON API                     date only (treated as "today")
Shine        HTML search page             "10 hours ago" style label
Instahyre    JSON API + job page          date only (newest IDs first)
Cutshort     page data (__NEXT_DATA__)    exact timestamp

Indeed and Glassdoor are NOT included: both sit behind Cloudflare bot protection that
blocks automated access (even a real headless browser). Use their own job alerts instead.

Every fetcher returns a list of dicts in the same shape as naukri_source.py, so the main
script can filter / dedupe / auto-apply them the same way. Any portal that fails returns [].
"""
import re, json, time, datetime as dt
from html import unescape
import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})

CITIES = ["Pune", "Hyderabad"]
# set by job_alert.py before fetching (to cut traffic):
SINCE_MS = 0      # results older than this (ms) are outside the search window → stop paging
KNOWN = {}        # {"Instahyre": {"in-123", ...}} jobs already seen → don't re-open their pages
KEYWORDS = ["salesforce developer", "salesforce", "apex lwc"]
CITY_RX = {c: re.compile(c if c != "Hyderabad" else r"hyderabad|secunderabad", re.I) for c in CITIES}


def _clean(html):
    t = re.sub(r"<br\s*/?>|</p>|</li>", " ", html or "", flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()


def _cities_in(text):
    return [c for c, rx in CITY_RX.items() if rx.search(text or "")]


def _job(source, jid, city, title, company, location, created_ts, exp_min, exp_max, exp_label,
         salary, text, url, ago="", mode=""):
    created = dt.datetime.fromtimestamp(created_ts / 1000).strftime("%Y-%m-%d %H:%M") if created_ts else ""
    title = re.sub(r"\s+", " ", re.sub(r"^\s*(job\s*)?title\s*:\s*", "", title or "", flags=re.I)).strip()
    return dict(id=f"{source[:2].lower()}-{jid}", source=source, city=city, title=title,
                company=(company or "").strip(), location=location, mode=mode or location,
                date=created, created_ts=int(created_ts or 0), ago=ago,
                exp=exp_label, exp_min=exp_min, exp_max=exp_max,
                salary=salary or "Not disclosed", text=text or "", url=url, applicants="",
                company_site_apply=False)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ───────────────────────────── Foundit ─────────────────────────────
def fetch_foundit(log=print):
    out = {}
    for city in CITIES:
        for kw in ["salesforce"]:                       # broad search covers "salesforce developer" too
            for start in (0, 15, 30):
                url = ("https://www.foundit.in/middleware/jobsearch?sort=1&limit=15"
                       f"&start={start}&query={requests.utils.quote(kw).replace('%20', '%2B')}"
                       f"&locations={city}&jobFreshness=1")
                try:
                    r = S.get(url, timeout=25, headers={"Accept": "application/json",
                                                        "Referer": "https://www.foundit.in/srp/results"})
                    data = r.json().get("jobSearchResponse", {}).get("data", [])
                except Exception as e:
                    log(f"Foundit: {city}/{kw} failed ({e.__class__.__name__})"); data = []
                for j in data:
                    lo = _num((j.get("minimumExperience") or {}).get("years"))
                    hi = _num((j.get("maximumExperience") or {}).get("years"))
                    smin = (j.get("minimumSalary") or {}).get("absoluteValue") or 0
                    smax = (j.get("maximumSalary") or {}).get("absoluteValue") or 0
                    sal = (f"{smin/1e5:.1f}-{smax/1e5:.1f} Lacs PA" if smax and not j.get("hideSalary") else "Not disclosed")
                    apply = j.get("applyUrl") or j.get("redirectUrl") or ""
                    seo = j.get("seoJdUrl") or j.get("jdUrl") or ""
                    page = ("https://www.foundit.in" + seo) if seo.startswith("/") else (seo or apply)
                    jb = _job("Foundit", j.get("jobId"), city, j.get("title", ""), j.get("companyName", ""),
                              j.get("locations", city), j.get("createdAt") or j.get("freshness"),
                              lo, hi, f"{lo:g}-{hi:g} Yrs" if lo is not None and hi is not None else "",
                              sal, (j.get("skills") or "") + " " + _clean(j.get("description", "")), page,
                              ago=j.get("updatedAt", ""))
                    # Foundit re-lists many LinkedIn jobs; remember the original so we can dedupe
                    if "linkedin.com/jobs/view/" in apply:
                        jb["linkedin_id"] = re.search(r"view/(\d+)", apply).group(1)
                    out[jb["id"]] = jb
                time.sleep(1.2)
                oldest = min([j.get("createdAt") or 0 for j in data] or [0])
                if len(data) < 15 or (SINCE_MS and oldest and oldest < SINCE_MS):
                    break                                # newest-first: the rest is older than the window
    log(f"Foundit: {len(out)} raw listings")
    return list(out.values())


# ───────────────────────────── TimesJobs ─────────────────────────────
def fetch_timesjobs(log=print):
    out = {}
    for city in CITIES:
        for kw in ["salesforce developer", "salesforce"]:
            body = {"keyword": kw, "location": city.lower(), "experience": "", "page": "1", "size": "50",
                    "jobFunctions": [], "company": "", "industry": "", "functionAreaId": "", "jobFunction": ""}
            try:
                r = S.post("https://tjapi.timesjobs.com/search/api/v1/search/jobs/list", json=body, timeout=25,
                           headers={"Referer": "https://www.timesjobs.com/", "Accept": "application/json"})
                jobs = r.json().get("jobs", [])
            except Exception as e:
                log(f"TimesJobs: {city}/{kw} failed ({e.__class__.__name__})"); jobs = []
            for j in jobs:
                d = j.get("postDate", "")
                try:  # date only -> treat as noon of that day, the time filter uses the date
                    ts = int(dt.datetime.strptime(d, "%Y-%m-%d").timestamp() * 1000)
                except ValueError:
                    ts = 0
                lo, hi = _num(j.get("experienceFrom")), _num(j.get("experienceTo"))
                ls, hs = j.get("lowSalary", -1), j.get("highSalary", -1)
                sal = f"{ls:g}-{hs:g} Lacs PA" if isinstance(ls, (int, float)) and ls > 0 and hs > 0 else "Not disclosed"
                for c in (_cities_in(j.get("location", "")) or [city]):
                    jb = _job("TimesJobs", j.get("jobId"), c, j.get("title", ""), j.get("company") or j.get("hfCompany"),
                              j.get("location", c), ts, lo, hi,
                              f"{lo:g}-{hi:g} Yrs" if lo is not None and hi is not None else "",
                              sal, (j.get("skills") or "") + " " + (j.get("description") or ""),
                              (j.get("jobDetailUrl") or "").replace(" ", "%20"), ago=d,
                              mode=f"{c} – {j.get('jobType')}" if j.get("jobType") else "")
                    jb["date_only"] = True
                    out[jb["id"] + c] = jb
            time.sleep(1.2)
    log(f"TimesJobs: {len(out)} raw listings")
    return list(out.values())


# ───────────────────────────── Shine ─────────────────────────────
_AGO = re.compile(r"(\d+|an?|few)\s*(minute|min|hour|hr|day|week|month)s?\s*ago", re.I)


def _ago_to_ts(label):
    if re.search(r"less than (an?|1) hour", label or "", re.I):
        return int((time.time() - 1800) * 1000)
    m = _AGO.search(label or "")
    if not m:
        return int(time.time() * 1000) if re.search(r"just now|today|few (sec|min)", label or "", re.I) else 0
    n = 1 if m.group(1).lower() in ("a", "an", "few") else int(m.group(1))
    unit = m.group(2).lower()
    secs = {"minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800, "month": 2592000}[unit]
    return int((time.time() - n * secs) * 1000)


def fetch_shine(log=print):
    out = {}
    for city in CITIES:
        for kw in ["salesforce-developer", "salesforce"]:
            url = f"https://www.shine.com/job-search/{kw}-jobs-in-{city.lower()}?sort=1"
            try:
                html = S.get(url, timeout=25).text
            except Exception as e:
                log(f"Shine: {url} failed ({e.__class__.__name__})"); continue
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.select("article[class*=result-card_card]"):
                t = a.select_one("[class*=result-card_role]")
                link = a.find("a", href=True)
                if not t or not link:
                    continue
                href = link["href"].split("?")[0]
                jid = re.search(r"/(\d+)/?$", href)
                ago = (a.select_one("[class*=result-card_posted]") or {}).get_text(strip=True) if a.select_one("[class*=result-card_posted]") else ""
                meta = [x.get_text(strip=True) for x in a.select("[class*=result-card_meta-text]")]
                exp = next((m for m in meta if "Yr" in m), "")
                em = re.findall(r"\d+", exp)
                sal = next((m for m in meta if "Lac" in m or "₹" in m), "Not disclosed")
                loc = meta[-1] if meta else city
                skills = " ".join(x.get_text(" ", strip=True) for x in a.select("[class*=result-card_skills-item]"))
                co = a.select_one("[class*=result-card_company]")
                jb = _job("Shine", jid.group(1) if jid else href, city, t.get_text(" ", strip=True),
                          co.get_text(strip=True) if co else "", loc, _ago_to_ts(ago),
                          _num(em[0]) if em else None, _num(em[1]) if len(em) > 1 else None,
                          exp.replace(" to ", "-"), sal, skills + " " + t.get_text(" ", strip=True),
                          "https://www.shine.com" + href if href.startswith("/") else href, ago=ago)
                out[jb["id"]] = jb
            time.sleep(1.2)
    log(f"Shine: {len(out)} raw listings")
    return list(out.values())


# ───────────────────────────── Instahyre ─────────────────────────────
def fetch_instahyre(log=print, max_detail=10):
    """Instahyre's search API has no dates, so we open each Pune/Hyderabad job page
    (newest IDs first) and read datePosted from its JSON-LD."""
    cands = {}
    for skill in ["salesforce", "apex", "lightning web components"]:
        try:
            r = S.get("https://www.instahyre.com/api/v1/job_search", timeout=25, params=dict(
                company_size=0, job_type=0, limit=60, offset=0, skills=skill))
            objs = r.json().get("objects", [])
        except Exception as e:
            log(f"Instahyre: {skill} failed ({e.__class__.__name__})"); objs = []
        for o in objs:
            cs = _cities_in(o.get("locations", ""))
            if cs:
                cands[o["id"]] = (o, cs)
        time.sleep(1)
    out = []
    known = KNOWN.get("Instahyre")
    opened = 0
    for jid in sorted(cands, reverse=True):     # newest first
        o, cs = cands[jid]
        url = o.get("public_url") or f"https://www.instahyre.com/job-{jid}/"
        posted, text = "", " ".join(o.get("keywords") or [])
        if known is not None and f"in-{jid}" in known:
            # already seen on an earlier run: no need to open its page again
            for c in cs:
                jb = _job("Instahyre", jid, c, o.get("title", ""), (o.get("employer") or {}).get("company_name", ""),
                          o.get("locations", c), 0, None, None, "", "Not disclosed", text, url)
                jb["date_only"] = True
                out.append(jb)
            continue
        if opened >= max_detail:
            continue
        opened += 1
        try:
            html = S.get(url, timeout=25).text
            for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
                try:
                    d = json.loads(m.group(1))
                except Exception:
                    continue
                if isinstance(d, dict) and d.get("@type") == "JobPosting":
                    posted = d.get("datePosted", "")
                    text += " " + _clean(d.get("description", ""))
                    exp = d.get("experienceRequirements") or {}
            time.sleep(1)
        except Exception:
            pass
        try:
            ts = int(dt.datetime.strptime(posted[:10], "%Y-%m-%d").timestamp() * 1000)
        except ValueError:
            ts = 0
        em = re.search(r"(\d+)\s*(?:-|to|–)\s*(\d+)\s*(?:years|yrs)", text, re.I)
        for c in cs:
            jb = _job("Instahyre", jid, c, o.get("title", ""), (o.get("employer") or {}).get("company_name", ""),
                      o.get("locations", c), ts, _num(em.group(1)) if em else None,
                      _num(em.group(2)) if em else None, f"{em.group(1)}-{em.group(2)} Yrs" if em else "",
                      "Not disclosed", text, url, ago=posted)
            jb["date_only"] = True
            out.append(jb)
    log(f"Instahyre: {len(out)} raw listings (Pune/Hyderabad)")
    return out


# ───────────────────────────── Cutshort ─────────────────────────────
def fetch_cutshort(log=print):
    out = {}
    for city in CITIES:
        url = f"https://cutshort.io/jobs/salesforce-jobs-in-{city.lower()}"
        try:
            html = S.get(url, timeout=25).text
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            data = json.loads(m.group(1)) if m else {}
        except Exception as e:
            log(f"Cutshort: {city} failed ({e.__class__.__name__})"); continue
        found = []

        def walk(o):
            if isinstance(o, dict):
                if "jobFactSummary" in o:
                    found.append(o)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(data)
        for j in found:
            f = j["jobFactSummary"]
            try:
                ts = int(dt.datetime.fromisoformat(f["postedDate"].replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                ts = 0
            er = j.get("expRange") or {}
            skills = " ".join(s.get("name", "") if isinstance(s, dict) else str(s) for s in (j.get("allSkills") or []))
            co = (j.get("companyId") or {}).get("name") or f.get("companyName", "")
            jb = _job("Cutshort", j.get("_id"), city, f.get("roleTitle") or j.get("headline", ""), co,
                      f.get("locations", city), ts, _num(er.get("min")), _num(er.get("max")),
                      f.get("experience", ""), f.get("salary") or j.get("salaryRangeText") or "Not disclosed",
                      skills + " " + _clean(j.get("sanitizedComment", "")), j.get("publicUrl", ""),
                      ago=f.get("postedDateLabel", ""))
            out[jb["id"] + city] = jb
        time.sleep(1.2)
    log(f"Cutshort: {len(out)} raw listings")
    return list(out.values())

# ───────────────────────────── Talent.com (aggregator) ─────────────────────────────
def fetch_talent(log=print):
    out = {}
    for city in CITIES:
        for kw in ["salesforce developer", "salesforce"]:
            url = f"https://in.talent.com/jobs?k={kw.replace(' ', '+')}&l={city}&date=1&sort=date"
            try:
                html = S.get(url, timeout=25).text
            except Exception as e:
                log(f"Talent.com: {city} failed ({e.__class__.__name__})"); continue
            soup = BeautifulSoup(html, "html.parser")
            for c in soup.select("[data-testid^=jobcard-container]"):
                parts = [t.strip() for t in c.stripped_strings if t.strip() and t.strip() != "•"]
                if len(parts) < 3:
                    continue
                ago_txt = next((x for x in parts if "ago" in x.lower()), "")
                ago = ago_txt.replace("Last updated:", "").strip()
                if "+" in ago:                     # "30+ days ago"
                    continue
                jid = c.get("data-new-id") or c.get("data-job-id")
                a = c.find("a", href=True)
                href = a["href"] if a else f"/view?id={jid}"
                title, company, loc = parts[0], parts[1], parts[2]
                desc = " ".join(x for x in parts[3:] if x not in (ago_txt, "Show more"))
                em = re.findall(r"(\d+)\s*(?:\+|-|to)?\s*(\d+)?\s*(?:years|yrs)", desc, re.I)
                emin = _num(em[0][0]) if em else None
                emax = _num(em[0][1]) if em and em[0][1] else None
                jb = _job("Talent.com", jid, city, title, company, loc, _ago_to_ts(ago), emin, emax,
                          (f"{em[0][0]}-{em[0][1]} yrs" if em and em[0][1] else f"{em[0][0]}+ yrs") if em else "",
                          "Not disclosed", title + " " + desc,
                          "https://in.talent.com" + href if href.startswith("/") else href, ago=ago)
                if _cities_in(loc) or city.lower() in loc.lower():
                    out[jb["id"]] = jb
            time.sleep(1.2)
    log(f"Talent.com: {len(out)} raw listings")
    return list(out.values())


FETCHERS = {
    "Foundit": fetch_foundit,
    "TimesJobs": fetch_timesjobs,
    "Shine": fetch_shine,
    "Instahyre": fetch_instahyre,
    "Cutshort": fetch_cutshort,
    "Talent.com": fetch_talent,
}


def fetch_all(enabled=None, log=print):
    jobs = []
    for name, fn in FETCHERS.items():
        if enabled is not None and name not in enabled:
            continue
        try:
            jobs += fn(log=log)
        except Exception as e:
            log(f"{name}: skipped ({e})")
    return jobs
