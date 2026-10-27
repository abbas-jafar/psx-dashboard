"""Quantitative signal engine: transparent points-based scoring, no black box.

Every stock gets points for income, valuation, payout safety, dividend record, position in its 52-week range, trend,
RSI, Bollinger position and support/resistance. Hard portfolio rules (position cap, sector cap, active risk notices)
can override the score. The score maps to one of five signals for stocks you hold, or four for stocks you don't.

This is rule-based decision support, NOT a price forecast. Thresholds live in config/settings.json ("rules" and
"signals") so you can tune them. Every point awarded is listed in `reasons` with the number behind it."""

HELD = ["Review/Exit", "Trim/Take Profit", "Hold", "Accumulate", "Strong Buy"]
UNHELD = ["Avoid", "Hold", "Accumulate", "Strong Buy"]
DEFAULTS = {"strong_buy": 4.0, "accumulate": 2.0, "trim": -1.5, "exit": -3.0}


SRC = {"yield": "PSX screener / your dividend input", "pe": "PSX screener / your EPS input", "payout": "your EPS and dividend inputs", "record": "PSX company page (payouts)",
       "range": "PSX company page (52-week range)", "support": "computed from PSX daily prices", "resistance": "computed from PSX daily prices",
       "trend": "computed from daily prices", "rsi": "computed from daily prices", "boll": "computed from daily prices", "triggers": "your watchlist triggers",
       "risk_notice": "PSX announcement", "cap": "your rules (settings.json)", "loss": "your cost and the price trend", "sector": "your rules (settings.json)",
       "shariah": "PSX KMI index list"}
NOTE_TXT = {"sma200": "200-day average not available yet: price history is still building (needs about 10 months)", "sma50": "50-day average needs about 3 months of history",
            "rsi": "RSI needs at least 15 days of price history", "dividend record": "Dividend history could not be read from the PSX company page",
            "yield": "No dividend yield available for this stock", "pe": "No valid P/E (PSX shows none for loss-making companies; add EPS to override)",
            "range": "52-week range not retrieved", "support": "Support level needs about 40 days of history"}
WARN_KEYS = {"sma200", "dividend record", "yield", "pe"}


def _f(x):
    try:
        return None if x in ("", None) else float(x)
    except (TypeError, ValueError):
        return None


def ladder(held):
    return HELD if held else UNHELD


