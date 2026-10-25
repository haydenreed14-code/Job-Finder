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


def years(title, text):
    found = []
    for s in _sentences(text):
        if not re.search(r"experience|experienced", s, re.I) or PREF.search(s) or BOILER.search(s):
            continue
        m = RANGE.search(s)
        if m:
            found.append((int(m.group(1)), int(m.group(2))))
            continue
        m = ANY_YRS.search(s)
        if m:
            found.append((int(m.group(1)), None))
    if not found:
        return (0, None, []) if ENTRY.search(title + " " + text) else (None, None, [])
    review = ["years"] if len({f[0] for f in found}) > 1 else []
    return found[0][0], found[0][1], review


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


def analyze(title, text):
    ymin, ymax, r1 = years(title, text)
    tag, level, r2 = clearance(text)
    return {"years_min": ymin, "years_max": ymax, "degree": degree(text),
            "clearance_tag": tag, "clearance_level": level, "review": r1 + r2}
