#!/usr/bin/env python3
"""Collects public job listings and writes jobs.json (read by index.html).
Standard library only. Public pages only, no logins, slow request rate, robots.txt respected.
If one source breaks, its previous listings are kept and the others still update."""
import datetime, html, http.cookiejar, json, os, re, time
import urllib.parse, urllib.request, urllib.robotparser
from extract import analyze

OUT = "jobs.json"
UA = "JobFinderPersonal/1.0 (personal job search; public pages only)"
DELAY = 1.5          # seconds between requests
MAX_TEXT = 8000      # characters of description kept per listing (extraction always uses the full text)
VER = 4              # bump when extraction rules change so old listings get re-read
LOCAL = re.compile(r"huntsville|madison|redstone|decatur|athens|harvest|hazel green|new market|owens cross roads|meridianville", re.I)
TODAY = datetime.date.today().isoformat()

# ---- the sources (add a line here to add a company that uses a supported system) ----
SOURCES = [
    ("peopletec-main", "PeopleTec", "icims", dict(host="careers-peopletec.icims.com")),
    ("peopletec-future", "PeopleTec", "icims", dict(host="futurecareers-peopletec.icims.com")),
    ("peopletec-rccto", "PeopleTec", "icims", dict(host="rccto-careers-peopletec.icims.com")),
    ("decibel", "Decibel Research", "applicantpro_api", dict(host="decibelresearch.applicantpro.com", client_id="10639")),
    ("torch", "Torch Technologies", "workday", dict(host="starfish.wd501.myworkdayjobs.com", tenant="starfish", site="Careers")),
    ("usajobs", "USAJOBS", "usajobs", dict()),
    # Northrop is left out on purpose: its robots.txt asks automated tools not to use the data feed.
]

# ---- polite fetching ----
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
_robots = {}

def allowed(url):
    p = urllib.parse.urlsplit(url)
    root = f"{p.scheme}://{p.netloc}"
    if root not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(root + "/robots.txt", headers={"User-Agent": UA})
            rp.parse(opener.open(req, timeout=30).read().decode("utf-8", "ignore").splitlines())
        except Exception:
            rp = None  # no readable robots.txt
        _robots[root] = rp
    rp = _robots[root]
    return rp is None or rp.can_fetch(UA, url)

def fetch(url, body=None, headers=None, robots=True):
    if robots and not allowed(url):
        raise RuntimeError("robots.txt does not allow " + url)
    time.sleep(DELAY)
    hdrs = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"}
    hdrs.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs)
    return opener.open(req, timeout=40).read().decode("utf-8", "ignore")

def fetch_json(url, body=None, **kw):
    return json.loads(fetch(url, body, **kw))

# ---- text helpers ----
def strip_html(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</(p|li|div|h\d|tr)>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*", "\n", s)).strip()

def jobposting(page):
    """Most career pages embed a machine-readable JobPosting block. Returns (title, location, posted, text) or None."""
    for blob in re.findall(r'(?is)<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page):
        try:
            data = json.loads(blob)
        except Exception:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for d in items:
            if isinstance(d, dict) and "JobPosting" in str(d.get("@type")):
                loc = d.get("jobLocation") or {}
                loc = loc[0] if isinstance(loc, list) and loc else loc
                addr = loc.get("address", {}) if isinstance(loc, dict) else {}
                place = ", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion")] if x) if isinstance(addr, dict) else ""
                return (d.get("title", ""), place, (d.get("datePosted") or "")[:10], strip_html(d.get("description", "")))
    return None

def page_fallback(page):
    t = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page) or re.search(r"(?is)<title>(.*?)</title>", page)
    return (strip_html(t.group(1)) if t else "", "", "", strip_html(page))

# ---- collectors: each returns a list of dicts with id, url, title, location, posted, text ----
def get_detail(url):
    page = fetch(url)
    return jobposting(page) or page_fallback(page)

def collect_icims(host, known):
    ids = {}
    for pg in range(40):
        page = fetch(f"https://{host}/jobs/search?ss=1&in_iframe=1&pr={pg}")
        new = [(urllib.parse.urljoin(f"https://{host}/", html.unescape(u)), i)
               for u, i in re.findall(r'href="([^"]*?/jobs/(\d+)/[^"/]*/job[^"]*)"', page) if i not in ids]
        if not new:
            break
        for u, i in new:
            ids[i] = u
    out = []
    for i, u in ids.items():
        if f"icims:{host}:{i}" in known:
            out.append(dict(id=f"icims:{host}:{i}", url=u, reuse=True))
            continue
        title, loc, posted, text = get_detail(u)
        out.append(dict(id=f"icims:{host}:{i}", url=u, title=title, location=loc, posted=posted, text=text))
    return out

