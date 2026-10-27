"""Full pipeline dry run with NO internet: fake PSX data, fake AI reply, synthetic price history.
Writes a demo page to ./demo_docs/index.html (your real docs/ folder is untouched). Run from the project folder:
    python tests/dry_run.py"""
import csv, datetime as dt, json, os, random, sys
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import fetcher, history, main, ai_agent

OUT = os.path.join(ROOT, "demo_docs")
os.makedirs(os.path.join(OUT, "history"), exist_ok=True)
main.DOCS = OUT
random.seed(7)
rd = lambda n: list(csv.DictReader(open(os.path.join(ROOT, "config", n))))
H, W = rd("holdings.csv"), rd("watchlist.csv")
syms = sorted({r["ticker"] for r in H + W})
today = dt.date.today()
for s in syms:    # synthetic daily history ending at the CSV price
    px = float([r for r in H + W if r["ticker"] == s][0]["price"] or 100)
    series, p = [], px
    for i in range(520):
        series.append(p)
        p /= 1 + random.gauss(0.0002, 0.015)
    series.reverse()
    d, rows = today - dt.timedelta(days=len(series) * 7 // 5 + 3), []
    for v in series:
        while d.weekday() > 4:
            d += dt.timedelta(days=1)
        rows.append([int(d.strftime("%Y%m%d")), round(v, 2), round(v * 1.01, 2), round(v * .99, 2), int(random.uniform(2e5, 2e6))])
        d += dt.timedelta(days=1)
    json.dump({"sym": s, "rows": rows[-500:], "done": []}, open(os.path.join(OUT, "history", s + ".json"), "w"))

def mw():
    out = {}
    for r in H + W:
        out[r["ticker"]] = {"sector": "", "price": float(r["price"]), "change_pct": float(r["change_pct"] or 0),
                            "pe_ttm": random.choice([4.9, 5.3, 6.6, 9.8, 11.2, 14.0]), "yield_ttm": random.choice([10.6, 7.9, 5.7, 3.4, 2.1])}
    return out

def fund(sym):
    return {"eps": [{"label": "EPS", "period": "2025", "values": [30.0, 25.0]}], "payouts": [{"date": (today - dt.timedelta(days=90)).isoformat(), "pct": 200, "dps_est": 20}],
            "n_12m": 2, "n_36m": 6, "dps_12m_est": 25.0}

ann = [{"source": "Company", "date": today.strftime("%b %d, %Y"), "ticker": "SSGC", "title": "Notice: company placed on deficit list", "category": "Risk notice", "url": "#"},
       {"source": "Company", "date": today.strftime("%b %d, %Y"), "ticker": "OGDC", "title": "Financial results for the quarter: profit up 18%, interim dividend Rs 3.5", "category": "Results", "url": "#"},
       {"source": "Company", "date": today.strftime("%b %d, %Y"), "ticker": "ENGROH", "title": "Board meeting to consider financial results", "category": "Board meeting", "url": "#"}]
news = [{"title": "SBP keeps policy rate at 11%, flags inflation risks", "url": "#", "date": "27 Oct 10:00", "topic": "SBP monetary policy rate Pakistan"},
        {"title": "KSE-100 closes higher on banking and E&P buying", "url": "#", "date": "27 Oct 15:30", "topic": "KSE-100 PSX Pakistan stock market"}]

OFF = [{"source": "State Bank of Pakistan", "source_id": "sbp", "source_url": "https://www.sbp.org.pk/", "priority": 1, "via": "official page", "date": today.isoformat(),
        "title": "Monetary Policy Statement: policy rate kept unchanged at 11 percent", "url": "https://www.sbp.org.pk/m_policy/2026/MPS-Oct-2026.pdf"},
       {"source": "Ministry of Finance", "source_id": "mof", "source_url": "https://www.finance.gov.pk/", "priority": 3, "via": "Google News index of the official site", "date": today.isoformat(),
        "title": "Finance Division notifies revised gas circular debt settlement plan", "url": "https://www.finance.gov.pk/press/2026/circular-debt.html"},
       {"source": "SECP", "source_id": "secp", "source_url": "https://www.secp.gov.pk/", "priority": 2, "via": "official page", "date": today.isoformat(),
        "title": "SECP amends rules for listed companies' dividend disclosure and payout timelines", "url": "https://www.secp.gov.pk/press/2026/dividend-rules.html"}]
SRC = [{"id": "psx", "name": "Pakistan Stock Exchange", "home": "https://dps.psx.com.pk/", "covers": "company announcements", "ok": True, "count": None, "note": "company filings"},
       {"id": "sbp", "name": "State Bank of Pakistan", "home": "https://www.sbp.org.pk/", "covers": "policy rate, monetary policy", "ok": True, "count": 1, "via": "official page", "note": "1 release in the last 14 days via official page"},
       {"id": "secp", "name": "SECP", "home": "https://www.secp.gov.pk/", "covers": "capital-market regulation", "ok": True, "count": 1, "via": "official page", "note": "1 release"},
       {"id": "mof", "name": "Ministry of Finance", "home": "https://www.finance.gov.pk/", "covers": "budget, IMF, circular debt", "ok": True, "count": 1, "via": "Google News index of the official site", "note": "1 release via Google News index"},
       {"id": "fbr", "name": "FBR", "home": "https://www.fbr.gov.pk/", "covers": "tax measures", "ok": False, "count": 0, "note": "no release found in the last 14 days (or page not readable)"}]

def fake_post(url, headers=None, json=None, timeout=None):
    body = json["messages"][0]["content"].split("Input JSON:\n", 1)[1]
    import json as J
    p = J.loads(body)
    out = []
    oid = [o["id"] for o in p["official_items"]]
    for i, st in enumerate(p["stocks"]):
        t, ids = st["ticker"], list(st["facts"])[:2]
        a = {"ticker": t, "signal": st["rule_signal"], "sentiment": "neutral", "rationale": f"{t}: the quantitative picture stands; no filing in the supplied data changes it.", "risks": ["Check the next payout announcement"], "opportunity": "", "evidence": ids}
        if t == "OGDC":
            lad = st["ladder"]; k = lad.index(st["rule_signal"]); a.update(signal=lad[min(k + 1, len(lad) - 1)], sentiment="positive", rationale="Quarter profit up 18% with an interim dividend, supportive of the income case.", evidence=ids + [f"{t}.A1"], opportunity="Results and dividend both improved.")
        out.append(a)
    sbp = next((o["id"] for o in p["official_items"] if o["source"].startswith("State Bank")), oid[0])
    mof = next((o["id"] for o in p["official_items"] if o["source"].startswith("Ministry")), oid[0])
    og = next((o["id"] for o in p["official_items"] if "OGDC" in o["title"]), oid[0])
    tool = {"market_view": {"stance": "mixed", "summary": "Index firm on banks and energy, but the SBP is cautious on inflation, so rate-cut hopes are limited.", "evidence": [sbp, "MKT.KSE100.change_pct"]},
            "findings": [
              {"headline": "SBP holds the rate at 11%: no relief yet for rate-sensitive stocks", "what_happened": "The State Bank kept the policy rate unchanged at 11 percent.", "stance": "mixed", "sources": [sbp], "affected": ["MEBL", "HUBC"],
               "analysis": "A hold keeps deposit and bond yields attractive, which competes with dividend stocks, while banks such as MEBL keep earning healthy spreads. Power producers with rupee debt (HUBC) get no financing-cost relief.",
               "reality_check": "A hold is not a tightening, but the statement is cautious on inflation, so a cut next meeting is not assured. Verify the next CPI print before expecting lower rates."},
              {"headline": "Circular-debt plan: positive for gas and power cash flows if executed", "what_happened": "The Finance Division notified a revised settlement plan for gas circular debt.", "stance": "positive", "sources": [mof], "affected": ["SSGC", "OGDC"],
               "analysis": "Faster settlement would ease receivables at exploration companies (OGDC) and gas utilities (SSGC), supporting dividend capacity.",
               "reality_check": "Plans have been announced before and slipped. Only the title was supplied, so the amounts and timeline are unknown: read the notification and watch for actual payments."}],
            "assessments": out}
    class R:
        status_code = 200
        def json(self): return {"content": [{"type": "tool_use", "name": "submit_assessments", "input": tool}], "usage": {"input_tokens": 9000, "output_tokens": 2500}}
    return R()

with mock.patch.object(fetcher, "market_watch", mw), mock.patch.object(fetcher, "range_52w", lambda s: (float([r for r in H + W if r["ticker"] == s][0]["low52"]), float([r for r in H + W if r["ticker"] == s][0]["high52"]), "fake")), \
     mock.patch.object(fetcher, "kse100", lambda: {"level": 163038.46, "prev_close": 161000, "change_pct": 1.27, "high": 1, "low": 1}), \
     mock.patch.object(fetcher, "indices_all", lambda: {"KSE100": {"level": 163038.46, "change_pct": 1.27}, "KMI30": {"level": 245000.1, "change_pct": 1.1}, "KSE30": {"level": 48000.3, "change_pct": 1.4}}), \
     mock.patch.object(fetcher, "index_members", lambda c: set(syms) - {"SYS", "SSGC"} if c == "KMIALLSHR" else set(syms[:12])), \
     mock.patch.object(fetcher, "fundamentals", fund), mock.patch.object(fetcher, "company_announcements", lambda s, days=14: ann), \
     mock.patch.object(fetcher, "news", lambda q: news), mock.patch.object(fetcher, "official_news", lambda s=None, days=14: (list(OFF), SRC)), \
     mock.patch.object(fetcher, "fetch_text", lambda u, n=3000: "The Monetary Policy Committee decided to keep the policy rate at 11 percent. " * 6 if "sbp" in u else None), mock.patch.object(fetcher, "flows", lambda u: {"fipi_net": -4.2, "lipi_net": 4.6, "rows": []}), \
     mock.patch.object(history, "update", lambda *a, **k: {"symbols_with_data": len(syms), "months_fetched": 0, "failed": 0, "oldest": None}), \
     mock.patch.object(ai_agent.requests, "post", fake_post), mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-dry-run", "HOLDINGS_KEY": "dry-run-passphrase-123"}):
    sys.argv = ["main.py", "--ai", "--no-notify"]
    main.main()
print("demo page:", os.path.join(OUT, "index.html"))