def assess(r, tech, fund, anns, R, S=None, sector_pct=None, shariah=None):
    """r: enriched row (rules.enrich). tech: indicators.compute() or None. fund: fetcher.fundamentals() or None.
    anns: this ticker's recent announcements. R/S: rule and signal thresholds. Returns a dict (see bottom)."""
    S = {**DEFAULTS, **(S or {})}
    tech = tech or {}
    t, held = r["ticker"], (r.get("qty") or 0) > 0
    price, y, pe, pay = r.get("price"), r.get("yield_pct"), r.get("pe"), r.get("payout_pct")
    pe = pe if pe and pe > 0 else None
    rp, w, vs_avg = r.get("range_pos"), r.get("weight_pct"), r.get("vs_avg_pct")
    cap = R["max_stock_weight_pct"]
    reasons, flags, score = [], [], 0.0

    def add(key, pts, txt):
        nonlocal score
        score += pts
        reasons.append({"id": key, "pts": pts, "txt": txt, "src": SRC.get(key, "")})

    # --- income and valuation
    if y is not None:
        if y >= 7:
            add("yield", 2, f"Dividend yield {y:.1f}% is high")
        elif y >= R["opp_min_yield_pct"]:
            add("yield", 1, f"Dividend yield {y:.1f}% meets your {R['opp_min_yield_pct']}% goal")
        elif y < 2.5:
            add("yield", -1, f"Dividend yield only {y:.1f}%")
        else:
            add("yield", 0, f"Dividend yield {y:.1f}%")
    if pe is not None:
        if pe <= 6:
            add("pe", 2, f"P/E {pe:.1f} is very low")
        elif pe <= R["opp_max_pe"]:
            add("pe", 1, f"P/E {pe:.1f} is reasonable")
        elif pe > 25:
            add("pe", -2, f"P/E {pe:.1f} is expensive")
        elif pe > 15:
            add("pe", -1, f"P/E {pe:.1f} is above 15")
        else:
            add("pe", 0, f"P/E {pe:.1f}")
    if pay is not None:
        if pay > 100:
            add("payout", -2, f"Pays {pay:.0f}% of earnings as dividend, more than it earns")
        elif pay > R["high_payout_pct"]:
            add("payout", -1, f"Payout {pay:.0f}% of earnings leaves little cushion")
    n12 = (fund or {}).get("n_12m")
    if fund is not None and fund.get("payouts") is not None:
        if n12:
            add("record", 0.5, f"{n12} cash dividend announcement(s) in the last 12 months")
        elif fund.get("n_36m") == 0 and (fund.get("payouts") == [] ):
            add("record", -1, "No cash dividend found in the company page's payout history")
    # --- price position, trend, momentum
    if rp is not None:
        if rp <= 20:
            add("range", 1, f"Price sits in the bottom {rp:.0f}% of its 52-week range")
        elif rp >= R["trim_range_pos_pct"]:
            add("range", -1, f"Price is in the top {100 - rp:.0f}% of its 52-week range")
    sup, res = tech.get("support"), tech.get("resistance")
    if price and sup and 0 <= (price - sup) / sup * 100 <= 3:
        add("support", 0.5, f"Resting just above support near Rs {sup:,.1f}")
    if price and res and 0 <= (res - price) / price * 100 <= 2:
        add("resistance", -0.5, f"Pressing against resistance near Rs {res:,.1f}")
    tr = tech.get("trend")
    if tr == "up":
        add("trend", 1, "Uptrend: price above its 200-day average" if tech.get("sma200") else "Price above its 50-day average")
    elif tr == "down":
        add("trend", -1, "Downtrend: price below its 200-day average" if tech.get("sma200") else "Price below its 50-day average")
    rs = tech.get("rsi14")
    if rs is not None:
        if rs < 30:
            add("rsi", 1, f"RSI {rs:.0f} is oversold")
        elif rs > 70:
            add("rsi", -1, f"RSI {rs:.0f} is overbought")
    bb = tech.get("boll")
    if bb:
        if bb["pct_b"] < 0.1:
            add("boll", 0.5, "Price is at the lower Bollinger band")
        elif bb["pct_b"] > 0.95:
            add("boll", -0.5, "Price is at the upper Bollinger band")

    # --- watchlist triggers (your own entry rules)
    trig = []
    for key, label, tgt, now, ok in (
        ("entry", "Entry price", _f(r.get("entry_price")), price, lambda n, g: n <= g),
        ("yield", "Target yield", _f(r.get("target_yield")), y, lambda n, g: n >= g),
        ("pe", "Target P/E", _f(r.get("target_pe")), pe, lambda n, g: n <= g),
    ):
        if tgt is not None and not held:
            trig.append({"k": key, "label": label, "target": tgt, "now": now, "hit": bool(now is not None and ok(now, tgt))})
    if trig and all(x["hit"] for x in trig):
        add("triggers", 1.5, "All your watchlist triggers are met (" + ", ".join(x["label"].lower() for x in trig) + ")")
        flags.append("all_triggers")

    # --- map score to a signal
    n = ladder(held)
    if score >= S["strong_buy"]:
        sig = "Strong Buy"
    elif score >= S["accumulate"]:
        sig = "Accumulate"
    elif score > S["trim"]:
        sig = "Hold"
    elif score > S["exit"]:
        sig = "Trim/Take Profit" if held else "Avoid"
    else:
        sig = "Review/Exit" if held else "Avoid"

    # --- hard overrides: portfolio rules and risk notices
    risk = [a for a in anns or [] if a.get("category") == "Risk notice"]
    if risk:
        flags.append("risk_notice")
        sig = "Review/Exit" if held else "Avoid"
        reasons.append({"id": "risk_notice", "pts": 0, "txt": "Active PSX risk notice: " + risk[0]["title"][:120], "src": SRC["risk_notice"], "url": risk[0].get("url", "")})
    if held and w is not None and w > cap:
        flags.append("over_cap")
        if sig not in ("Review/Exit",):
            sig = "Trim/Take Profit"
        reasons.append({"id": "cap", "pts": 0, "txt": f"{w:.1f}% of the portfolio is above the {cap}% single-stock cap", "src": SRC["cap"]})
    elif held and w is not None and w >= cap - 1 and sig in ("Strong Buy", "Accumulate"):
        flags.append("near_cap")
        sig = "Hold"
        reasons.append({"id": "cap", "pts": 0, "txt": f"{w:.1f}% of the portfolio is already close to the {cap}% cap, so no more adding", "src": SRC["cap"]})
    if held and vs_avg is not None and vs_avg <= -R["below_avg_pct"] and tr == "down" and (y is None or y < R["trim_yield_below_pct"] + 1):
        flags.append("broken")
        sig = "Review/Exit"
        reasons.append({"id": "loss", "pts": 0, "txt": f"{abs(vs_avg):.0f}% below your cost, in a downtrend, without a strong yield", "src": SRC["loss"]})
    if sector_pct is not None and sector_pct > R["max_sector_weight_pct"] and sig in ("Strong Buy", "Accumulate"):
        flags.append("sector_cap")
        sig = "Hold"
        reasons.append({"id": "sector", "pts": 0, "txt": f"Sector already above the {R['max_sector_weight_pct']}% limit", "src": SRC["sector"]})
    if shariah is False:
        flags.append("not_kmi")
        reasons.append({"id": "shariah", "pts": 0, "txt": "Not found in the KMI All Share index list: check Shariah status before buying", "src": SRC["shariah"]})
        if sig in ("Strong Buy", "Accumulate") and not held:
            sig = "Hold"
    if sig not in n:   # unheld stocks never show held-only labels
        sig = "Avoid" if sig in ("Review/Exit", "Trim/Take Profit") else sig

    # --- how much data is behind it, and what to be careful about
    have = {"yield": y is not None, "pe": pe is not None, "range": rp is not None, "sma50": tech.get("sma50") is not None,
            "sma200": tech.get("sma200") is not None, "rsi": rs is not None, "dividend record": fund is not None, "support": sup is not None}
    missing = [k for k, v in have.items() if not v]
    conf = "High" if len(missing) <= 1 else "Medium" if len(missing) <= 3 else "Low"
    caveats = []
    if tech.get("mismatch"):
        caveats.append({"sev": "warn", "txt": "Price history does not match the live price, so technical indicators were ignored"})
    for k in missing:
        if k in NOTE_TXT and not (tech.get("mismatch") and k in ("sma50", "sma200", "rsi", "support")):
            caveats.append({"sev": "warn" if k in WARN_KEYS else "note", "txt": NOTE_TXT[k]})
    if "Yahoo" in str(tech.get("src", "")):
        caveats.append({"sev": "note", "txt": "Technicals use price history from Yahoo Finance (unofficial), not the PSX portal"})
    if r.get("dps") is None and y is not None:
        caveats.append({"sev": "note", "txt": "Yield is PSX's trailing 12-month figure, not a dividend input of yours"})
    if shariah is None:
        caveats.append({"sev": "note", "txt": "Shariah status unknown: the KMI index list was not retrieved"})
    if sig == "Strong Buy" and conf == "Low":
        sig = "Accumulate"
        flags.append("capped_data")
        caveats.append({"sev": "warn", "txt": "Capped at Accumulate: too little data behind this signal for Strong Buy"})
    quality = "Weak" if conf == "Low" else "Good" if conf == "High" and not any(c["sev"] == "warn" for c in caveats) else "Partial"

    top = sorted([x for x in reasons if x["pts"] != 0 or x["id"] in ("risk_notice", "cap", "loss", "sector")], key=lambda x: -abs(x["pts"]))[:3]
    summary = f"{t}: " + ("; ".join(x["txt"] for x in top) if top else "no strong factor either way") + f" → {sig}"
    facts = {"price": price, "yield_pct": y, "pe": pe, "payout_pct": pay, "range_pos_pct": rp, "weight_pct": w if held else None,
             "vs_your_cost_pct": vs_avg if held else None, "sma20": tech.get("sma20"), "sma50": tech.get("sma50"), "sma200": tech.get("sma200"),
             "rsi14": tech.get("rsi14"), "boll_pct_b": bb["pct_b"] if bb else None, "support": sup, "resistance": res, "trend": tr,
             "ret_1m_pct": tech.get("ret_1m"), "ret_3m_pct": tech.get("ret_3m"), "cash_dividends_12m": n12, "history_days": tech.get("n"),
             "day_change_pct": r.get("change_pct"), "kmi_member": shariah}
    return {"ticker": t, "held": held, "signal": sig, "score": round(score, 2), "confidence": conf, "missing": missing, "flags": flags,
            "reasons": reasons, "caveats": caveats, "quality": quality, "summary": summary, "triggers": trig, "facts": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in facts.items()}}


