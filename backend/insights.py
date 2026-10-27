"""Turns raw headlines into short 'key findings' cards (a few bullets plus source links).
Rule-based, so it can miss nuance or mis-sort a headline: the source links are there for the detail."""
import re
from collections import Counter
from difflib import SequenceMatcher

THEMES = [
    ("policy", r"policy rate|interest rate|key rate|monetary policy|\bSBP\b|State Bank"),
    ("market", r"\bPSX\b|KSE|bourse|closing bell|stocks? (close|end|settle)"),
    ("energy", r"\boil\b|petrol|diesel|\bgas\b|LNG|refiner|energy|crude|Brent|power tariff|electricity"),
    ("economy", r"\bIMF\b|budget|inflation|rupee|exports?|remittance|economy|FPCCI|tax|GDP|trade deficit"),
    ("world", r"Iran|India|Afghan|Taliban|Middle East|\bUS\b|China|war|sanction"),
]
TITLES = {"policy": "State Bank and interest rates", "market": "Stock market", "energy": "Oil, gas and power",
          "economy": "Economy and business", "world": "Regional and world news"}
REASONS = [(r"inflation", "inflation risks"), (r"oil|energy|crude|Brent", "higher oil and energy prices"),
           (r"Iran|Middle East|geopolit|tension", "Middle East and Iran-US tensions"), (r"\bIMF\b", "IMF programme"),
           (r"rupee|exchange rate|currency", "rupee pressure"), (r"global pressure", "global pressures")]


def outlet(t):
    m = re.search(r"\s[-|]\s([^-|]{2,40})$", t)
    return m.group(1).strip() if m else ""


def clean(t):
    return re.sub(r"\s[-|]\s[^-|]{2,40}$", "", t).strip()


def _dedupe(items, thr=0.62):
    out = []
    for n in items:
        c = clean(n["title"]).lower()
        if not any(SequenceMatcher(None, c, clean(o["title"]).lower()).ratio() > thr for o in out):
            out.append(n)
    return out


def _sources(items, k=4):
    seen, out = set(), []
    for n in items:
        o = outlet(n["title"]) or "Source"
        if o not in seen:
            seen.add(o)
            out.append({"name": o, "url": n["url"]})
        if len(out) == k:
            break
    return out


def key_points(news, index=None):
    groups = {k: [] for k, _ in THEMES}
    for n in news:
        for k, pat in THEMES:
            if re.search(pat, n["title"], re.I):
                groups[k].append(n)
                break
    cards = []
    pol = groups["policy"]
    if pol:
        txt = " ".join(clean(n["title"]) for n in pol)
        act = Counter()
        for n in pol:
            t = n["title"].lower()
            for word, label in (("rais|hike|jack|increas|hiking", "raised"), ("cut|reduc|slash", "cut"), ("retain|keep|unchanged|maintain|status quo", "kept")):
                if re.search(word, t):
                    act[label] += 1
        rates = Counter(re.findall(r"(\d{1,2}(?:\.\d+)?)\s*(?:%|pc|percent)", txt))
        bps = Counter(re.findall(r"(\d{2,3})\s*(?:bps|basis points)", txt, re.I))
        bullets = []
        if act:
            a = act.most_common(1)[0][0]
            line = f"The State Bank {a} its policy rate"
            if bps and a != "kept":
                line += f" by {bps.most_common(1)[0][0]} basis points"
            if rates:
                line += f" to {rates.most_common(1)[0][0]}%"
            bullets.append(line + f" ({len(pol)} headlines agree).")
            reasons = [lab for pat, lab in REASONS if re.search(pat, txt, re.I)]
            if reasons:
                bullets.append("Reasons given: " + ", ".join(reasons[:4]) + ".")
            react = [n for n in pol if re.search(r"FPCCI|business|industry|denounce|critici[sz]|slam", n["title"], re.I)]
            if react:
                bullets.append("Business groups reacted: " + clean(react[0]["title"]) + ".")
            bullets.append("What it can mean for you: banks like MEBL often benefit; debt-heavy companies and rate-sensitive stocks can come under pressure; bond and money-market funds may offer higher yields.")
        else:
            bullets = [clean(n["title"]) for n in _dedupe(pol)[:3]]
        cards.append({"title": TITLES["policy"], "bullets": bullets, "sources": _sources(pol)})
    mk = groups["market"]
    if mk or index:
        bullets = []
        if index and index.get("change_pct") is not None:
            bullets.append(f"KSE-100: {index['level']:,.2f} ({index['change_pct']:+.2f}% on the day), from the PSX data portal.")
        for n in _dedupe(mk)[:3]:
            bullets.append(clean(n["title"]) + ".")
        if bullets:
            cards.append({"title": TITLES["market"], "bullets": bullets, "sources": _sources(mk)})
    for k in ("energy", "economy", "world"):
        g = _dedupe(groups[k])
        if g:
            cards.append({"title": TITLES[k], "bullets": [clean(n["title"]) + "." for n in g[:2]], "sources": _sources(g, 3)})
    return cards[:5]