def collect_applicantpro(host, known):
    page = fetch(f"https://{host}/jobs/")
    links = sorted(set(re.findall(r'href="((?:https://[^"/]+)?/jobs/\d+-\d+\.html)"', page)))
    out = []
    for l in links:
        u = urllib.parse.urljoin(f"https://{host}/", l)
        jid = f"ap:{host}:{re.search(r'/jobs/(\d+-\d+)', l).group(1)}"
        if jid in known:
            out.append(dict(id=jid, url=u, reuse=True))
            continue
        title, loc, posted, text = get_detail(u)
        out.append(dict(id=jid, url=u, title=title, location=loc, posted=posted, text=text))
    return out

def _find_jobs(node):
    """Finds the first list of job-like records anywhere inside a JSON reply."""
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node) and any(("title" in x or "jobTitle" in x) for x in node):
            return node
        for x in node:
            r = _find_jobs(x)
            if r:
                return r
    elif isinstance(node, dict):
        for v in node.values():
            r = _find_jobs(v)
            if r:
                return r
    return None

def collect_applicantpro_api(host, client_id, known):
    """ApplicantPro pages load their job list from /core/jobs/<id>. UNVERIFIED guess at the reply format,
    so if it cannot be read, the error shows the start of the reply."""
    last, jobs = "", None
    for params in ("%7B%7D", "%7B%22filters%22%3A%7B%7D%7D"):
        raw = fetch(f"https://{host}/core/jobs/{client_id}?getParams={params}")
        last = raw[:300].replace("\n", " ")
        try:
            jobs = _find_jobs(json.loads(raw))
        except Exception:
            jobs = None
        if jobs:
            break
    if not jobs:
        raise RuntimeError("could not read the job list. Reply began: " + last)
    out = []
    for d in jobs:
        title = d.get("title") or d.get("jobTitle") or ""
        jid = str(d.get("id") or d.get("jobId") or d.get("job_id") or title)
        loc = d.get("location") or ", ".join(str(x) for x in (d.get("city"), d.get("state") or d.get("stateCode")) if x)
        u = urllib.parse.urljoin(f"https://{host}/", d.get("jobUrl") or d.get("url") or d.get("link") or "/jobs/")
        key = f"ap:{host}:{jid}"
        if key in known:
            out.append(dict(id=key, url=u, reuse=True))
            continue
        text = strip_html(d.get("description") or d.get("jobDescription") or "")
        posted = str(d.get("datePosted") or d.get("postedDate") or "")[:10]
        if not text and u.rstrip("/") != f"https://{host}/jobs":
            try:
                t2, l2, p2, text = get_detail(u)
                title, loc, posted = title or t2, loc or l2, posted or p2
            except Exception:
                pass
        out.append(dict(id=key, url=u, title=title, location=loc, posted=posted, text=text))
    return out

FEDERAL_KEEP = re.compile(r"army|navy|air force|defense|aeronautics|space|missile|marine", re.I)

def _s(v):
    return "\n".join(str(x) for x in v) if isinstance(v, list) else str(v or "")

def collect_usajobs(known):
    """Official USAJOBS Search API (free key). Keys come from GitHub secrets, never from the code."""
    key, email = os.environ.get("USAJOBS_KEY", ""), os.environ.get("USAJOBS_EMAIL", "")
    if not key or not email:
        raise RuntimeError("the USAJOBS_KEY and USAJOBS_EMAIL secrets are not set")
    headers = {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}
    out, page = [], 1
    while page <= 10:
        q = urllib.parse.urlencode({"LocationName": "Huntsville, Alabama", "Radius": 30, "WhoMayApply": "public",
                                    "ResultsPerPage": 100, "Page": page})
        data = fetch_json("https://data.usajobs.gov/api/search?" + q, headers=headers, robots=False)
        items = data.get("SearchResult", {}).get("SearchResultItems", [])
        for it in items:
            d = it.get("MatchedObjectDescriptor", {})
            det = d.get("UserArea", {}).get("Details", {})
            org = d.get("OrganizationName") or d.get("DepartmentName") or "Federal"
            if not FEDERAL_KEEP.search(org + " " + d.get("DepartmentName", "")):
                continue
            jid, u = f"usajobs:{it.get('MatchedObjectId')}", d.get("PositionURI", "")
            if jid in known:
                out.append(dict(id=jid, url=u, reuse=True))
                continue
            locs = "; ".join(l.get("LocationName", "") for l in d.get("PositionLocation", []) if isinstance(l, dict)) \
                or d.get("PositionLocationDisplay", "")
            clr = _s(det.get("SecurityClearance"))
            parts = [_s(det.get("JobSummary")), "Qualifications: " + _s(d.get("QualificationSummary")),
                     "Education: " + _s(det.get("Education")), "Requirements: " + _s(det.get("Requirements")),
                     _s(det.get("MajorDuties"))]
            if clr and not re.search(r"not required|none|unspecified|n/?a|other", clr, re.I):
                parts.append("Security clearance: " + clr + ".")
            out.append(dict(id=jid, url=u, company=org + " (federal)", title=d.get("PositionTitle", ""), location=locs,
                            posted=str(d.get("PublicationStartDate", ""))[:10], text=strip_html("\n".join(parts))))
        if len(items) < 100:
            break
        page += 1
    return out

