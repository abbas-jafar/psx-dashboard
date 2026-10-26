# PSX Portfolio Dashboard

Personal, Shariah/dividend-focused PSX dashboard. Fetches prices, announcements, news and price history, applies your rules, and publishes one web page (GitHub Pages). Refreshes itself every 30 minutes during market hours and at 3:45 PM Pakistan time.

## Secrets and variables (repository Settings > Secrets and variables > Actions)
| Name | Type | What |
|---|---|---|
| `HOLDINGS_CSV` | secret | Your holdings file contents (only needed for the first run) |
| `HOLDINGS_KEY` | secret | A long passphrase you invent (20+ characters). Encrypts your holdings and the update form |
| `NTFY_TOPIC` | secret | Your private ntfy topic name (phone alerts) |
| `EMAIL_USER` | secret | Your Gmail address |
| `EMAIL_APP_PASSWORD` | secret | Google App Password, no spaces |
| `DASH_URL` | variable | Your page address, so tapping a notification opens it |

## Daily use
- Open your page address. It refreshes by itself.
- **Refresh now:** Actions tab > "Refresh PSX dashboard" > Run workflow. Tick "Also send a test notification" to test alerts.
- **Bought or sold?** Use "Update my portfolio" on the page. The details are encrypted in your browser; GitHub applies them and rebuilds the page.
- **Watchlist:** same form ("WATCH ADD LUCK MTL PSO").

## Privacy
Holdings are stored encrypted (`config/holdings.enc`, AES-256-GCM). Choose a strong `HOLDINGS_KEY`: anyone can download that file, and only the passphrase protects it. The public page shows percentages, not rupee amounts or share counts (`show_rs_amounts` in `config/settings.json`). Update issues contain only encrypted text, and only the repository owner's issues are processed. Never put AKD login details anywhere.

## Files you can edit
`config/watchlist.csv` (also editable from the page), `config/sector_targets.csv`, `config/settings.json` (rules, news searches, `github_repo`).

## Local checks
```
pip install -r requirements.txt
python src/main.py --selftest   # which PSX feeds answer from your machine
python src/main.py --offline    # builds docs/index.html from saved prices
```

## Limits
GitHub's scheduler can run late or skip. Feeds are scraped from public PSX pages and can break if PSX changes them. Price history is gathered a few months at a time and fills in over a day or two. Not investment advice.
