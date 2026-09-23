"""
Naukri.com source for the daily Salesforce job alert.
Naukri blocks plain HTTP requests (reCAPTCHA), so we open the search pages in a real
Chromium browser (Playwright) and read the JSON the page itself loads.
If Naukri blocks the run, this returns [] and the LinkedIn part still works.
"""
import re, time, datetime as dt
from html import unescape

NAUKRI_KEYWORDS = ["salesforce developer", "senior salesforce developer", "apex developer",
                   "lwc developer", "salesforce technical lead", "sfdc developer",
                   "salesforce cpq developer", "salesforce lightning developer"]
NAUKRI_CITIES = {"Pune": "pune", "Hyderabad": "hyderabad"}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _clean(html):
    t = re.sub(r"<br\s*/?>", " ", html or "", flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()


def _to_job(j, city):
    ph = {p.get("type"): p.get("label", "") for p in j.get("placeholders", [])}
    loc = ph.get("location", city)
    try:
        created = dt.datetime.fromtimestamp(int(j.get("createdDate", 0)) / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        created = ""
    mode = "Hybrid" if "hybrid" in loc.lower() else ("Remote" if "remote" in loc.lower() else "")
    sal = ph.get("salary", "Not disclosed") or "Not disclosed"
    url = j.get("jdURL", "")
    if url.startswith("/"):
        url = "https://www.naukri.com" + url
    return dict(
        id="nk-" + str(j.get("jobId")), source="Naukri", city=city,
        title=j.get("title", ""), company=j.get("companyName", ""),
        location=loc, mode=(f"{city} – {mode}" if mode else loc),
        date=created, created_ts=int(j.get("createdDate", 0) or 0), ago=j.get("footerPlaceholderLabel", ""),
        exp=ph.get("experience", j.get("experienceText", "")),
        exp_min=float(j["minimumExperience"]) if str(j.get("minimumExperience", "")).replace(".", "").isdigit() else None,
        exp_max=float(j["maximumExperience"]) if str(j.get("maximumExperience", "")).replace(".", "").isdigit() else None,
        salary=sal, text=_clean(j.get("jobDescription", "")) + " " + (j.get("tagsAndSkills", "") or "").replace(",", ", "),
        tags=j.get("tagsAndSkills", ""), url=url, applicants="",
        company_site_apply=bool(j.get("companyApplyJob")),
        rating=(j.get("ambitionBoxData") or {}).get("AggregateRating", ""),
    )


def fetch_naukri(job_age_days=1, pages=2, log=print):
    """Return list of job dicts from Naukri for Pune + Hyderabad."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("Naukri: playwright not installed — skipped")
        return []
    jobs = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chromium", headless=True,
                                        args=["--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                locale="en-IN", timezone_id="Asia/Kolkata", viewport={"width": 1366, "height": 900})
            ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page = ctx.new_page()
            captured = []

            def on_resp(r):
                if "jobapi/v3/search" in r.url:
                    try:
                        captured.append(r.json())
                    except Exception:
                        pass
            page.on("response", on_resp)

            blocked = 0
            for city, cslug in NAUKRI_CITIES.items():
                for kw in NAUKRI_KEYWORDS:
                    for pg in range(1, pages + 1):
                        suffix = "" if pg == 1 else f"-{pg}"
                        url = f"https://www.naukri.com/{_slug(kw)}-jobs-in-{cslug}{suffix}?jobAge={job_age_days}"
                        captured.clear()
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=45000)
                            for _ in range(20):          # wait up to ~10s for the search API
                                if captured:
                                    break
                                page.wait_for_timeout(500)
                        except Exception as e:
                            log(f"Naukri: {url} failed ({e.__class__.__name__})")
                            continue
                        if "access denied" in (page.title() or "").lower():
                            blocked += 1
                            log("Naukri: access denied on " + url)
                            if blocked >= 3:
                                raise RuntimeError("Naukri is blocking this IP")
                            continue
                        details = []
                        for c in captured:
                            details += c.get("jobDetails", []) if isinstance(c, dict) else []
                        for j in details:
                            job = _to_job(j, city)
                            jobs[job["id"]] = job
                        time.sleep(1.5)
                        if len(details) < 20:
                            break
            browser.close()
    except Exception as e:
        log(f"Naukri: stopped early — {e}")
    log(f"Naukri: {len(jobs)} raw listings")
    return list(jobs.values())
