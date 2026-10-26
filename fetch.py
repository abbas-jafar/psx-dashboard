"""Data fetchers. Endpoints are the public PSX data-portal pages and were NOT verified from the
build environment (it could not reach PSX). Run `python src/main.py --selftest` to see which work."""
import datetime as dt, re, xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

BASE = "https://dps.psx.com.pk"
HDR = {"User-Agent": "Mozilla/5.0 (personal PSX dashboard)", "Accept": "*/*"}
PKT = dt.timezone(dt.timedelta(hours=5))


def _get(url, **kw):
    r = requests.get(url, headers=HDR, timeout=25, **kw)
    r.raise_for_status()
    return r


def _num(s):
    if s is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(s).replace(",", ""))
    try:
        return float(s)
    except ValueError:
        return None


def market_watch():
    """One page with every listed stock. Returns {symbol: {price, change_pct, ldcp, high, low, volume}}."""
    soup = BeautifulSoup(_get(BASE + "/market-watch").text, "html.parser")
    out = {}
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
        if "SYMBOL" not in heads or "CURRENT" not in heads:
            continue
        idx = {h: i for i, h in enumerate(heads)}
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < len(heads):
                continue
            sym = tds[idx["SYMBOL"]].split()[0].upper()
            chg_key = next((h for h in heads if h.startswith("CHANGE") and "%" in h), None)
            out[sym] = {
                "price": _num(tds[idx["CURRENT"]]),
                "change_pct": _num(tds[idx[chg_key]]) if chg_key else None,
                "ldcp": _num(tds[idx["LDCP"]]) if "LDCP" in idx else None,
                "high": _num(tds[idx["HIGH"]]) if "HIGH" in idx else None,
                "low": _num(tds[idx["LOW"]]) if "LOW" in idx else None,
                "volume": _num(tds[idx["VOLUME"]]) if "VOLUME" in idx else None,
            }
    if not out:
        raise RuntimeError("market-watch table not found (page layout changed or blocked)")
    return out


def range_52w(sym):
    """52-week low/high. Tries the company page, then falls back to a year of daily closes."""
    try:
        txt = BeautifulSoup(_get(f"{BASE}/company/{sym}").text, "html.parser").get_text(" ", strip=True)
        m = re.search(r"52[\s-]*WEEK\s*RANGE\D{0,20}([\d,]+\.?\d*)\s*[—–\-]+\s*([\d,]+\.?\d*)", txt, re.I)
        if m:
            return _num(m.group(1)), _num(m.group(2)), "company page"
    except Exception:
        pass
    rows = _get(f"{BASE}/timeseries/eod/{sym}").json().get("data", [])
    cutoff = dt.datetime.now(PKT).timestamp() - 365 * 86400
    closes = [r[1] for r in rows if r and r[0] >= cutoff and r[1]]
    if not closes:
        raise RuntimeError("no eod data")
    return min(closes), max(closes), "daily closes (approx.)"


def kse100():
    rows = _get(f"{BASE}/timeseries/int/KSE100").json().get("data", [])
    rows = sorted(rows, key=lambda r: r[0])
    last = rows[-1][1]
    eod = sorted(_get(f"{BASE}/timeseries/eod/KSE100").json().get("data", []), key=lambda r: r[0])
    today = dt.datetime.now(PKT).date()
    prev = next((r[1] for r in reversed(eod) if dt.datetime.fromtimestamp(r[0], PKT).date() < today), None)
    return {"level": last, "prev_close": prev,
            "change_pct": (last - prev) / prev * 100 if prev else None}


CATS = [
    ("Risk notice", r"suspen|delist|risk warning|default|violation|show cause|penalt|deficit list|non[- ]compliance"),
    ("Dividend / book closure", r"dividend|book closure|bonus|right shares|entitlement"),
    ("Results", r"financial results|quarter(ly)? (result|account)|half year|annual (result|account)|profit|earnings"),
    ("Board meeting", r"board of directors|board meeting|meeting of the board"),
    ("Material information", r"material information|acquisition|merger|agreement|credit rating|expansion|capacity"),
]


def classify(text):
    for name, pat in CATS:
        if re.search(pat, text, re.I):
            return name
    return "Other"


def company_announcements(days=3):
    """Company (type C) and PSX (type P) notices, via the portal's announcements search form."""
    end = dt.datetime.now(PKT).date()
    start = end - dt.timedelta(days=days)
    items = []
    for typ, label in (("C", "Company"), ("P", "PSX notice")):
        r = requests.post(BASE + "/announcements", headers=HDR, timeout=25, data={
            "type": typ, "symbol": "", "query": "", "count": 100, "offset": 0,
            "date_from": start.isoformat(), "date_to": end.isoformat(), "page": "annc"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tr in soup.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < 3:
                continue
            link = tr.find("a", href=True)
            sym = next((t for t in tds if re.fullmatch(r"[A-Z0-9]{2,8}", t)), "")
            title = max(tds, key=len)
            date = tds[0]
            items.append({"source": label, "date": date, "ticker": sym, "title": title,
                          "category": "Risk notice" if typ == "P" and classify(title) == "Other" else classify(title),
                          "url": (BASE + link["href"]) if link and link["href"].startswith("/") else (link["href"] if link else "")})
    if not items:
        raise RuntimeError("no announcement rows parsed")
    return items


def news(queries, days=3):
    """Headlines from Google News RSS (no key needed)."""
    out, seen = [], set()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    for q in queries:
        try:
            xml = _get("https://news.google.com/rss/search", params={"q": q + f" when:{days}d", "hl": "en-PK", "gl": "PK", "ceid": "PK:en"}).text
            for it in ET.fromstring(xml).iter("item"):
                title = (it.findtext("title") or "").strip()
                if title in seen:
                    continue
                seen.add(title)
                pub = it.findtext("pubDate") or ""
                try:
                    when = dt.datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=dt.timezone.utc)
                except ValueError:
                    when = None
                if when and when < cutoff:
                    continue
                out.append({"title": title, "url": it.findtext("link") or "", "date": when.astimezone(PKT).strftime("%d %b %H:%M") if when else "",
                            "topic": q, "_t": when.timestamp() if when else 0})
        except Exception:
            continue
    out.sort(key=lambda x: -x["_t"])
    for o in out:
        o.pop("_t")
    return out[:25]


def quote(sym):
    """Per-stock fallback when the market-watch table is unavailable: intraday series, then daily, then company page."""
    try:
        rows = sorted(_get(f"{BASE}/timeseries/int/{sym}").json().get("data", []), key=lambda r: r[0])
        price = rows[-1][1]
        eod = sorted(_get(f"{BASE}/timeseries/eod/{sym}").json().get("data", []), key=lambda r: r[0])
        today = dt.datetime.now(PKT).date()
        prev = next((r[1] for r in reversed(eod) if dt.datetime.fromtimestamp(r[0], PKT).date() < today), None)
        return {"price": price, "change_pct": (price - prev) / prev * 100 if prev else 0}
    except Exception:
        pass
    txt = BeautifulSoup(_get(f"{BASE}/company/{sym}").text, "html.parser").get_text(" ", strip=True)
    m = re.search(r"Rs\.?\s*([\d,]+\.\d+)", txt)
    c = re.search(r"\(\s*([+\-\u2212]?[\d.]+)\s*%\s*\)", txt)
    if not m:
        raise RuntimeError("price not found on company page")
    return {"price": _num(m.group(1)), "change_pct": _num(c.group(1).replace("\u2212", "-")) if c else 0}
