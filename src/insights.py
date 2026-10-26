"""Turns raw headlines into a short list of key findings. Rule-based: always read the source for detail."""
import re
from collections import Counter


def key_points(news, index=None):
    pts, used = [], set()
    pol = [n for n in news if re.search(r"policy rate|interest rate|key rate|monetary policy|SBP|State Bank", n["title"], re.I)]
    if pol:
        txt = " ".join(n["title"] for n in pol)
        act = Counter()
        for n in pol:
            t = n["title"].lower()
            for word, label in (("rais|hike|jack|increas", "raised"), ("cut|reduc|slash", "cut"), ("retain|keep|unchanged|maintain|status quo", "kept")):
                if re.search(word, t):
                    act[label] += 1
        rates = Counter(re.findall(r"(\d{1,2}(?:\.\d+)?)\s*(?:%|pc|percent)", txt))
        bps = Counter(re.findall(r"(\d{2,3})\s*(?:bps|basis points)", txt, re.I))
        if act:
            a = act.most_common(1)[0][0]
            line = f"SBP {a} the policy rate"
            if bps and a != "kept":
                line += f" by {bps.most_common(1)[0][0]} basis points"
            if rates:
                line += f" (to {rates.most_common(1)[0][0]}%)"
            pts.append((line + f". Reported by {len(pol)} headlines. Banks and rate-sensitive stocks usually react; read the statement for the inflation outlook.", pol[0]["url"]))
            used.update(n["title"] for n in pol)
    mk = [n for n in news if re.search(r"PSX|KSE|bourse|stocks?\b", n["title"], re.I) and n["title"] not in used]
    if mk:
        pts.append(("Market: " + mk[0]["title"], mk[0]["url"]))
        used.add(mk[0]["title"])
    if index and index.get("change_pct") is not None:
        pts.append((f"KSE-100 at {index['level']:,.0f} ({index['change_pct']:+.2f}% today).", ""))
    for topic in dict.fromkeys(n["topic"] for n in news):
        first = next((n for n in news if n["topic"] == topic and n["title"] not in used), None)
        if first:
            pts.append((first["title"], first["url"]))
            used.add(first["title"])
    return [{"text": t, "url": u} for t, u in pts[:6]]
