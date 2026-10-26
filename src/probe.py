"""Tries candidate PSX addresses and writes what comes back to docs/probe.txt (for debugging feeds)."""
import re, sys, os, requests
H = {"User-Agent": "Mozilla/5.0 (personal PSX dashboard)"}
B = "https://dps.psx.com.pk"
GET = ["/market-watch", "/market-summary", "/indices", "/indices/KSE100", "/timeseries/int/KSE100", "/timeseries/eod/KSE100",
       "/timeseries/int/OGDC", "/timeseries/eod/OGDC", "/company/OGDC", "/announcements/companies", "/announcements", "/", "/data/KSE100",
       "/trading-panel", "/screener"]
POST = [("/announcements/companies", {"type": "C", "symbol": "", "query": "", "count": 50, "offset": 0, "page": "annc"}),
        ("/announcements", {"type": "C", "symbol": "", "query": "", "count": 50, "offset": 0, "page": "annc"})]
out = []
def show(label, r):
    t = re.sub(r"\s+", " ", r.text)[:350]
    heads = re.findall(r"<th[^>]*>(.*?)</th>", r.text, re.S | re.I)[:14]
    out.append(f"{label} -> {r.status_code} {r.headers.get('content-type','')} len={len(r.text)}\n  start: {t}\n  th: {[re.sub('<.*?>','',h).strip() for h in heads]}\n")
for p in GET:
    try:
        show("GET " + p, requests.get(B + p, headers=H, timeout=25))
    except Exception as e:
        out.append(f"GET {p} -> ERROR {e}\n")
for p, d in POST:
    try:
        show("POST " + p, requests.post(B + p, data=d, headers=H, timeout=25))
    except Exception as e:
        out.append(f"POST {p} -> ERROR {e}\n")
os.makedirs("docs", exist_ok=True)
open("docs/probe.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out)[:3000])
