"""Price history. Sources, in order: PSX data portal 'Historical Data' page (official; untested from the build sandbox), then Yahoo Finance
(UNOFFICIAL fallback, one request gives 10 years). The source used is stored per stock and shown on the page.
Builds docs/history/<SYMBOL>.json (rows of [yyyymmdd, close, high, low, volume]; high/low/volume may be null) from the PSX 'Historical Data' page, month by month.
Each run fetches the current month for every stock, then backfills older months (newest first) within a request
budget, so 10 years of history builds up over a day or two. The page and the exact fields were NOT verified from
the build environment; the dashboard reports how many months were fetched."""
import datetime as dt, json, os, time
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
import fetcher as fetch

MAX_MONTHS = 120


def month_rows(sym, year, month):
    r = requests.post(fetch.BASE + "/historical", data={"month": month, "year": year, "symbol": sym}, headers=fetch.HDR, timeout=30)
    r.raise_for_status()
    rows = []
    for table in BeautifulSoup(r.text, "html.parser").find_all("table"):
        heads = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
        if "CLOSE" not in heads:
            continue
        ci = heads.index("CLOSE")
        col = lambda n: heads.index(n) if n in heads else None
        hi_i, lo_i, vo_i = col("HIGH"), col("LOW"), col("VOLUME")
        di = next((i for i, h in enumerate(heads) if h in ("TIME", "DATE")), 0)
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) <= max(ci, di):
                continue
            d, c = fetch._parse_date(tds[di]), fetch._num(tds[ci])
            if d and c:
                pick = lambda i: fetch._num(tds[i]) if i is not None and i < len(tds) else None
                rows.append([int(d.strftime("%Y%m%d")), c, pick(hi_i), pick(lo_i), pick(vo_i)])
    return rows


def _months_back(today, n):
    y, m = today.year, today.month
    for _ in range(n):
        yield y, m
        m -= 1
        if m == 0:
            y, m = y - 1, 12


YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.KA"


def yahoo_rows(sym, rng="10y", get=None):
    """Daily rows [yyyymmdd, close, high, low, volume] from Yahoo Finance (symbol.KA = Karachi). UNOFFICIAL source."""
    get = get or requests.get
    r = get(YAHOO.format(sym=sym), params={"range": rng, "interval": "1d"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Yahoo HTTP {r.status_code}")
    res = r.json()["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(t, fetch.PKT).date()
        g = lambda k: round(q[k][i], 2) if q.get(k) and q[k][i] is not None else None
        rows.append([int(d.strftime("%Y%m%d")), round(c, 2), g("high"), g("low"), q["volume"][i] if q.get("volume") else None])
    if not rows:
        raise RuntimeError("Yahoo returned no rows")
    return rows


def update(symbols, out_dir, budget=80, yahoo_get=None):
    os.makedirs(out_dir, exist_ok=True)
    today = dt.datetime.now(fetch.PKT).date()
    cur = (today.year, today.month)
    store = {}
    for s in symbols:
        try:
            store[s] = json.load(open(os.path.join(out_dir, s + ".json")))
        except Exception:
            store[s] = {}
        store[s].setdefault("sym", s)
        store[s].setdefault("rows", [])
        store[s].setdefault("done", [])
    back = []
    for ym in list(_months_back(today, MAX_MONTHS))[1:]:
        for s in symbols:
            if f"{ym[0]}-{ym[1]:02d}" not in set(store[s]["done"]):
                back.append((s, ym))
    fetched, failed, psx_ok = 0, 0, set()

    def one(job):
        s, (y, m) = job
        try:
            return job, month_rows(s, y, m)
        except Exception:
            return job, None

    def run(jobs):
        nonlocal fetched, failed
        with ThreadPoolExecutor(4) as ex:
            for (s, (y, m)), rows in ex.map(one, jobs):
                if rows is None:
                    failed += 1
                    continue
                fetched += 1
                if rows and (y, m) == cur:
                    psx_ok.add(s)
                keep = [r for r in store[s]["rows"] if not (r[0] // 100 == y * 100 + m)]
                store[s]["rows"] = sorted(keep + rows)
                tag = f"{y}-{m:02d}"
                if (y, m) != cur and tag not in store[s]["done"]:
                    store[s]["done"].append(tag)

    run([(s, cur) for s in symbols])
    if psx_ok:                      # only spend the backfill budget if the PSX history page actually answers
        run([j for j in back if j[0] in psx_ok][:budget])
    # ---- fallback / backfill from Yahoo (unofficial), clearly labelled
    yerrs, ycalls = [], 0
    for s in symbols:
        d = store[s]
        need_all = s not in psx_ok
        need_back = s in psx_ok and len(d["rows"]) < 300 and not d.get("yahoo_done") and ycalls < 40
        if not (need_all or need_back) or ycalls >= 60:
            continue
        try:
            ycalls += 1
            fresh = d.get("yahoo_done") and need_all
            rows = yahoo_rows(s, "1mo" if fresh else "10y", yahoo_get)
            if need_all:
                first = rows[0][0]
                d["rows"] = sorted([r for r in d["rows"] if r[0] < first] + rows)
            else:
                oldest = d["rows"][0][0] if d["rows"] else 99999999
                d["rows"] = sorted([r for r in rows if r[0] < oldest] + d["rows"])
            d["yahoo_done"] = True
            d["src"] = "Yahoo Finance (unofficial)" if need_all else "PSX + Yahoo Finance backfill"
        except Exception as e:
            yerrs.append(f"{s}: {str(e)[:60]}")
    for s in psx_ok:
        if store[s].get("src") is None:
            store[s]["src"] = "PSX data portal"
    have, srcs = 0, {}
    for s, d in store.items():
        if d["rows"]:
            have += 1
            srcs[d.get("src", "PSX data portal")] = srcs.get(d.get("src", "PSX data portal"), 0) + 1
        json.dump({"sym": s, "rows": d["rows"], "done": d["done"], "src": d.get("src"), "yahoo_done": d.get("yahoo_done", False)}, open(os.path.join(out_dir, s + ".json"), "w"), separators=(",", ":"))
    oldest = min((d["rows"][0][0] for d in store.values() if d["rows"]), default=None)
    return {"symbols_with_data": have, "months_fetched": fetched, "failed": failed, "oldest": oldest, "sources": srcs, "yahoo_errors": yerrs[:3], "psx_ok": len(psx_ok)}
