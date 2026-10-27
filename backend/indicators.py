"""Technical indicators computed from the daily history files in docs/history/<SYM>.json.
Pure maths on prices: no network, no guessing. Each value is None when there is not enough history yet
(the 200-day average needs about 10 months of data, which the history feed backfills over a few days)."""
import datetime as dt, json, os


def load_rows(hist_dir, sym):
    """[[yyyymmdd, close, high, low, volume], ...] sorted by date, or []."""
    try:
        with open(os.path.join(hist_dir, sym + ".json")) as fh:
            rows = json.load(fh).get("rows", [])
    except Exception:
        return []
    return sorted((r for r in rows if len(r) >= 2 and r[1]), key=lambda r: r[0])


def load_src(hist_dir, sym):
    try:
        with open(os.path.join(hist_dir, sym + ".json")) as fh:
            return json.load(fh).get("src") or ""
    except Exception:
        return ""


def sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def rsi(vals, n=14):
    """Wilder's RSI."""
    if len(vals) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = vals[i] - vals[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(vals)):
        d = vals[i] - vals[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def bollinger(vals, n=20, k=2.0):
    if len(vals) < n:
        return None
    w = vals[-n:]
    mid = sum(w) / n
    sd = (sum((x - mid) ** 2 for x in w) / n) ** 0.5
    up, lo = mid + k * sd, mid - k * sd
    pctb = (vals[-1] - lo) / (up - lo) if up > lo else 0.5
    return {"mid": mid, "upper": up, "lower": lo, "pct_b": pctb, "width_pct": (up - lo) / mid * 100 if mid else None}


def support_resistance(rows, price, lookback=180, win=4):
    """Nearest swing-low below the price and swing-high above it, from the last `lookback` sessions.
    A swing point is the lowest/highest value within `win` sessions on each side. Uses daily lows/highs when present."""
    rows = rows[-lookback:]
    lows = [r[3] if len(r) > 3 and r[3] else r[1] for r in rows]
    highs = [r[2] if len(r) > 2 and r[2] else r[1] for r in rows]
    sup, res = [], []
    for i in range(win, len(rows) - win):
        if lows[i] == min(lows[i - win:i + win + 1]):
            sup.append(lows[i])
        if highs[i] == max(highs[i - win:i + win + 1]):
            res.append(highs[i])
    below = [x for x in sup if x < price]
    above = [x for x in res if x > price]
    if not rows:
        return None, None
    support = max(below) if below else min(lows)
    resistance = min(above) if above else max(highs)
    return (support if support < price else None), (resistance if resistance > price else None)


def compute(rows, price=None, today=None):
    """All indicators for one stock. If a live price is given it is used as today's latest close."""
    today = today or dt.date.today()
    closes = [r[1] for r in rows]
    dates = [r[0] for r in rows]
    if price and closes and abs(price / closes[-1] - 1) > 0.35:
        # history and live price disagree by more than a limit-up/limit-down week could explain: wrong symbol, split or bad data
        return {"n": 0, "mismatch": True, "sma20": None, "sma50": None, "sma200": None, "rsi14": None, "boll": None, "support": None,
                "resistance": None, "trend": None, "vol_ratio": None, "ret_1m": None, "ret_3m": None}
    if price:
        tnum = int(today.strftime("%Y%m%d"))
        if dates and dates[-1] == tnum:
            closes[-1] = price
        else:
            closes.append(price)
            dates.append(tnum)
    n = len(closes)
    out = {"n": n, "sma20": sma(closes, 20), "sma50": sma(closes, 50), "sma200": sma(closes, 200), "rsi14": rsi(closes, 14),
           "boll": bollinger(closes, 20), "support": None, "resistance": None, "trend": None, "vol_ratio": None, "ret_1m": None, "ret_3m": None}
    last = closes[-1] if closes else None
    if n >= 30 and last:
        out["support"], out["resistance"] = support_resistance(rows if not price else rows, last)
    if n > 21 and last:
        out["ret_1m"] = (last / closes[-22] - 1) * 100
    if n > 63 and last:
        out["ret_3m"] = (last / closes[-64] - 1) * 100
    s50, s200 = out["sma50"], out["sma200"]
    if last and s50 and s200:
        out["trend"] = "up" if last > s200 and s50 > s200 else "down" if last < s200 and s50 < s200 else "mixed"
    elif last and s50:
        out["trend"] = "up" if last > s50 else "down"
    vols = [r[4] for r in rows if len(r) > 4 and r[4]]
    if len(vols) >= 25:
        out["vol_ratio"] = (sum(vols[-5:]) / 5) / (sum(vols[-25:-5]) / 20) if sum(vols[-25:-5]) else None
    return out
