import argparse, csv, datetime as dt, hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import fetcher as fetch, rules, notify, render, insights, indicators, signals, ai_agent

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
        ("all indices (KSE100/KMI30/KSE30)", lambda: sorted(fetch.indices_all())[:8]),
        ("KMI-30 constituents", lambda: len(fetch.index_members("KMI30"))),
        ("KMI All Share constituents", lambda: len(fetch.index_members("KMIALLSHR"))),
        ("fundamentals + payouts HUBC", lambda: {k: v for k, v in fetch.fundamentals("HUBC").items() if k != "payouts"}),
        ("FIPI / LIPI flows", lambda: fetch.flows(load_json(os.path.join(CFG, "settings.json"), {}).get("flows_urls") or fetch.DEFAULT_FLOWS_URLS)),
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
    ap.add_argument("--ai", action="store_true", help="run the AI analyst now (otherwise it runs on the daily report and manual runs, and reuses its last answer)")
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
    idx_list, flows, ext, src_status = [], None, [], []
    fundamentals = load_json(os.path.join(DOCS, "fund_cache.json"), {}).get("data", {})
    _m = load_json(os.path.join(DOCS, "members_cache.json"), {})
    members = {k: set(_m[k]) for k in ("KMI30", "KMIALLSHR") if _m.get(k)}
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
        if cfg.get("allow_media_headlines"):      # off by default: only official sources are used
            news = fetch.news(cfg.get("news_queries", []))
            status.append({"name": "Media headlines", "ok": bool(news), "note": f"{len(news)} headlines" if news else "no headlines retrieved"})
        try:
            raw_items, src_status = fetch.official_news(cfg.get("official_sources"), days=14)
            ext = fetch.dedupe_items(raw_items)
            n_src = sum(1 for s_ in src_status if s_["ok"] and s_["id"] != "psx")
            status.append({"name": "Official sources", "ok": n_src > 0, "note": f"{len(ext)} releases from {n_src}/{len(src_status) - 1} official bodies (SBP, SECP, Finance, regulators...)" if n_src else "no official release found or pages not readable; see the source list on the page"})
        except Exception as e:
            ext, src_status = [], []
            status.append({"name": "Official sources", "ok": False, "note": str(e)[:100]})
        if not a.no_history:
            try:
                import history
                st = history.update(symbols, os.path.join(DOCS, "history"), budget=int(os.getenv("HISTORY_BUDGET", "80")))
                ok = st["symbols_with_data"] > 0
                srcs = ", ".join(f"{v} from {k}" for k, v in st.get("sources", {}).items())
                note = (f"{st['symbols_with_data']} stocks ({srcs})" if ok else "no price history retrieved yet") + (". Yahoo problems: " + "; ".join(st["yahoo_errors"]) if st.get("yahoo_errors") else "")
                status.append({"name": "History", "ok": ok, "note": note})
            except Exception as e:
                status.append({"name": "History", "ok": False, "note": str(e)[:100]})
        # ---- new feeds: sector benchmarks, Shariah index lists, fundamentals, flows
        try:
            ix_all = fetch.indices_all()
            idx_list = [{"name": n, "level": ix_all[k]["level"], "change_pct": ix_all[k]["change_pct"]} for k, n in (("KSE100", "KSE-100"), ("KMI30", "KMI-30"), ("KSE30", "KSE-30"), ("KMIALLSHR", "KMI All Share")) if k in ix_all]
            status.append({"name": "Indices", "ok": bool(idx_list), "note": ", ".join(i["name"] for i in idx_list) or "none found"})
        except Exception as e:
            status.append({"name": "Indices", "ok": False, "note": str(e)[:100]})
        mem_path = os.path.join(DOCS, "members_cache.json")
        mem = load_json(mem_path, {})
        if mem.get("date") != now.date().isoformat():
            mem = {"date": now.date().isoformat(), "KMI30": mem.get("KMI30"), "KMIALLSHR": mem.get("KMIALLSHR")}
            for code in ("KMI30", "KMIALLSHR"):
                try:
                    mem[code] = sorted(fetch.index_members(code))
                except Exception:
                    pass
            json.dump(mem, open(mem_path, "w"))
        members = {k: set(mem[k]) for k in ("KMI30", "KMIALLSHR") if mem.get(k)}
        status.append({"name": "Shariah lists", "ok": bool(members), "note": ", ".join(f"{k} {len(v)}" for k, v in members.items()) or "KMI index lists not available; Shariah status unknown"})
        fund_path = os.path.join(DOCS, "fund_cache.json")
        fc = load_json(fund_path, {})
        if fc.get("date") != now.date().isoformat():
            fc = {"date": now.date().isoformat(), "data": {k: v for k, v in fc.get("data", {}).items() if v}}
        from concurrent.futures import ThreadPoolExecutor as _TP

        def _fund(sym):
            try:
                return sym, fetch.fundamentals(sym)
            except Exception:
                return sym, None
        todo = [x for x in symbols if x not in fc["data"]]
        with _TP(6) as ex:
            for sym, fd in ex.map(_fund, todo):
                if fd:
                    fc["data"][sym] = fd
        json.dump(fc, open(fund_path, "w"))
        fundamentals = fc["data"]
        status.append({"name": "Fundamentals", "ok": bool(fundamentals), "note": f"EPS and dividend history for {len(fundamentals)}/{len(symbols)} stocks" if fundamentals else "company page tables not readable; using PSX ratios only"})
        try:
            flows = fetch.flows(cfg.get("flows_urls") or fetch.DEFAULT_FLOWS_URLS)
            status.append({"name": "FIPI/LIPI", "ok": True, "note": f"foreign net {flows['fipi_net']}, local net {flows['lipi_net']}"})
        except Exception as e:
            status.append({"name": "FIPI/LIPI", "ok": False, "note": "optional, not available: " + str(e)[:90]})
    else:
        status.append({"name": "Offline mode", "ok": False, "note": "showing prices saved in the CSV files"})

    H, W = rules.enrich(holdings), rules.enrich(watch)
    mix = rules.sector_mix(H, targets)
    alerts = rules.run_rules(H, W, mix, index, anns, R)
    events = rules.build_events(anns, {r["ticker"] for r in holdings}, {r["ticker"] for r in watch}, fetch._parse_date)
    T = rules.totals(H)

    # ---- state (alert dedupe + signal stability) ----
    st_path = os.path.join(DOCS, "state.json")
    st = load_json(st_path, {})
    today = now.date()

    # ---- technical indicators, quantitative signals, AI analyst ----
    hist_dir = os.path.join(DOCS, "history")
    sector_pct = {m["sector"]: m["current_pct"] for m in mix}
    anns_by = {}
    for x in anns:
        anns_by.setdefault(x["ticker"], []).append(x)
    rows_all, seen_t = [], set()
    for r in H + W:
        if r["ticker"] not in seen_t:
            seen_t.add(r["ticker"])
            rows_all.append(r)
    kmi_all, kmi30 = members.get("KMIALLSHR"), members.get("KMI30")
    results = []
    for r in rows_all:
        t = r["ticker"]
        tech = indicators.compute(indicators.load_rows(hist_dir, t), r.get("price"), today)
        tech["src"] = indicators.load_src(hist_dir, t)
        shariah = (t in kmi_all) if kmi_all else (True if kmi30 and t in kmi30 else None)
        res = signals.assess(r, tech, fundamentals.get(t), anns_by.get(t, []), R, cfg.get("signals"), sector_pct.get(r.get("sector")), shariah)
        res["kmi30"] = bool(kmi30 and t in kmi30)
        results.append(res)
    mk = {}
    for i in idx_list:
        if i.get("change_pct") is not None:
            mk[i["name"].replace("-", "").replace(" ", "")] = {"change_pct": i["change_pct"], "level": i["level"]}
    if flows:
        mk["FIPI_LIPI"] = {k: v for k, v in (("fipi_net", flows.get("fipi_net")), ("lipi_net", flows.get("lipi_net"))) if v is not None}
    # ---- official items for the AI and the page: PSX filings of your stocks first, then official bodies
    held_t, watch_t = {r["ticker"] for r in holdings if (rules.f(r.get("qty")) or 0) > 0}, {r["ticker"] for r in watch}
    keep_cat = {"Risk notice", "Results", "Dividend / book closure", "Board meeting", "Material information"}
    psx_items = []
    for x in anns:
        d = fetch._parse_date(x["date"])
        if x["category"] in keep_cat and (x["ticker"] in held_t or x["ticker"] in watch_t) and d and (today - d).days <= 10:
            psx_items.append({"source": "Pakistan Stock Exchange", "source_id": "psx", "source_url": "https://dps.psx.com.pk/", "priority": 0, "date": d.isoformat(),
                              "title": f"{x['ticker']}: {x['title']}", "url": x.get("url", ""), "ticker": x["ticker"], "via": "PSX company page"})
    psx_items = sorted(psx_items, key=lambda i: i["date"], reverse=True)
    psx_items = sorted(psx_items, key=lambda i: 0 if i["ticker"] in held_t else 1)[:8]
    off_items = (psx_items + sorted(ext, key=lambda i: i.get("date", ""), reverse=True))[:14]
    for n_, it in enumerate(off_items, 1):
        it["id"] = f"O{n_}"
    if not a.offline and off_items:
        from concurrent.futures import ThreadPoolExecutor as _TP2

        def _txt(it):
            if it["source_id"] == "psx":
                return None
            try:
                return fetch.fetch_text(it["url"])
            except Exception:
                return None
        with _TP2(4) as ex:
            for it, t_ in zip(off_items, ex.map(_txt, off_items)):
                if t_:
                    it["text"] = t_
    ai_block = ai_agent.run(results, anns, off_items, mk, cfg.get("ai"), force=(a.ai or a.daily) and not a.offline,
                            cache_path=os.path.join(DOCS, "ai.json"), now=now)
    ai_agent.apply(results, ai_block)
    sig_by = {x["ticker"]: x for x in results}
    for r in H + W:
        r["sig"] = sig_by.get(r["ticker"])
    prev_sig, new_sig = st.get("sig", {}), {}
    for x in results:
        p = prev_sig.get(x["ticker"])
        new_sig[x["ticker"]] = [x["signal"], (p[1] + 1) if p and p[0] == x["signal"] else 1, (p[2] if len(p) > 2 else None) if p and p[0] == x["signal"] else (p[0] if p else None)]
    have_rule_alert = {(x["ticker"], x["severity"]) for x in alerts}
    for x in results:
        t, sg_, fl = x["ticker"], x["signal"], x["flags"]
        why = (x["ai"]["rationale"] if x.get("ai") and x["ai"].get("rationale") and not x["ai"].get("stale") else x["summary"])[:300]
        stable = new_sig[t][1] >= 2
        if x["held"] and sg_ == "Review/Exit" and "risk_notice" not in fl and (t, "review") not in have_rule_alert:
            alerts.append({"id": f"{t}-sig-review", "ticker": t, "kind": "risk", "severity": "review", "rule": "Signal: Review/Exit", "detail": why, "stable": stable})
        elif x["held"] and sg_ == "Trim/Take Profit" and "over_cap" not in fl and (t, "trim") not in have_rule_alert:
            alerts.append({"id": f"{t}-sig-trim", "ticker": t, "kind": "risk", "severity": "trim", "rule": "Signal: Trim/Take Profit", "detail": why, "stable": stable})
        elif sg_ == "Strong Buy" or "all_triggers" in fl:
            alerts.append({"id": f"{t}-sig-buy", "ticker": t, "kind": "opportunity", "severity": "opportunity",
                           "rule": "Watchlist triggers met" if "all_triggers" in fl and not x["held"] else "Signal: Strong Buy", "detail": why, "stable": stable})
    # ---- more roles so nothing is missed: new filings, AI warnings, lowered signals, broken data feeds
    ladder = signals.HELD
    for x in anns:
        d = fetch._parse_date(x["date"])
        if x["ticker"] in held_t and x["category"] in ("Results", "Dividend / book closure", "Board meeting", "Material information") and d and (today - d).days <= 3:
            alerts.append({"id": f"filing-{x['ticker']}-{hashlib.md5(x['title'].encode()).hexdigest()[:8]}", "ticker": x["ticker"], "kind": "risk", "severity": "watch",
                           "rule": f"New filing: {x['category']}", "detail": x["title"][:220] + " (open the filing before you act on the signal)", "stable": True, "url": x.get("url", "")})
    for x in results:
        t, a_ = x["ticker"], x.get("ai")
        if x["held"] and a_ and not a_.get("stale") and (a_["view"] == "downgrade" or a_["sentiment"] == "negative") and not any(al["ticker"] == t and al["severity"] in ("review", "trim") for al in alerts):
            alerts.append({"id": f"{t}-ai-warn-{x['signal'].replace('/', '')}", "ticker": t, "kind": "risk", "severity": "watch", "rule": "AI analyst warns",
                           "detail": (a_["rationale"] or "Negative tone in recent filings")[:240], "stable": True})
        p = new_sig.get(t)
        if x["held"] and p and p[2] and p[1] >= 2 and p[1] <= 26 and p[2] in ladder and x["signal"] in ladder and ladder.index(x["signal"]) < ladder.index(p[2]) and not any(al["ticker"] == t and al["severity"] in ("review", "trim") for al in alerts):
            alerts.append({"id": f"{t}-lowered-{p[2].replace('/', '')}-{x['signal'].replace('/', '')}", "ticker": t, "kind": "risk", "severity": "watch", "rule": f"Signal lowered: {p[2]} to {x['signal']}",
                           "detail": x["summary"][:240], "stable": True})
    if not a.offline and not prices_ok:
        alerts.append({"id": "data-prices-" + today.isoformat(), "ticker": "DATA", "kind": "risk", "severity": "review", "rule": "Prices are not updating",
                       "detail": "No live price source worked on the last run, so every signal uses old prices. Check the Actions tab.", "stable": True})
    if ai_block.get("status") == "error":
        alerts.append({"id": "data-ai-" + today.isoformat(), "ticker": "DATA", "kind": "risk", "severity": "watch", "rule": "AI analyst failed", "detail": ai_block.get("note", "")[:200], "stable": True})
    order = {"review": 0, "trim": 1, "sector": 2, "watch": 3, "opportunity": 4}
    alerts.sort(key=lambda a_: order.get(a_["severity"], 9))
    # ---- audit log of signals (lets you check later whether they were useful) ----
    log = signals.audit_log(os.path.join(DOCS, "signals_log.json"), today.isoformat(), results) if not a.offline else {}
    record = signals.track_record(log)
    tr_ok = lambda r_: r_.get("price") and abs(r_.get("change_pct") or 0) <= 10
    verified = prices_ok and hit >= 0.95 * len(holdings + watch) and all(tr_ok(r) for r in rows_all) if not a.offline else False

    # ---- notifications (before rendering so the page can show the result) ----
    sent_log = st.get("sent", {})
    if not isinstance(sent_log, dict):
        sent_log = {}
    sent_log = {k: v for k, v in sent_log.items() if (today - dt.date.fromisoformat(v)).days < 5}
    notify_note = None
    if a.test_notify:
        ok, errs = notify.send("PSX dashboard test", "If you can read this, phone and email alerts work.", False)
        notify_note = {"ok": bool(ok) and not errs, "note": ("sent via " + " + ".join(ok) if ok else "not sent") + ("; " + "; ".join(errs) if errs else "")}
    elif not (a.no_notify or a.offline):
        if not prices_ok:
            notify_note = {"ok": False, "note": "skipped: live prices unavailable"}
        else:
            new = [x for x in alerts if x["kind"] != "info" and x.get("stable", True) and x["id"] not in sent_log]
            pct = T["day_change_pct"]
            if a.daily:
                top = "\n".join(f"- {x['ticker']}: {x['rule']}" for x in alerts if x["kind"] != "info")[:700] or "No rules triggered."
                buys = [x["ticker"] for x in results if x["signal"] in ("Strong Buy", "Accumulate")]
                top += ("\nBuy-side signals: " + ", ".join(buys[:10])) if buys else ""
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
            "key_points": [] if ai_block.get("findings") else insights.key_points([{"title": f"{i['title']} - {i['source']}", "url": i["url"], "date": i.get("date", "")} for i in off_items if i["source_id"] != "psx"] + news, index), "status": status, "symbols": all_symbols,
            "rules": R, "indices": idx_list, "flows": flows, "ai": {k: v for k, v in ai_block.items() if k != "assessments"}, "verified": verified,
            "track_record": record, "signal_ladder": {"held": signals.HELD, "unheld": signals.UNHELD}, "kmi_known": bool(kmi_all)}
    key = os.getenv("HOLDINGS_KEY", "")
    if key:
        import vault
        priv = {r["ticker"]: {"q": r["qty"], "a": r["avg_cost"]} for r in H if r["qty"] > 0 and r.get("avg_cost")}
        data["private"] = vault.encrypt(json.dumps(priv), key)
    data["notify"] = notify.diagnose()
    data["official"] = [{k: v for k, v in it.items() if k != "text"} | {"basis": "full text" if it.get("text") else "title only"} for it in off_items]
    data["sources"] = src_status
    data["findings"] = ai_block.get("findings") or []
    data["refs"] = ai_block.get("refs") or {}
    render.write(DOCS, data)
    print("page written | alerts:", len(alerts), "| feeds ok:", sum(s["ok"] for s in status), "/", len(status))
    if not a.offline:
        json.dump({"day": today.isoformat(), "sent": sent_log, "sig": new_sig}, open(st_path, "w"))


if __name__ == "__main__":
    main()
