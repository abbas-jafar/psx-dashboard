import json, os

PRIVATE_KEYS = ("qty", "avg_cost", "value", "cost", "pl", "day_change")


def scrub(d):
    d = json.loads(json.dumps(d))
    if d.get("show_rs"):
        return d
    for r in d["holdings"] + d["watchlist"]:
        r["held"] = (r.get("qty") or 0) > 0
        for k in PRIVATE_KEYS:
            r.pop(k, None)
    for k in ("value", "cost", "pl", "day_change"):
        d["totals"].pop(k, None)
    return d


def write(docs, data):
    os.makedirs(docs, exist_ok=True)
    payload = json.dumps(scrub(data)).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", data["title"])
    with open(os.path.join(docs, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)


TEMPLATE = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "index.template.html"), encoding="utf-8").read()
