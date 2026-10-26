"""Ratios and rule checks. Alerts are prompts to look closer, not buy/sell instructions."""


def f(x):
    try:
        return None if x in ("", None) else float(x)
    except ValueError:
        return None


def enrich(rows, held_only_total=True):
    out = []
    for r in rows:
        qty = f(r.get("qty")) or 0
        price, avg = f(r.get("price")), f(r.get("avg_cost"))
        chg, lo, hi, eps, dps = f(r.get("change_pct")), f(r.get("low52")), f(r.get("high52")), f(r.get("eps")), f(r.get("dps"))
        prev = price / (1 + chg / 100) if price and chg is not None else None
        d = dict(r)
        d.update(
            qty=qty, price=price, avg_cost=avg, change_pct=chg, low52=lo, high52=hi, eps=eps, dps=dps,
            value=qty * price if price else 0,
            cost=qty * avg if avg else 0,
            day_change=qty * (price - prev) if prev else 0,
            vs_low_pct=(price - lo) / lo * 100 if price and lo else None,
            vs_avg_pct=(price - avg) / avg * 100 if price and avg else None,
            range_pos=(price - lo) / (hi - lo) * 100 if price and lo and hi and hi > lo else None,
            yield_pct=dps / price * 100 if price and dps is not None else f(r.get("yield_ttm")),
            pe=price / eps if price and eps and eps > 0 else f(r.get("pe_ttm")),
            payout_pct=dps / eps * 100 if eps and eps > 0 and dps is not None else None,
        )
        d["pl"] = d["value"] - d["cost"]
        d["pl_pct"] = d["pl"] / d["cost"] * 100 if d["cost"] else None
        out.append(d)
    total = sum(r["value"] for r in out)
    for r in out:
        r["weight_pct"] = r["value"] / total * 100 if total else 0
    return out


def totals(h):
    held = [r for r in h if r["qty"] > 0]
    value, cost, day = (sum(r[k] for r in held) for k in ("value", "cost", "day_change"))
    prev = value - day
    return {"value": value, "cost": cost, "pl": value - cost, "pl_pct": (value - cost) / cost * 100 if cost else None,
            "day_change": day, "day_change_pct": day / prev * 100 if prev else None, "n_held": len(held)}


def sector_mix(h, targets):
    total = sum(r["value"] for r in h)
    out = []
    for t in targets:
        cur = sum(r["value"] for r in h if r["sector"] == t["sector"]) / total * 100 if total else 0
        out.append({"sector": t["sector"], "target_pct": float(t["target_pct"]), "current_pct": cur})
    return out


def run_rules(h, watch, mix, index, announcements, R):
    A = []

    def add(id_, ticker, kind, sev, rule, detail):
        A.append({"id": id_, "ticker": ticker, "kind": kind, "severity": sev, "rule": rule, "detail": detail})

    p = lambda v: f"{v:.1f}%"
    held = [r for r in h if r["qty"] > 0]
    for r in held:
        t = r["ticker"]
        if r["vs_low_pct"] is not None and r["vs_low_pct"] <= R["near_low_pct"]:
            add(t + "-low", t, "risk", "watch", "Near 52-week low", f"Rs {r['price']:.2f} is {p(r['vs_low_pct'])} above its 52-week low.")
        if r["vs_avg_pct"] is not None and r["vs_avg_pct"] <= -R["below_avg_pct"]:
            add(t + "-avg", t, "risk", "review", f"{R['below_avg_pct']}% below your cost", f"{p(abs(r['vs_avg_pct']))} below your average. Read the latest results before deciding; do not average down a non-dividend stock.")
        if r["weight_pct"] > R["max_stock_weight_pct"]:
            add(t + "-wt", t, "risk", "trim", f"Over {R['max_stock_weight_pct']}% of portfolio", f"{p(r['weight_pct'])} of the portfolio. Trim back toward 10%.")
        if r["change_pct"] is not None and r["change_pct"] <= -R["day_drop_pct"]:
            add(t + "-drop", t, "risk", "watch", "Big one-day drop", f"Down {p(abs(r['change_pct']))} today. Check for news before reacting.")
        if r["yield_pct"] is not None and r["yield_pct"] < R["trim_yield_below_pct"] and r["range_pos"] is not None and r["range_pos"] >= R["trim_range_pos_pct"]:
            add(t + "-trim", t, "risk", "trim", "Yield thin after a run-up", f"Yield {p(r['yield_pct'])} and price in the top {100 - R['trim_range_pos_pct']}% of its 52-week range. Consider trimming half.")
    for s in mix:
        if s["sector"].lower() == "cash":
            continue
        if s["current_pct"] > R["max_sector_weight_pct"]:
            add(s["sector"] + "-sector", s["sector"], "risk", "sector", f"Sector over {R['max_sector_weight_pct']}%", f"{s['sector']} is {p(s['current_pct'])} of the portfolio. Stop adding to it.")
        elif abs(s["current_pct"] - s["target_pct"]) > R["sector_drift_pct"]:
            word = "above" if s["current_pct"] > s["target_pct"] else "below"
            add(s["sector"] + "-drift", s["sector"], "info", "sector", "Sector off target", f"{s['sector']} is {p(s['current_pct'])} against a {p(s['target_pct'])} target ({word}). Steer new money accordingly.")
    # opportunities: plan stocks (held or not) and watchlist
    for r in [x for x in h if x.get("plan") in ("core", "new")] + watch:
        t = r["ticker"]
        if r["yield_pct"] is None or r["pe"] is None:
            continue
        near = r["vs_low_pct"] is not None and r["vs_low_pct"] <= R["opp_near_low_pct"]
        below = r["vs_avg_pct"] is not None and r["qty"] > 0 and r["vs_avg_pct"] <= -R["opp_below_avg_pct"]
        if r["yield_pct"] >= R["opp_min_yield_pct"] and r["pe"] <= R["opp_max_pe"] and (near or below):
            note = ""
            if r["payout_pct"] is not None and r["payout_pct"] > R["high_payout_pct"]:
                note = f" Payout is {r['payout_pct']:.0f}% of earnings, so check the dividend is sustainable."
            add(t + "-opp", t, "opportunity", "opportunity", "Dividend dip setup",
                f"Yield {p(r['yield_pct'])}, P/E {r['pe']:.1f}, {p(r['vs_low_pct'])} above 52-week low. Worth a small tranche from your monthly plan if the latest results are fine.{note}")
    if index and index.get("change_pct") is not None and index["change_pct"] <= -R["index_drop_pct"]:
        add("index-drop", "KSE-100", "risk", "watch", "Market falling", f"KSE-100 is down {p(abs(index['change_pct']))} today. Stick to your tranches; do not chase.")
    tickers = {r["ticker"] for r in held}
    for a in announcements or []:
        if a["ticker"] in tickers and a["category"] in ("Risk notice", "Results", "Dividend / book closure", "Board meeting"):
            sev = "review" if a["category"] == "Risk notice" else "watch"
            add(f"ann-{a['ticker']}-{abs(hash(a['title'])) % 10**6}", a["ticker"], "risk", sev, a["category"], a["title"][:220])
    order = {"review": 0, "trim": 1, "sector": 2, "watch": 3, "opportunity": 4}
    A.sort(key=lambda a: order.get(a["severity"], 9))
    return A
