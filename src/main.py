import argparse, csv, datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import fetch, rules, notify, render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG, DOCS = os.path.join(ROOT, "config"), os.path.join(ROOT, "docs")


def read_csv(name):
    with open(os.path.join(CFG, name), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def selftest():
    checks = [
        ("market-watch (all prices)", lambda: len(fetch.market_watch())),
        ("52-week range OGDC", lambda: fetch.range_52w("OGDC")),
        ("KSE-100 level", fetch.kse100),
        ("company announcements", lambda: len(fetch.company_announcements())),
        ("news headlines", lambda: len(fetch.news(["SBP monetary policy"]))),
    ]
    for name, fn in checks:
        try:
            print("OK  ", name, "->", fn())
        except Exception as e:
            print("FAIL", name, "->", repr(e)[:200])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use the prices in the CSV files, no network")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--daily", action="store_true", help="always send the daily summary notification")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    cfg = load_json(os.path.join(CFG, "settings.json"), {})
    R = cfg["rules"]
    holdings, watch, targets = read_csv("holdings.csv"), read_csv("watchlist.csv"), read_csv("sector_targets.csv")
    status, index, anns, news = [], None, [], []
    now = dt.datetime.now(fetch.PKT)

    if not a.offline:
        symbols = sorted({r["ticker"] for r in holdings + watch})
        try:
            mw = fetch.market_watch()
            hit = 0
            for r in holdings + watch:
                q = mw.get(r["ticker"])
                if q and q["price"]:
                    r["price"], r["change_pct"], r["price_time"] = q["price"], q["change_pct"] if q["change_pct"] is not None else 0, now.strftime("%H:%M")
                    hit += 1
            status.append({"name": "Prices", "ok": True, "note": f"{hit}/{len(holdings + watch)} symbols updated from PSX market watch"})
        except Exception as e:
            status.append({"name": "Prices", "ok": False, "note": f"using last saved prices ({str(e)[:90]})"})
        cache_path = os.path.join(DOCS, "range_cache.json")
        cache = load_json(cache_path, {})
        if cache.get("date") != now.date().isoformat():
            cache = {"date": now.date().isoformat(), "ranges": {}}
            for s in symbols:
                try:
                    lo, hi, src = fetch.range_52w(s)
                    cache["ranges"][s] = [lo, hi, src]
                except Exception:
                    pass
            json.dump(cache, open(cache_path, "w"))
        for r in holdings + watch:
            rg = cache["ranges"].get(r["ticker"])
            if rg and rg[0] and rg[1]:
                r["low52"], r["high52"] = rg[0], rg[1]
        status.append({"name": "52-week ranges", "ok": bool(cache["ranges"]), "note": f"{len(cache['ranges'])} symbols refreshed today" if cache["ranges"] else "using saved ranges"})
        try:
            index = fetch.kse100()
            status.append({"name": "KSE-100", "ok": True, "note": f"{index['level']:,.2f}"})
        except Exception as e:
            status.append({"name": "KSE-100", "ok": False, "note": str(e)[:100]})
        try:
            anns = fetch.company_announcements()
            status.append({"name": "Announcements", "ok": True, "note": f"{len(anns)} items"})
        except Exception as e:
            status.append({"name": "Announcements", "ok": False, "note": str(e)[:100]})
        news = fetch.news(cfg.get("news_queries", []))
        status.append({"name": "News", "ok": bool(news), "note": f"{len(news)} headlines" if news else "no headlines retrieved"})
    else:
        status.append({"name": "Offline mode", "ok": False, "note": "showing prices saved in the CSV files"})

    mine = {r["ticker"] for r in holdings}
    wl = {r["ticker"] for r in watch}
    for x in anns:
        x["scope"] = "holding" if x["ticker"] in mine else "watchlist" if x["ticker"] in wl else "market"

    H, W = rules.enrich(holdings), rules.enrich(watch)
    mix = rules.sector_mix(H, targets)
    alerts = rules.run_rules(H, W, mix, index, anns, R)
    data = {"generated": now.strftime("%a %d %b %Y, %H:%M PKT"), "title": cfg.get("dashboard_title", "PSX dashboard"),
            "show_rs": cfg.get("show_rs_amounts", False), "totals": rules.totals(H), "holdings": H, "watchlist": W, "sector_mix": mix,
            "alerts": alerts, "index": index, "announcements": anns, "news": news, "status": status}
    render.write(DOCS, data)
    print("page written:", os.path.join(DOCS, "index.html"), "| alerts:", len(alerts))

    if a.no_notify or a.offline:
        return
    st_path = os.path.join(DOCS, "state.json")
    st = load_json(st_path, {})
    day = now.date().isoformat()
    if st.get("day") != day:
        st = {"day": day, "sent": []}
    new = [x for x in alerts if x["id"] not in st["sent"] and x["severity"] in ("review", "trim", "sector", "watch", "opportunity") and x["kind"] != "info"]
    t = data["totals"]
    try:
        if a.daily:
            top = "\n".join(f"- {x['ticker']}: {x['rule']}" for x in alerts[:8]) or "No rules triggered."
            pct = t["day_change_pct"]
            notify.send(f"PSX daily report: {len(alerts)} alerts" + (f", day {pct:+.1f}%" if pct is not None else ""), top, urgent=False)
        elif new:
            body = "\n".join(f"{x['ticker']}: {x['rule']} - {x['detail']}" for x in new[:8])
            notify.send(f"PSX alert: {len(new)} new", body, urgent=any(x["severity"] in ("review", "trim") for x in new))
        st["sent"] += [x["id"] for x in new]
        json.dump(st, open(st_path, "w"))
    except Exception as e:
        print("notification failed:", e)


if __name__ == "__main__":
    main()
