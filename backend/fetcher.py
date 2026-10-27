"""Data fetchers (PSX data portal pages, Google News RSS, optional flows page).
Most endpoints were verified from GitHub's servers with the probe; the ones marked UNVERIFIED are best-effort and are
reported honestly by the dashboard's status lights. Run `python backend/main.py --selftest` to see which work."""
import datetime as dt, re, xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

BASE = "https://dps.psx.com.pk"
HDR = {"User-Agent": "Mozilla/5.0 (personal PSX dashboard)", "Accept": "*/*"}
PKT = dt.timezone(dt.timedelta(hours=5))
DEFAULT_FLOWS_URLS = ["https://www.nccpl.com.pk/market-information/fipi-lipi"]   # UNVERIFIED candidate; override with "flows_urls" in settings.json


def _get(url, **kw):
    r = requests.get(url, headers=HDR, timeout=25, **kw)
    r.raise_for_status()
    return r


_PAGES = {}


def company_soup(sym):
    """Company page, fetched once per run and shared by the range, announcement and fundamentals parsers."""
    if sym not in _PAGES:
        _PAGES[sym] = BeautifulSoup(_get(f"{BASE}/company/{sym}").text, "html.parser")
    return _PAGES[sym]


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
        txt = company_soup(sym).get_text(" ", strip=True)
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
            soup = company_soup(sym)
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



# ---------------------------------------------------------------- indices, constituents, fundamentals, flows
def _norm_index(name):
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def indices_all():
    """Every row of the portal's indices table -> {KSE100: {level, change, change_pct, high, low}, KMI30: ..., KSE30: ...}."""
    soup = BeautifulSoup(_get(BASE + "/indices").text, "html.parser")
    out = {}
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
        if "CURRENT" not in heads or "INDEX" not in heads:
            continue
        ix = {h: i for i, h in enumerate(heads)}
        pc = next((h for h in heads if "%" in h), None)
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < len(heads):
                continue
            lvl = _num(tds[ix["CURRENT"]])
            if lvl is None:
                continue
            out[_norm_index(tds[ix["INDEX"]])] = {"level": lvl, "change": _num(tds[ix["CHANGE"]]) if "CHANGE" in ix else None,
                                                  "change_pct": _num(tds[ix[pc]]) if pc else None,
                                                  "high": _num(tds[ix["HIGH"]]) if "HIGH" in ix else None, "low": _num(tds[ix["LOW"]]) if "LOW" in ix else None}
    if not out:
        raise RuntimeError("indices table not found")
    return out


def index_members(code):
    """Constituent symbols of an index page such as /indices/KMI30 (page style verified for KSE100)."""
    soup = BeautifulSoup(_get(f"{BASE}/indices/{code}").text, "html.parser")
    syms = set()
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
        if "SYMBOL" not in heads:
            continue
        i = heads.index("SYMBOL")
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) > i and tds[i]:
                syms.add(tds[i].split()[0].upper())
    if not syms:
        raise RuntimeError(f"no constituents found for {code}")
    return syms


_DIV = re.compile(r"(\d+(?:\.\d+)?)\s*%[^()]*(?:\([^)]*\)\s*)*\(\s*D\s*\)", re.I)


def fundamentals(sym, par_value=10.0):
    """UNVERIFIED parser for the company page's Financials / Ratios / Payouts tables.
    Returns whatever it can find: latest EPS figures, and cash-dividend history (PSX prints a payout as '% of face value', e.g. '150% (D)')."""
    soup = company_soup(sym)
    out = {"eps": [], "payouts": []}
    today = dt.datetime.now(PKT).date()
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            label = cells[0].upper()
            if label.startswith("EPS") or label == "EARNINGS PER SHARE":
                vals = [_num(c) for c in cells[1:]]
                vals = [v for v in vals if v is not None]
                if vals:
                    out["eps"].append({"label": cells[0], "period": heads[1] if len(heads) > 1 else "", "values": vals[:6]})
            line = " ".join(cells)
            m = _DIV.search(line)
            if m:
                d = next((_parse_date(c) for c in cells if _parse_date(c)), None)
                pct = float(m.group(1))
                out["payouts"].append({"date": d.isoformat() if d else "", "pct": pct, "dps_est": round(pct / 100 * par_value, 2)})
    seen, uniq = set(), []
    for p in out["payouts"]:
        k = (p["date"], p["pct"])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    out["payouts"] = uniq
    def within(days):
        return [p for p in uniq if p["date"] and (today - dt.date.fromisoformat(p["date"])).days <= days]
    out["n_12m"], out["n_36m"] = len(within(365)), len(within(1095))
    out["dps_12m_est"] = round(sum(p["dps_est"] for p in within(365)), 2) if within(365) else None
    if not out["eps"] and not out["payouts"]:
        raise RuntimeError("no financial tables found on company page")
    return out


