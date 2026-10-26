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
    """All listed stocks from the portal's screener table (verified to exist from GitHub's servers).
    Returns {symbol: {sector, price, change_pct, pe_ttm, yield_ttm}}."""
    soup = BeautifulSoup(_get(BASE + "/screener").text, "html.parser")
    out = {}
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
        if "SYMBOL" not in heads or "PRICE" not in heads:
            continue
        idx = {h: i for i, h in enumerate(heads)}
        chg = next((h for h in heads if h.startswith("CHANGE")), None)
        pe = next((h for h in heads if h.startswith("PE RATIO")), None)
        dy = next((h for h in heads if h.startswith("DIVIDEND YIELD")), None)
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < len(heads):
                continue
            sym = tds[idx["SYMBOL"]].split()[0].upper()
            out[sym] = {"sector": tds[idx["SECTOR"]] if "SECTOR" in idx else "", "price": _num(tds[idx["PRICE"]]), "change_pct": _num(tds[idx[chg]]) if chg else None,
                        "pe_ttm": _num(tds[idx[pe]]) if pe else None, "yield_ttm": _num(tds[idx[dy]]) if dy else None}
    if not out:
        raise RuntimeError("screener table not found")
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
    """KSE-100 from the portal's indices table (Index, High, Low, Current, Change, % Change)."""
    soup = BeautifulSoup(_get(BASE + "/indices").text, "html.parser")
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
        if "CURRENT" not in heads or "INDEX" not in heads:
            continue
        ix = {h: i for i, h in enumerate(heads)}
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < len(heads) or tds[ix["INDEX"]].replace(" ", "").upper() != "KSE100":
                continue
            lvl, chg = _num(tds[ix["CURRENT"]]), _num(tds[ix["CHANGE"]])
            pc = next((h for h in heads if "%" in h), None)
            return {"level": lvl, "prev_close": lvl - chg if chg is not None else None,
                    "change_pct": _num(tds[ix[pc]]) if pc else None, "high": _num(tds[ix["HIGH"]]), "low": _num(tds[ix["LOW"]])}
    raise RuntimeError("KSE100 row not found in indices table")


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


def _parse_date(t):
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(t.strip(), fmt).date()
        except ValueError:
            pass
    return None


def company_announcements(symbols, days=14):
    """Announcement tables printed on each company's page (Date / Title / Document)."""
    from concurrent.futures import ThreadPoolExecutor
    cutoff = dt.datetime.now(PKT).date() - dt.timedelta(days=days)

    def one(sym):
        items = []
        try:
            soup = BeautifulSoup(_get(f"{BASE}/company/{sym}").text, "html.parser")
        except Exception:
            return None
        for table in soup.find_all("table"):
            heads = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
            if heads[:3] != ["DATE", "TITLE", "DOCUMENT"]:
                continue
            for tr in table.find_all("tr")[1:12]:
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                date_txt, title = tds[0].get_text(" ", strip=True), tds[1].get_text(" ", strip=True)
                d = _parse_date(date_txt)
                if d and d < cutoff:
                    continue
                link = tr.find("a", href=True)
                href = link["href"] if link else ""
                items.append({"source": "Company", "date": date_txt, "ticker": sym, "title": title, "category": classify(title),
                              "url": (BASE + href) if href.startswith("/") else href})
        return items

    out, ok = [], 0
    with ThreadPoolExecutor(6) as ex:
        for res in ex.map(one, symbols):
            if res is not None:
                ok += 1
                out += res
    if not ok:
        raise RuntimeError("no company page could be read")
    return out


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
