"""Builds docs/history/<SYMBOL>.json (daily closes) from the PSX 'Historical Data' page, month by month.
Each run fetches the current month for every stock, then backfills older months (newest first) within a request
budget, so 10 years of history builds up over a day or two. The page and the exact fields were NOT verified from
the build environment; the dashboard reports how many months were fetched."""
import datetime as dt, json, os, time
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
import fetch

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
        di = next((i for i, h in enumerate(heads) if h in ("TIME", "DATE")), 0)
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) <= max(ci, di):
                continue
            d, c = fetch._parse_date(tds[di]), fetch._num(tds[ci])
            if d and c:
                rows.append([int(d.strftime("%Y%m%d")), c])
    return rows


def _months_back(today, n):
    y, m = today.year, today.month
    for _ in range(n):
        yield y, m
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def update(symbols, out_dir, budget=80):
    os.makedirs(out_dir, exist_ok=True)
    today = dt.datetime.now(fetch.PKT).date()
    cur = (today.year, today.month)
    store, jobs = {}, []
    for s in symbols:
        p = os.path.join(out_dir, s + ".json")
        try:
            store[s] = json.load(open(p))
        except Exception:
            store[s] = {"sym": s, "rows": [], "done": []}
        done = set(store[s]["done"])
        jobs.append((s, cur))
    # backfill list, newest months first, interleaved across symbols
    back = []
    for ym in list(_months_back(today, MAX_MONTHS))[1:]:
        for s in symbols:
            if f"{ym[0]}-{ym[1]:02d}" not in set(store[s]["done"]):
                back.append((s, ym))
    jobs = [(s, cur) for s in symbols] + back[:budget]
    fetched, failed = 0, 0

    def one(job):
        s, (y, m) = job
        try:
            return job, month_rows(s, y, m)
        except Exception:
            return job, None

    with ThreadPoolExecutor(4) as ex:
        for (s, (y, m)), rows in ex.map(one, jobs):
            if rows is None:
                failed += 1
                continue
            fetched += 1
            keep = [r for r in store[s]["rows"] if not (r[0] // 100 == y * 100 + m)]
            store[s]["rows"] = sorted(keep + rows)
            tag = f"{y}-{m:02d}"
            if (y, m) != cur and tag not in store[s]["done"]:
                store[s]["done"].append(tag)
    have = 0
    for s, d in store.items():
        if d["rows"]:
            have += 1
        json.dump({"sym": s, "rows": d["rows"], "done": d["done"]}, open(os.path.join(out_dir, s + ".json"), "w"), separators=(",", ":"))
    oldest = min((d["rows"][0][0] for d in store.values() if d["rows"]), default=None)
    return {"symbols_with_data": have, "months_fetched": fetched, "failed": failed, "oldest": oldest}