def flows(urls):
    """UNVERIFIED, optional. Foreign (FIPI) and local (LIPI) investor net flows from an official page such as NCCPL's.
    Tries each URL in settings.json -> flows_urls and reads rows whose label mentions foreign / local investors."""
    last = "no flows URL configured"
    for url in urls or []:
        try:
            soup = BeautifulSoup(_get(url).text, "html.parser")
            res = {"fipi_net": None, "lipi_net": None, "source": url, "rows": []}
            for tr in soup.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                lab, nums = cells[0].upper(), [_num(c) for c in cells[1:]]
                nums = [n for n in nums if n is not None]
                if not nums:
                    continue
                net = nums[-1]
                if "FIPI" in lab or "FOREIGN" in lab and "TOTAL" in lab:
                    res["fipi_net"] = net
                elif "LIPI" in lab or "LOCAL" in lab and "TOTAL" in lab:
                    res["lipi_net"] = net
                elif any(k in lab for k in ("FOREIGN", "INDIVIDUAL", "MUTUAL", "BANK", "INSURANCE", "COMPAN", "BROKER")):
                    res["rows"].append({"label": cells[0], "net": net})
            if res["fipi_net"] is not None or res["lipi_net"] is not None or res["rows"]:
                return res
            last = "page read but no FIPI/LIPI rows found"
        except Exception as e:
            last = repr(e)[:120]
    raise RuntimeError(last)


# ---------------------------------------------------------------- official sources (replaces media headlines)
OFFICIAL_SOURCES = [
    {"id": "psx", "name": "Pakistan Stock Exchange", "home": "https://dps.psx.com.pk/", "domain": "dps.psx.com.pk", "priority": 0, "pages": [],
     "covers": "company announcements, results, dividends, board meetings, risk notices"},
    {"id": "sbp", "name": "State Bank of Pakistan", "home": "https://www.sbp.org.pk/", "domain": "sbp.org.pk", "priority": 1,
     "pages": ["https://www.sbp.org.pk/press/index.htm", "https://www.sbp.org.pk/m_policy/index.asp"], "covers": "policy rate, monetary policy statements, FX and banking"},
    {"id": "secp", "name": "SECP", "home": "https://www.secp.gov.pk/", "domain": "secp.gov.pk", "priority": 2,
     "pages": ["https://www.secp.gov.pk/media-center/press-releases/"], "covers": "capital-market and company regulation"},
    {"id": "mof", "name": "Ministry of Finance", "home": "https://www.finance.gov.pk/", "domain": "finance.gov.pk", "priority": 3,
     "pages": [], "covers": "budget, IMF programme, circular debt, taxes"},
    {"id": "fbr", "name": "FBR", "home": "https://www.fbr.gov.pk/", "domain": "fbr.gov.pk", "priority": 4, "pages": [], "covers": "tax measures"},
    {"id": "pbs", "name": "Pakistan Bureau of Statistics", "home": "https://www.pbs.gov.pk/", "domain": "pbs.gov.pk", "priority": 5, "pages": [], "covers": "inflation (CPI), trade, GDP"},
    {"id": "ogra", "name": "OGRA", "home": "https://www.ogra.org.pk/", "domain": "ogra.org.pk", "priority": 6, "pages": [], "covers": "gas and petroleum prices (SSGC, SNGP, PSO)"},
    {"id": "nepra", "name": "NEPRA", "home": "https://nepra.org.pk/", "domain": "nepra.org.pk", "priority": 7, "pages": [], "covers": "power tariffs (HUBC, KAPCO, K-Electric)"},
]
_DATE_PATS = [r"\b\d{1,2}[\s-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*[\s,-]+\d{4}", r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}",
              r"\b\d{1,2}-\d{1,2}-\d{4}\b", r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{1,2}/\d{1,2}/\d{4}\b"]


