"""Reads years of experience, degree, and clearance out of a job listing's text.
Plain pattern matching, no AI. Anything it is unsure about is flagged in "review"."""
import re

SPLIT = re.compile(r"[.;\n\u2022\u00b7]+|\s-\s")
PREF = re.compile(r"\b(prefer|preferred|desired|desirable|a plus|nice to have|bonus|advantage|helpful)\b", re.I)
BOILER = re.compile(r"\b(our company|we have|we are|founded|since \d{4}|for over|for more than)\b|\bhas\s+(?:over|more than|nearly|almost)\s+\d+", re.I)
RANGE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|\u2013|\u2014|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.I)
ANY_YRS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.I)
ENTRY = re.compile(r"entry[- ]level|no experience (?:is )?(?:required|needed)|recent graduate|new grad", re.I)

DEGREES = [  # (name, pattern, case-insensitive?)
    ("phd", r"\b(?:ph\.?d\.?|doctorate|doctoral)\b", True),
    ("master", r"\b(?:master'?s?|M\.S\.|MBA)\b", True),
    ("bachelor", r"\b(?:bachelor'?s?|undergraduate degree|four[- ]year degree)\b", True),
    ("bachelor", r"\b(?:BS|BA|B\.S\.|B\.A\.|BBA)\b", False),
    ("associate", r"\bassociate'?s?\s+(?:degree|of)\b", True),
]
RANK = {"none": 0, "associate": 1, "bachelor": 2, "master": 3, "phd": 4}

CLR_ANY = re.compile(r"\b(clearance|top secret|ts/sci|secret|public trust|polygraph)\b", re.I)
ACTIVE = re.compile(
    r"\b(?:active|current|existing|interim|valid)\s+(?:\w+\s+){0,2}?(?:secret|top secret|ts|clearance|public trust)"
    r"|\bcurrently\s+(?:hold|possess|have)\b|\bmust\s+(?:currently\s+)?(?:have|hold|possess)\s+an?\s+(?:\w+\s+){0,3}?clearance"
    r"|\bclearance\s+(?:is\s+)?required\s+(?:prior|before|at\s+(?:the\s+)?time|to\s+start|upon|for\s+start)"
    r"|\bmust\s+be\s+(?:currently\s+)?cleared\b|\balready\s+(?:hold|have|possess)\b", re.I)
OBTAIN = re.compile(
    r"\b(?:ability|able|eligible|eligibility|willing|willingness|can)\s+(?:to\s+)?(?:\w+\s+){0,3}?(?:obtain|acquire|be\s+granted|qualify)"
    r"|\bobtain(?:ed)?\s+(?:and|or)\s+maintain|\bwill\s+sponsor|\bsponsor(?:ed|ship)?\b|\beligible\s+for\s+(?:a\s+|an\s+)?(?:\w+\s+){0,2}clearance", re.I)


def _sentences(text):
    return [s.strip() for s in SPLIT.split(text) if s.strip()]


NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}
YRS = re.compile(r"(\d{1,2})\s*(?:\+|plus|or more)?\s*(?:(?:-|\u2013|\u2014|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)\b", re.I)


def _normalize_years(t):
    t = re.sub(r"\b(yrs?)\.", r"\1", t, flags=re.I)
    words = "|".join(NUMW)
    t = re.sub(r"\b(%s)\b(?:\s*\(\d+\))?(?=\s*(?:\+|plus|or more)?\s*(?:-|to)?\s*(?:\d{1,2}\s*)?(?:years?|yrs?)\b)" % words,
               lambda m: str(NUMW[m.group(1).lower()]), t, flags=re.I)
    return re.sub(r"\((\d{1,2})\)(?=\s*(?:\+|plus|or more)?\s*(?:years?|yrs?)\b)", r"\1", t)


LADDER = re.compile(r"\b(junior|jr|entry|mid|journeyman|senior|sr|sme|principal|lead)\b[ \t]*[:\-\u2013]?[ \t]*(\d{1,2})[ \t]*(?:-|\u2013|\u2014|to)[ \t]*(\d{1,2})[ \t]*\+?", re.I)
LEVELKEY = {"junior": "junior", "jr": "junior", "entry": "junior", "mid": "mid", "journeyman": "mid",
            "senior": "senior", "sr": "senior", "lead": "senior", "sme": "sme", "principal": "sme"}
NOYRS = re.compile(r"(\d{1,2})\s*(?:-|\u2013|\u2014|to)\s*(\d{1,2})\s*\+?\s+of\s+(?:[\w,-]+\s+){0,3}?experience", re.I)
GENERIC = re.compile(r"(?:years?|yrs?)\s+(?:of\s+)?(?:relevant|related|professional|work|total|overall|progressively)\b|\d\s+of\s+progressively", re.I)


