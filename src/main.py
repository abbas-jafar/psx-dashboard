import argparse, csv, datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import fetch, rules, notify, render, insights

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
    import history
    checks = [
        ("prices (screener)", lambda: len(fetch.market_watch())),
        ("52-week range OGDC", lambda: fetch.range_52w("OGDC")),
        ("KSE-100 (indices)", fetch.kse100),
        ("company announcements", lambda: len(fetch.company_announcements(["OGDC"]))),
        ("news headlines", lambda: len(fetch.news(["SBP monetary policy"]))),
        ("price history OGDC (this month)", lambda: len(history.month_rows("OGDC", dt.date.today().year, dt.date.today().month))),
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
    ap.add_argument("--test-notify", action="store_true", help="send a test phone + email notification")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    cfg = load_json(os.path.join(CFG, "settings.json"), {})
    R = cfg["rules"]
    holdings, watch, targets = read_csv("holdings.csv"), read_csv("watchlist.csv"), read_csv("sector_targets.csv")
    status, index, anns, news, all_symbols = [], None, [], [], []
    now = dt.datetime.now(fetch.PKT)
    prices_ok = False
    symbols = sorted({r["ticker"] for r in holdings + watch})

    if not a.offline:
        mw = {}
        try:
            mw, how = fetch.market_watch(), "PSX screener"
        except Exception:
            how = "per-stock quotes"
            from concurrent.futures import ThreadPoolExecutor

            def one(s):
                try:
                    return s, fetch.quote(s)
                except Exception:
                    return s, None
            with ThreadPoolExecutor(6) as ex:
                for s, q in ex.map(one, symbols):
                    if q:
                        mw[s] = q
        all_symbols = sorted(k for k in mw if k.isalnum())
        hit = 0
        for r in holdings + watch:
            q = mw.get(r["ticker"])
            if q and q.get("price"):
                r["price"], r["change_pct"], r["price_time"] = q["price"], q["change_pct"] if q["change_pct"] is not None else 0, now.strftime("%H:%M")
                r["pe_ttm"], r["yield_ttm"] = q.get("pe_ttm"), q.get("yield_ttm")
                hit += 1
        prices_ok = hit > 0
        status.append({"name": "Prices", "ok": prices_ok, "note": f"{hit}/{len(holdings + watch)} stocks updated via {how}" if prices_ok else "no live source worked; showing saved prices"})
        cache_path = os.path.join(DOCS, "range_cache.json")
        cache = load_json(cache_path, {})
        wanted = set(symbols)
        if cache.get("date") != now.date().isoformat() or not wanted <= set(cache.get("ranges", {})):
            old = cache.get("ranges", {}) if cache.get("date") == now.date().isoformat() else {}
            cache = {"date": now.date().isoformat(), "ranges": old}
            for s in symbols:
                if s in old:
                    continue
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
        status.append({"name": "52-week ranges", "ok": bool(cache["ranges"]), "note": f"{len(cache['ranges'])} stocks" if cache["ranges"] else "using saved ranges"})
        try:
            index = fetch.kse100()
            status.append({"name": "KSE-100", "ok": True, "note": f"{index['level']:,.2f}"})
        except Exception as e:
            status.append({"name": "KSE-100", "ok": False, "note": str(e)[:100]})
        try:
            anns = fetch.company_announcements(symbols)
            status.append({"name": "Announcements", "ok": True, "note": f"{len(anns)} items from company pages"})
        except Exception as e:
            status.append({"name": "Announcements", "ok": False, "note": str(e)[:100]})
        news = fetch.news(cfg.get("news_queries", []))
        status.append({"name": "News", "ok": bool(news), "note": f"{len(news)} headlines" if news else "no headlines retrieved"})
        if not a.no_history:
            try:
                import history
                st = history.update(symbols, os.path.join(DOCS, "history"), budget=int(os.getenv("HISTORY_BUDGET", "80")))
                ok = st["symbols_with_data"] > 0
                note = f"{st['symbols_with_data']} stocks, {st['months_fetched']} months fetched" if ok else "no price history retrieved yet"
                status.append({"name": "History", "ok": ok, "note": note})
            except Exception as e:
                status.append({"name": "History", "ok": False, "note": str(e)[:100]})
    else:
        status.append({"name": "Offline mode", "ok": False, "note": "showing prices saved in the CSV files"})

    H, W = rules.enrich(holdings), rules.enrich(watch)
    mix = rules.sector_mix(H, targets)
    alerts = rules.run_rules(H, W, mix, index, anns, R)
    events = rules.build_events(anns, {r["ticker"] for r in holdings}, {r["ticker"] for r in watch}, fetch._parse_date)
    T = rules.totals(H)

    # ---- notifications (before rendering so the page can show the result) ----
    st_path = os.path.join(DOCS, "state.json")
    st = load_json(st_path, {})
    sent_log = st.get("sent", {})
    if not isinstance(sent_log, dict):
        sent_log = {}
    today = now.date()
    sent_log = {k: v for k, v in sent_log.items() if (today - dt.date.fromisoformat(v)).days < 5}
    notify_note = None
    if a.test_notify:
        ok, errs = notify.send("PSX dashboard test", "If you can read this, phone and email alerts work.", False)
        notify_note = {"ok": bool(ok) and not errs, "note": ("sent via " + " + ".join(ok) if ok else "not sent") + ("; " + "; ".join(errs) if errs else "")}
    elif not (a.no_notify or a.offline):
        if not prices_ok:
            notify_note = {"ok": False, "note": "skipped: live prices unavailable"}
        else:
            new = [x for x in alerts if x["kind"] != "info" and x["id"] not in sent_log]
            pct = T["day_change_pct"]
            if a.daily:
                top = "\n".join(f"- {x['ticker']}: {x['rule']}" for x in alerts if x["kind"] != "info")[:900] or "No rules triggered."
                head = f"PSX daily report: {len([x for x in alerts if x['kind'] == 'risk'])} alerts" + (f", portfolio {pct:+.1f}%" if pct is not None else "")
                ok, errs = notify.send(head, top, False)
            elif new:
                body = "\n".join(f"{x['ticker']}: {x['rule']} - {x['detail']}" for x in new[:8])
                ok, errs = notify.send(f"PSX alert: {len(new)} new", body, any(x["severity"] in ("review", "trim") for x in new))
            else:
                ok, errs = None, []
            if ok is None:
                notify_note = {"ok": True, "note": "no new alerts to send"}
            else:
                notify_note = {"ok": bool(ok) and not errs, "note": ("sent via " + " + ".join(ok) if ok else "NOT sent") + ("; " + "; ".join(errs) if errs else "")}
                if ok and not a.daily:
                    for x in new:
                        sent_log[x["id"]] = today.isoformat()
    if notify_note:
        status.append({"name": "Alerts", **notify_note})

    data = {"generated": now.strftime("%a %d %b %Y, %H:%M PKT"), "title": cfg.get("dashboard_title", "PSX dashboard"),
            "show_rs": cfg.get("show_rs_amounts", False), "repo": cfg.get("github_repo", ""), "totals": T, "holdings": H, "watchlist": W,
            "sector_mix": mix, "alerts": alerts, "events": events, "index": index, "news": news,
            "key_points": insights.key_points(news, index), "status": status, "symbols": all_symbols}
    render.write(DOCS, data)
    print("page written | alerts:", len(alerts), "| feeds ok:", sum(s["ok"] for s in status), "/", len(status))
    if not a.offline:
        json.dump({"day": today.isoformat(), "sent": sent_log}, open(st_path, "w"))


if __name__ == "__main__":
    main()