def _find_date(text):
    for pat in _DATE_PATS:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        t = re.sub(r"\s+", " ", m.group(0).replace("Sept", "Sep")).strip()
        for cand in (t, t.replace(".", ""), re.sub(r"\b([A-Za-z]{3})[a-z]*\b", r"\1", t)):
            d = _parse_date(cand)
            if d:
                return d
        try:
            return dt.datetime.strptime(t, "%d/%m/%Y").date()
        except ValueError:
            pass
    return None


def _scrape_dated_links(url, days, get=None):
    """Heuristic: links with a real sentence as text and a recent date in the same row/paragraph. UNVERIFIED per site."""
    from urllib.parse import urljoin
    soup = BeautifulSoup((get or _get)(url).text, "html.parser")
    cutoff = dt.datetime.now(PKT).date() - dt.timedelta(days=days)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if len(text) < 28 or text in seen or a["href"].startswith(("#", "javascript", "mailto")):
            continue
        d = _find_date(text) or _find_date((a.find_parent(["tr", "li", "p", "div"]) or a).get_text(" ", strip=True)[:300])
        if not d or d < cutoff or d > dt.datetime.now(PKT).date() + dt.timedelta(days=1):
            continue
        seen.add(text)
        out.append({"date": d.isoformat(), "title": text[:240], "url": urljoin(url, a["href"])})
    return out


def _google_site(domain, days):
    xml = _get("https://news.google.com/rss/search", params={"q": f"site:{domain} when:{days}d", "hl": "en-PK", "gl": "PK", "ceid": "PK:en"}).text
    out = []
    for it in ET.fromstring(xml).iter("item"):
        title = re.sub(r"\s[-|]\s[^-|]{2,60}$", "", (it.findtext("title") or "").strip())
        try:
            when = dt.datetime.strptime(it.findtext("pubDate") or "", "%a, %d %b %Y %H:%M:%S %Z").date()
        except ValueError:
            when = None
        if title:
            out.append({"date": when.isoformat() if when else "", "title": title[:240], "url": it.findtext("link") or ""})
    return out


def official_news(sources=None, days=14, get=None):
    """Latest releases from official bodies only. Returns (items, status_per_source). Each item: source, source_id, source_url,
    priority, date, title, url, via. Nothing from newspapers or TV channels."""
    items, status = [], []
    for s in sources or OFFICIAL_SOURCES:
        if s["id"] == "psx":
            status.append({"id": "psx", "name": s["name"], "home": s["home"], "covers": s.get("covers", ""), "ok": True, "count": None, "note": "company filings (see PSX Filings)"})
            continue
        got, via, note = [], None, ""
        for url in s.get("pages", []):
            try:
                got += _scrape_dated_links(url, days, get)
                via = "official page" if got else via
            except Exception as e:
                note = repr(e)[:80]
        if not got:
            try:
                got = _google_site(s["domain"], days)
                via = "Google News index of the official site" if got else via
            except Exception as e:
                note = note or repr(e)[:80]
        for g in got:
            items.append({"source": s["name"], "source_id": s["id"], "source_url": s["home"], "priority": s["priority"], "via": via, **g})
        status.append({"id": s["id"], "name": s["name"], "home": s["home"], "covers": s.get("covers", ""), "ok": bool(got), "count": len(got), "via": via,
                       "note": (f"{len(got)} release(s) in the last {days} days via {via}" if got else (note or f"no release found in the last {days} days (or page not readable)"))})
    return items, status


def dedupe_items(items, thr=0.7):
    """Same story from several official sources: keep the most authoritative one (lowest priority number)."""
    from difflib import SequenceMatcher
    out = []
    for it in sorted(items, key=lambda x: x.get("priority", 9)):
        low = it["title"].lower()
        if any(SequenceMatcher(None, low, o["title"].lower()).ratio() >= thr for o in out):
            continue
        out.append(it)
    return sorted(out, key=lambda x: (x.get("date", ""), -x.get("priority", 9)), reverse=True)


def fetch_text(url, n=3000, get=None):
    """Plain text of an official release page (first n characters). None for PDFs/unreadable pages."""
    r = (get or _get)(url)
    if "pdf" in (r.headers.get("content-type", "") if hasattr(r, "headers") else "").lower() or url.lower().endswith(".pdf"):
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside"]):
        t.decompose()
    txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return txt[:n] if len(txt) > 200 else None