def audit_log(path, today, results):
    """Append today's signals to a small JSON log (one entry per ticker per day) so results can be reviewed later."""
    import json, os
    try:
        log = json.load(open(path))
    except Exception:
        log = {}
    for x in results:
        if x["facts"].get("price"):
            log.setdefault(x["ticker"], {})[today] = [x["signal"], x["facts"]["price"]]
    cutoff = sorted({d for v in log.values() for d in v})[-400:]
    keep = set(cutoff)
    log = {k: {d: v for d, v in days.items() if d in keep} for k, days in log.items()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(log, open(path, "w"), separators=(",", ":"))
    return log


def track_record(log, horizon=20):
    """For every logged signal at least `horizon` calendar-days old, compare the price then with the latest price.
    Returns {signal: {n, avg_return_pct, hit_pct}}. 'Hit' = price rose for buy-type signals, fell/flat for trim/exit/avoid."""
    import datetime as dt
    out = {}
    for tk, days in log.items():
        ds = sorted(days)
        if len(ds) < 2:
            continue
        last_d, last_p = ds[-1], days[ds[-1]][1]
        for d in ds[:-1]:
            if (dt.date.fromisoformat(last_d) - dt.date.fromisoformat(d)).days < horizon:
                continue
            sig, p0 = days[d]
            if not p0:
                continue
            ret = (last_p / p0 - 1) * 100
            o = out.setdefault(sig, {"n": 0, "sum": 0.0, "hit": 0})
            o["n"] += 1
            o["sum"] += ret
            o["hit"] += 1 if (ret > 0 if sig in ("Strong Buy", "Accumulate") else ret <= 0) else 0
    return {k: {"n": v["n"], "avg_return_pct": round(v["sum"] / v["n"], 1), "hit_pct": round(v["hit"] / v["n"] * 100)} for k, v in out.items() if v["n"]}
