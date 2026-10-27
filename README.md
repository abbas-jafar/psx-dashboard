# PSX Intelligence Dashboard

Personal, Shariah-aware, dividend-focused PSX dashboard. A scheduled GitHub job collects official PSX data, computes technical and fundamental signals, optionally asks an AI analyst to check them against recent filings and headlines, then publishes one web page and sends phone/email alerts. No server and no database: GitHub Actions + GitHub Pages.

## Architecture

```
GitHub Actions (cron every 30 min in market hours, 15:45 PKT daily report, or "Run workflow")
        |
        v
backend/fetcher.py     PSX portal: prices (screener), indices (KSE-100 / KMI-30 / KSE-30), KMI constituent lists,
                       company pages (52-week range, filings, EPS + payout history), FIPI/LIPI flows (optional),
                       OFFICIAL releases only (SBP, SECP, Finance Ministry, FBR, PBS, OGRA, NEPRA) with dedupe; no media headlines
backend/history.py     daily OHLCV per stock -> docs/history/<SYM>.json. PSX history page first; Yahoo Finance (UNOFFICIAL, clearly labelled)
                       as fallback/backfill, 10 years in one request
backend/indicators.py  SMA 20/50/200, RSI(14), Bollinger bands, support/resistance, trend, returns
backend/rules.py       portfolio maths: weights, P/L, yield, P/E, payout, sector mix, alert rules
backend/signals.py     transparent points-based score -> Strong Buy / Accumulate / Hold / Trim-Take Profit / Review-Exit
                       (+ your hard rules: 12% stock cap, 25% sector cap, risk notices, Shariah list)
backend/ai_agent.py    AI analyst via function calling -> structured JSON, validated in code, may move a signal ONE step
backend/notify.py      ntfy (phone) + Gmail (email)
backend/trade.py       applies encrypted "I bought / sold / watch" updates from the page form
backend/vault.py       AES-256-GCM encryption of your holdings (config/holdings.enc)
backend/main.py        orchestrator -> docs/index.html (+ docs/ai.json, docs/state.json, docs/signals_log.json)
frontend/index.template.html   the page: status tags, Needs Attention, AI Opportunities, Holdings | Watchlist tabs
tests/                 unit tests + a no-internet dry run
```

## What the signals are (and are not)
* **Rule-based, explainable.** Points for yield, P/E, payout safety, dividend record, 52-week position, trend (200-day average), RSI, Bollinger band, support/resistance. Every point is listed under the signal (tap it on the page). Thresholds: `rules` and `signals` in `config/settings.json`.
* **Hard overrides.** A stock above your cap becomes Trim; an active PSX risk notice becomes Review/Exit; 15%+ under your cost in a downtrend without a strong yield becomes Review/Exit; a stock outside the KMI All Share list is not upgraded to a buy.
* **Not a forecast.** Nothing here predicts prices. Signals have not been back-tested. Each signal is logged daily in `docs/signals_log.json` and the page shows a track record after 20 days.
* **AI layer.** Reads the facts, recent company filings and headlines and returns structured JSON. It can agree, or move a signal one step with at least two cited pieces of evidence. It cannot change stocks that are over the cap or have a risk notice. Only percentages are sent, never share counts or rupee values. Without an API key the layer is off and rule-based signals stand alone.

## Secrets and variables (repository Settings > Secrets and variables > Actions)
| Name | Type | What |
|---|---|---|
| `HOLDINGS_CSV` | secret | Holdings file contents (first run only) |
| `HOLDINGS_KEY` | secret | Long passphrase (20+ characters). Encrypts holdings and the update form |
| `NTFY_TOPIC` | secret | Private ntfy topic (phone alerts) |
| `EMAIL_USER`, `EMAIL_APP_PASSWORD` | secret | Gmail address and Google App Password (no spaces) |
| `ANTHROPIC_API_KEY` | secret | **New, optional.** Switches the AI analyst on. Create at console.anthropic.com (separate from a Claude subscription, prepaid credit) |
| `DASH_URL` | variable | Your page address |

## Daily use
* Open your page. **Refresh data now** = Actions > "Refresh PSX dashboard" > Run workflow. Tick *Run the AI analyst now* to refresh AI opinions on demand (otherwise they refresh with the 15:45 report).
* **Bought or sold?** "Update my portfolio" on the page (encrypted in your browser).
* **Watchlist triggers:** Watchlist tab > "Set watchlist triggers" (buy at or below, yield at least, P/E at most), or a line such as `WATCH SET LUCK entry=360 yield=5 pe=8`.

## Optional settings (add to config/settings.json)
```
"signals": {"strong_buy": 4, "accumulate": 2, "trim": -1.5, "exit": -3},
"ai": {"enabled": true, "model": "claude-sonnet-5-5", "max_tokens": 8000},
"flows_urls": ["https://www.nccpl.com.pk/market-information/fipi-lipi"]
```
Optional watchlist/holdings column `bvps` (book value per share) enables P/B.

## Checks
```
pip install -r requirements.txt
python -m unittest discover -s tests -v   # 24 offline tests
python tests/dry_run.py                   # full pipeline with fake data -> demo_docs/index.html
python backend/main.py --selftest         # which live feeds answer from your machine
```

## Privacy
Holdings are stored encrypted (`config/holdings.enc`). The public page shows percentages, not rupees or share counts. Update issues contain only encrypted text and only the repository owner's are processed. `docs/ai.json` and `docs/signals_log.json` are public like the page. Never put AKD login details anywhere.

## Limits
GitHub's scheduler can run late or skip. PSX pages are scraped and can change. Items marked UNVERIFIED in `backend/fetcher.py` (fundamentals tables, KMI lists, FIPI/LIPI) were written without live access and report their status on the page. Not investment advice.

## Quality rules for signals (v5)
* Every reason lists its data source, every AI claim cites evidence IDs that resolve to links (PSX company page, the filing, the official release).
* **Flags are always shown.** A signal with missing or weak data carries a ⚑ and a plain-language list of limits (for example "200-day average not available yet", "history from Yahoo Finance (unofficial)", "AI opinion out of date"). Quality is labelled Good / Partial / Weak. A Strong Buy with Low confidence is capped to Accumulate.
* History that disagrees with the live price by more than 35% is ignored (wrong symbol, split or bad data).
* Alerts: Critical (risk notice, broken position, prices not updating) / Important (caps, trim) / Heads-up (new filing for a holding, AI warning, lowered signal).

## Notifications not arriving?
Actions > **Test notifications** > Run workflow. Its log says which secret is missing (NTFY_TOPIC, EMAIL_USER, EMAIL_APP_PASSWORD) or what Gmail/ntfy rejected, and it turns red if any configured channel fails. Phone: subscribe the ntfy app to exactly the same topic. Email: check Spam.

## Your buy prices on the page
The public page never contains buy prices or share counts in plain text. They are embedded encrypted; type your passphrase above the holdings table ("Unlock my numbers") and the page shows Avg cost, Shares and Value on that device only.