def collect_workday(host, tenant, site, known):
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    out, offset = [], 0
    while True:
        data = fetch_json(base + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""})
        posts = data.get("jobPostings", [])
        if not posts:
            break
        for p in posts:
            path = p["externalPath"]
            jid = f"wd:{host}:{path}"
            u = f"https://{host}/{site}{path}"
            if jid in known:
                out.append(dict(id=jid, url=u, reuse=True))
                continue
            info = fetch_json(base + path).get("jobPostingInfo", {})
            out.append(dict(id=jid, url=info.get("externalUrl") or u, title=info.get("title") or p.get("title", ""),
                            location=info.get("location") or p.get("locationsText", ""),
                            posted=(info.get("startDate") or "")[:10], text=strip_html(info.get("jobDescription", ""))))
        offset += 20
        if offset >= data.get("total", 0):
            break
    return out

def collect_eightfold(host, domain, where, known):
    """UNVERIFIED against the live site: the endpoint below is the common Eightfold pattern."""
    out, start = [], 0
    while start < 400:
        q = urllib.parse.urlencode({"domain": domain, "start": start, "num": 10, "location": where, "sort_by": "timestamp"})
        data = fetch_json(f"https://{host}/api/apply/v2/jobs?{q}")
        pos = data.get("positions", [])
        if not pos:
            break
        for p in pos:
            jid = f"ef:{host}:{p['id']}"
            locs = ", ".join(p.get("locations") or [p.get("location", "")])
            u = p.get("canonicalPositionUrl") or f"https://{host}/careers/job/{p['id']}"
            if jid in known:
                out.append(dict(id=jid, url=u, reuse=True))
                continue
            d = fetch_json(f"https://{host}/api/apply/v2/jobs/{p['id']}?domain={domain}")
            posted = datetime.date.fromtimestamp(p["t_create"]).isoformat() if p.get("t_create") else ""
            out.append(dict(id=jid, url=u, title=p.get("name", ""), location=locs, posted=posted,
                            text=strip_html(d.get("job_description", ""))))
        start += 10
        if start >= data.get("count", 0):
            break
    return out

COLLECTORS = {"icims": collect_icims, "applicantpro": collect_applicantpro, "applicantpro_api": collect_applicantpro_api, "usajobs": collect_usajobs,
              "workday": collect_workday, "eightfold": collect_eightfold}

# ---- main ----
def main():
    try:
        prev = {j["id"]: j for j in json.load(open(OUT))}
    except Exception:
        prev = {}
    known = {k: v for k, v in prev.items() if v.get("ver") == VER}
    results, report = [], []
    for label, company, kind, args in SOURCES:
        try:
            raw = COLLECTORS[kind](known=known, **args)
            kept = 0
            for r in raw:
                if r.get("reuse"):
                    old = prev[r["id"]]
                    if not old.get("location") or LOCAL.search(old["location"]):
                        results.append(old); kept += 1
                    continue
                if r.get("location") and not LOCAL.search(r["location"]):
                    continue
                full = r.get("text") or ""
                job = dict(id=r["id"], company=r.get("company") or company, source=label, title=r.get("title", "").strip(),
                           location=r.get("location", ""), url=r["url"], first_seen=TODAY, ver=VER,
                           posted=r.get("posted") or TODAY, text=full[:MAX_TEXT])
                job.update(analyze(job["title"], full))
                results.append(job); kept += 1
            report.append(f"OK      {label}: {len(raw)} found, {kept} in the Huntsville area")
        except Exception as e:
            old = [j for j in prev.values() if j.get("source") == label]
            results.extend(old)
            report.append(f"FAILED  {label}: {type(e).__name__}: {e} (kept {len(old)} earlier listings)")
    seen, unique = set(), []
    for j in results:  # the same job posted on two portals: keep one
        key = (j["company"].lower(), j["title"].lower().strip(), j["location"].lower().strip(), j.get("text", "")[:300])
        if key not in seen:
            seen.add(key)
            unique.append(j)
    if len(unique) < len(results):
        report.append(f"NOTE    removed {len(results) - len(unique)} duplicate listings")
    results = unique
    for j in results:
        j["first_seen"] = prev.get(j["id"], {}).get("first_seen", j.get("first_seen", TODAY))
    json.dump(results, open(OUT, "w"), indent=1)
    print("\n".join(report))
    print(f"Wrote {len(results)} listings to {OUT}")

if __name__ == "__main__":
    main()
