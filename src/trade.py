"""Applies an encrypted portfolio update sent from the dashboard form (via a GitHub issue).
Never prints amounts or tickers: Actions logs and issue comments are public."""
import csv, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vault

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config")
H_COLS = "ticker,sector,tier,plan,qty,avg_cost,price,change_pct,price_time,low52,high52,eps,dps".split(",")
W_COLS = "ticker,sector,price,change_pct,price_time,low52,high52,eps,dps,note".split(",")
TICK = re.compile(r"^[A-Z0-9]{2,8}$")


def bucket(psx_sector):
    s = (psx_sector or "").upper()
    for key, name in (("EXPLORATION", "Oil & gas"), ("FERTILIZER", "Fertilizer"), ("CEMENT", "Cement"),
                      ("BANK", "Banking"), ("PHARMA", "Pharma"), ("POWER", "Power")):
        if key in s:
            return name
    return "Growth/other"


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def read(path, cols):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [{c: r.get(c, "") for c in cols} for r in csv.DictReader(fh)]


def write(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def apply_ops(ops, H, W, market):
    """Pure function: returns (H, W, error_or_None). All-or-nothing."""
    H, W = [dict(r) for r in H], [dict(r) for r in W]
    if not isinstance(ops, list) or not ops or len(ops) > 40:
        return H, W, "no valid changes found"
    for op in ops:
        kind, t = str(op.get("op", "")), str(op.get("t", "")).upper().strip()
        if not TICK.match(t):
            return H, W, "a ticker symbol is not valid"
        row = next((r for r in H if r["ticker"] == t), None)
        info = market.get(t) if market else None
        if kind in ("buy", "sell", "set"):
            q, p = _f(op.get("q")), _f(op.get("p"))
            if kind != "set" and not (q and q > 0) or p is None or p <= 0 or q is None or q < 0 or q > 1e7 or p > 1e5:
                return H, W, "a share count or price is not valid"
            if kind == "buy":
                if row is None:
                    if not info:
                        return H, W, "a ticker could not be checked on PSX"
                    row = {c: "" for c in H_COLS}
                    row.update(ticker=t, sector=bucket(info.get("sector")), tier="Medium", plan="new", qty="0", avg_cost="0")
                    H.append(row)
                oq, oa = _f(row["qty"]) or 0, _f(row["avg_cost"]) or 0
                nq = oq + q
                row["qty"] = str(int(nq) if nq == int(nq) else nq)
                row["avg_cost"] = f"{(oq * oa + q * p) / nq:.2f}"
                W[:] = [w for w in W if w["ticker"] != t]
            elif kind == "sell":
                if row is None or (_f(row["qty"]) or 0) < q:
                    return H, W, "you do not hold enough shares to sell"
                nq = (_f(row["qty"]) or 0) - q
                row["qty"] = str(int(nq) if nq == int(nq) else nq)
                if nq == 0 and row.get("plan") == "sell":
                    H.remove(row)
            else:  # set: correct a position
                if row is None:
                    if not info:
                        return H, W, "a ticker could not be checked on PSX"
                    row = {c: "" for c in H_COLS}
                    row.update(ticker=t, sector=bucket(info.get("sector")), tier="Medium", plan="new")
                    H.append(row)
                row["qty"], row["avg_cost"] = str(int(q) if q == int(q) else q), f"{p:.2f}"
        elif kind == "watch_add":
            if row is not None or any(w["ticker"] == t for w in W):
                continue
            if not info:
                return H, W, "a ticker could not be checked on PSX"
            W.append({**{c: "" for c in W_COLS}, "ticker": t, "sector": bucket(info.get("sector")), "note": "added from dashboard"})
        elif kind == "watch_remove":
            W[:] = [w for w in W if w["ticker"] != t]
        else:
            return H, W, "unknown action"
    return H, W, None


def main():
    pw = os.getenv("HOLDINGS_KEY", "")
    result = os.path.join(ROOT, "result.txt")
    try:
        payload = json.loads(vault.decrypt(os.getenv("ISSUE_BODY", ""), pw))
        ops = payload.get("ops")
    except Exception:
        open(result, "w").write("Rejected: could not decrypt this update. Check that the passphrase in the form matches the HOLDINGS_KEY secret.")
        return
    H = read(os.path.join(CFG, "holdings.csv"), H_COLS)
    W = read(os.path.join(CFG, "watchlist.csv"), W_COLS)
    market = {}
    try:
        import fetch
        market = fetch.market_watch()
    except Exception:
        pass
    H2, W2, err = apply_ops(ops, H, W, market)
    if err:
        open(result, "w").write(f"Rejected: {err}. Nothing was changed.")
        return
    write(os.path.join(CFG, "holdings.csv"), H_COLS, H2)
    write(os.path.join(CFG, "watchlist.csv"), W_COLS, W2)
    open(os.path.join(ROOT, ".changed"), "w").write("1")
    open(result, "w").write(f"Applied {len(ops)} change(s). The dashboard is rebuilding.")


if __name__ == "__main__":
    main()