def years(title, text):
    t = _normalize_years(re.sub(r"[ \t\r\f\v]+", " ", text))
    ladder = {}  # listings that give a range for each level: Junior 2-5, Mid 5-8, Senior 8-10
    for m in LADDER.finditer(t):
        ladder.setdefault(LEVELKEY[m.group(1).lower()], (int(m.group(2)), int(m.group(3))))
    if len(ladder) >= 2:
        tl = title.lower()
        for word, key in LEVELKEY.items():
            if key in ladder and re.search(r"\b%s\b" % word, tl):
                return ladder[key][0], ladder[key][1], []
        lo = min(ladder.values())
        return lo[0], lo[1], ["years"]
    cands = [(m, int(m.group(1)), int(m.group(2)) if m.group(2) else None) for m in YRS.finditer(t)]
    cands += [(m, int(m.group(1)), int(m.group(2))) for m in NOYRS.finditer(t)]
    req, pref = [], []
    for m, lo, hi in sorted(cands, key=lambda c: c[0].start()):
        win = t[max(0, m.start() - 90): m.end() + 90]
        if not re.search(r"experience|experienced|\bexp\b", win, re.I):
            continue
        sb = max(t.rfind(c, 0, m.start()) for c in ".;\n\u2022")
        se = [i for i in (t.find(c, m.end()) for c in ".;\n\u2022") if i != -1]
        sent = t[sb + 1: min(se) if se else len(t)]
        label_free = re.sub(r"preferred\s+(?:years\s+of\s+)?experience(?:\s+range)?", " ", sent, flags=re.I)  # a label, not a preference
        if BOILER.search(sent):
            continue
        if PREF.search(label_free):
            if GENERIC.search(sent):  # "10-12 years of relevant experience is desired": general level, keep but flag
                pref.append((lo, hi))
            continue
        req.append((lo, hi))
    if req:
        return req[0][0], req[0][1], (["years"] if len({f[0] for f in req}) > 1 else [])
    if pref:
        return pref[0][0], pref[0][1], ["years"]
    return (0, None, []) if ENTRY.search(title + " " + text) else (None, None, [])


def degree(text):
    names = set()
    for s in _sentences(text):
        if PREF.search(s):
            continue
        for name, pat, ci in DEGREES:
            if re.search(pat, s, re.I if ci else 0):
                names.add(name)
    return min(names, key=RANK.get) if names else "none"


def clearance(text):
    m = re.search(r"CLEARANCE REQUIRED FOR START:\s*(Yes|No)", text, re.I)
    t = re.search(r"CLEARANCE TYPE:\s*([A-Za-z/ ]{2,40})", text, re.I)
    sents = [s for s in _sentences(text) if CLR_ANY.search(s)]
    req = " ".join(s for s in sents if not PREF.search(s))
    level = _level(t.group(1)) if t and _level(t.group(1)) else (_level(req) or _level(text))
    if m:  # some employers state this directly
        if m.group(1).lower() == "yes":
            return "active", level, []
        has_type = bool(t and t.group(1).strip().lower() not in ("none", "n/a"))
        return ("obtain" if has_type else "none"), level, []
    if not CLR_ANY.search(text):
        return "none", "", []
    for s in sents:
        if ACTIVE.search(s) and not OBTAIN.search(s) and not PREF.search(s):
            return "active", _level(s) or level, []
    if OBTAIN.search(text):
        return "obtain", level, []
    return "unclear", level, ["clearance"]


def _level(t):
    if re.search(r"\bsci\b", t, re.I):
        return "TS/SCI"
    if re.search(r"top secret", t, re.I) or re.search(r"\bTS\b", t):
        return "Top Secret"
    if re.search(r"\bsecret\b", t, re.I):
        return "Secret"
    if re.search(r"public trust", t, re.I):
        return "Public Trust"
    return ""


FIELDS = {
    "business": r"business|management|finance|accounting|economics|marketing|logistics|supply chain|operations|administration",
    "engineering": r"engineering|stem",
    "computer": r"computer|information (?:technology|systems)|software|cyber|\bIT\b|stem",
    "math_science": r"mathematics|\bmath\b|physics|chemistry|statistics|\bscience|stem",
    "geospatial": r"geograph|\bGIS\b|geospatial|remote sensing",
}
ANY_FIELD = re.compile(r"any (?:field|discipline|major)|any related|unspecified", re.I)
EQUIV = re.compile(r"or equivalent|equivalent (?:work |professional |relevant |military )?experience|in lieu of|may substitute|can substitute", re.I)
DEG_ANY = re.compile(r"bachelor|master|ph\.?d|doctorate|associate|\bdegree\b|\bB\.?S\.?\b|\bB\.?A\.?\b|\bBBA\b|\bMBA\b", re.I)


def degree_fields(text):
    out = set()
    for m in DEG_ANY.finditer(text):
        seg = re.split(r"[.;\n]", text[m.start(): m.start() + 140])[0]
        if PREF.search(seg):
            continue
        for name, pat in FIELDS.items():
            if re.search(pat, seg, re.I if name != "computer" else 0) or (name == "computer" and re.search(r"computer|information (?:technology|systems)|software|cyber|\bIT\b|STEM", seg, re.I)):
                out.add(name)
        if ANY_FIELD.search(seg):
            out.add("any")
    return sorted(out)


def analyze(title, text):
    ymin, ymax, r1 = years(title, text)
    tag, level, r2 = clearance(text)
    return {"years_min": ymin, "years_max": ymax, "degree": degree(text),
            "degree_fields": degree_fields(text), "degree_equiv": bool(EQUIV.search(text)),
            "clearance_tag": tag, "clearance_level": level, "review": r1 + r2}
