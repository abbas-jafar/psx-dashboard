# My PSX dashboard

A personal, Shariah/dividend-focused PSX dashboard. It fetches prices and announcements, applies your rules,
and publishes one web page. No Claude needed once it is running.

## Files you edit
- `config/holdings.csv` - your stocks: ticker, sector, tier, plan, qty, avg_cost, plus eps and dps (latest full-year). Keep qty 0 for planned buys.
- `config/watchlist.csv` - stocks you are studying (same columns, no qty). Add rows any time.
- `config/sector_targets.csv`, `config/settings.json` - sector targets, rule thresholds, news searches.

## 1. Check that the data feeds work (do this first)
```
pip install -r requirements.txt
python src/main.py --selftest      # shows which PSX feeds answer from your machine
python src/main.py --no-notify     # builds docs/index.html with live data; open it in a browser
python src/main.py --offline       # builds from the saved CSV prices, no network
```
The PSX endpoints were written from the public portal's structure and could not be tested when this was built. If a line says FAIL, send me the message and I will fix that fetcher.

## 2. Publish it online (free)
1. Make a GitHub repository and push this folder. `config/holdings.csv` is git-ignored on purpose, so your quantities and costs are not published.
2. Repo Settings > Secrets and variables > Actions > New secret `HOLDINGS_CSV`: paste the full contents of your `config/holdings.csv`.
3. Settings > Pages > Source: branch `main`, folder `/docs`. Your dashboard is at `https://<user>.github.io/<repo>/`.
4. Actions tab > "Refresh PSX dashboard" > Run workflow. It then runs every 30 minutes from 09:00 to 14:30 PKT and at 15:45 PKT on weekdays.
By default the page shows percentages only, no rupee amounts or quantities (`show_rs_amounts: false`). Public repos and Pages are visible to anyone with the link.

## 3. Phone and email alerts
Add these Actions secrets: `NTFY_TOPIC` (a long random topic name; install the free ntfy app and subscribe to it), `EMAIL_USER` (your Gmail), `EMAIL_APP_PASSWORD` (a Google App Password, not your real password), optional `EMAIL_TO`. Add a repository variable `DASH_URL` with your page link so a tap on the notification opens it.
Alerts are sent once per rule per day. The 15:45 run always sends a summary.

## Limits
- GitHub's scheduler can run several minutes late or skip a run. It is not tick-by-tick.
- If PSX blocks GitHub's servers, run `python src/main.py` on your own computer (cron / Task Scheduler) or on a small always-on machine and publish `docs/` anywhere.
- Never put your AKD login, PIN or CNIC anywhere in this project.
