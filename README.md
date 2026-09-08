# Stock agent — $400/week, runs all day, buys and sells, follows Congress + insiders + news, learns which signals work

## Start here: SIM mode (the safety lock)

Out of the box the agent trades a **pretend $400 portfolio** (`BROKER=sim`). Real prices, real
signals, real decisions — fake money. It buys and sells, tracks every position's weight and profit,
books realised P/L, and rewrites **`portfolio.md`** after every check so you can see exactly what it
would have done with your money. Every Monday it adds another pretend $400, mirroring the real plan
(`sim.weekly_deposit` in `config.yaml`; set it to 0 for a one-time $400 test).

Run it this way for a few weeks. If `portfolio.md` looks like something you'd trust, switch brokers.
No Alpaca account is needed for SIM mode — only the Anthropic key (and the free Financial Modeling
Prep key if you want the Congress + insider feeds).

Three pieces:
1. **`portfolio-board.html`** — the phone dashboard (already built). Add to home screen.
2. **`agent/`** — runs every 30 minutes while the US market is open. At each check it gathers prices, headlines, Congress disclosures and SEC insider filings, asks Claude whether to deploy any of the week's $400 right now and into what, and places fractional buys on Alpaca. Every buy must cite evidence. Whatever's left gets deployed Friday afternoon.
3. **Guardrails** in `config.yaml` that the AI cannot override (max per ticker, max per day, max orders and sells per day, minimum hold before selling, no same-day sell-and-rebuy, min order).

## Accounts you need (in this order)

| # | Account | Why | Cost | Link |
|---|---------|-----|------|------|
| 1 | **Anthropic API** | The decision brain. The only key SIM mode needs. | Pay-as-you-go, cents per check | console.anthropic.com → API keys |
| 2 | **Financial Modeling Prep** (free) | SEC insider filings (Form 4). Its Congress endpoints need a paid plan; the agent falls back to the free public-records feed below. | Free | financialmodelingprep.com |
| 3 | **GitHub** (free) | Runs the agent on a schedule so your laptop doesn't have to be open (or use `autopilot-mac.command`) | Free | github.com |
| 4 | **Alpaca** — paper trading (later) | A real brokerage sandbox: fake $100k, real order routing. Only when you move past SIM. Set `BROKER=alpaca`. | Free | alpaca.markets → Paper trading → Generate API keys |

## Canada notes (you're in BC)
- **Paper on Alpaca works from Canada** — no residency check. Live Alpaca accounts don't accept Canadian residents, so real money goes through **IBKR Canada** instead: set `BROKER=ibkr` in `.env` and run IB Gateway on your Mac. The agent already has the adapter (`agent/broker_ibkr.py`). Autopilot then has to run on your Mac (cron), not GitHub, because the Gateway is local.
- **Age:** BC's age of majority is 19. IBKR Canada, Questrade and Wealthsimple all go by that; a TFSA also can't be opened in BC until 19 (room still accrues from 18). Check each brokerage yourself — this may mean paper until your birthday, or an account in a parent's name.
- **Currency:** everything on the watchlist is US-listed, so a live account will convert CAD→USD (IBKR's conversion is cheap; most others charge ~1.5%). Fund in USD once a week to avoid repeat fees.
- **Taxes:** file a W-8BEN with the brokerage so US dividends are withheld at 15%, not 30%. Gains are taxable in Canada in a non-registered account.
- **Canadian politicians:** MPs don't file per-trade disclosures, so there's no Canadian equivalent of the STOCK Act feed. The agent tracks US Congress only.

**Real money later (recap):** Alpaca live accounts need US/eligible residency, and Canadian brokerages (IBKR, Questrade, Wealthsimple) generally require the age of majority — **19 in BC**. Options until then: run paper, or open the live account in a parent's name. Verify this yourself; I'm not a financial advisor and this is not advice.

## Safety

Checks that sit outside the brain's reach. It cannot argue its way past any of them.

| Guard | What it does |
|---|---|
| `PAUSE` file / `pause.command` / **control workflow** | Kill switch. While the file exists the agent will not trade (it keeps publishing, so the site says PAUSED). From any device: github.com → Actions → **control** → Run workflow → pause / resume. On the Mac, double-click `pause.command`. |
| Ledger integrity | Before every check: cash + cost basis must equal money put in + realised P/L. On mismatch it refuses to trade and says so. |
| Circuit breaker | `max_drawdown_pct` (30%). If equity falls that far below the money put in, no new buys. |
| Bad-tick filter | `max_daily_move_pct` (35%). A quote that moved more than that in a day is treated as a bad tick and ignored. |
| `check.command` | Health check: keys, feeds, prices, calendar, ledger, schedule, disk. Changes nothing, exits non-zero if broken. |

## Backtester

`python -m agent.backtest` replays real daily prices over 2-year and 5-year windows, deploying the
weekly budget under the live guardrails, and compares the signal rules (momentum, contrarian, sector
rotation, ETF-default, equal weight) against buy-and-hold SPY. It writes `backtest.md` for you and
`backtest.json`, whose summary is handed to the brain each check as `backtest_priors`.

Read the caveats it prints. Two matter most: the winning strategy **flips between windows**, and the
watchlist itself was chosen in 2026 already knowing which themes had run, so "vs SPY" is hindsight,
not edge. The agent is told to treat it as a weak prior and never as a rule.

## Fastest setup (Mac, double-click)
1. `setup.command` — installs, asks for keys (Anthropic required, rest optional), writes `.env` with `BROKER=sim`, runs a check
2. `run.command` — one check, right now, during market hours. Read `log.md` and `portfolio.md`.
3. `autopilot-mac.command` — this Mac runs a check every 30 min during market hours while awake.
   `check.command` — health check any time. `pause.command` — stop/resume trading.
   `keep-awake-mac.command` — stops the Mac sleeping 6:25 AM–1:05 PM Pacific while plugged in (a sleeping Mac skips checks). Or:
4. `push.command` — autopilot on GitHub, laptop can be closed (logs in to GitHub in your browser)
5. Later, for Alpaca paper: set `BROKER=alpaca` in `.env`; `go-live.command` turns DRY_RUN off so paper orders get placed

If macOS blocks a .command file: right-click → Open, or System Settings → Privacy & Security → Open Anyway.

## Manual setup
```bash
cp .env.example .env      # paste your keys in
pip install -r requirements.txt
python -m agent.run --report   # sanity check: prints positions + budget
python -m agent.run            # one check in SIM mode: decides, fills at real prices into the pretend portfolio
python -m agent.run --force    # same, ignoring the market-hours gate (testing)
```
`DRY_RUN` and `ALPACA_PAPER` only matter once `BROKER=alpaca`. Only flip `ALPACA_PAPER=false` when you have a live account and want real money at risk.

## Running it automatically

> **Read [TRIGGER.md](TRIGGER.md) first.** GitHub's scheduler did not fire for this repo on day one.
> The agent works; waking it up is the fragile part, and TRIGGER.md sets up a second, independent alarm clock.

**GitHub Actions (recommended):** push this folder to a private repo, add each `.env` value under Settings → Secrets → Actions, done. `.github/workflows/agent.yml` runs it **every 30 minutes (at :02 and :32), 9:00 AM–5:30 PM New York, Mon–Fri** and commits `state.json`, `log.md`, `journal.json`, `decisions.json` and `lessons.md` back so you can read what it did from your phone. Off-hours slots exit in seconds. `watchdog.yml` runs at :17/:47 and dispatches a check itself if GitHub dropped a slot while the market was open, so nothing ever needs a manual start. `control.yml` is the stop/start switch (Actions → control → Run workflow → pause or resume). Roughly 14 real checks a day; GitHub's free tier covers it, and each check costs a few cents of Anthropic API. Commits must be authored by the GitHub account that owns the Vercel project or Vercel's Hobby plan blocks the deploy.

**Or on your Mac:** `crontab -e` → `*/30 6-13 * * 1-5 cd "$HOME/Desktop/AI Trader/stock-agent" && /opt/homebrew/bin/python3 -m agent.run` (6:30 AM–1:00 PM Pacific = market hours). Laptop must be awake. This is the only option once `BROKER=ibkr`, because IB Gateway is local.

`run_every_minutes` in `config.yaml` must match the schedule — the brain uses it to know how many checks it has left today.

## Same-day trading

The agent may open and close a position on the same day (`min_hold_days: 0`). Three things make that
work rather than just being permitted:

- **Every position gets an exit plan the moment it exists.** `auto_bracket` attaches a target and a
  stop to any position that lacks one, priced off the actual entry. The brain can place better levels
  itself; these only fill the gaps it left.
- **A fast tick between decisions.** `.github/workflows/tick.yml` starts every 5 minutes (GitHub's
  cron floor) and each job then watches minute by minute, firing any standing order whose level was
  reached. Reaction time is about a minute. It never calls the model, so it costs nothing in API,
  and the repo is public so runner minutes are free. The half-hourly `agent.yml` does the thinking.
  A tick only publishes when something changed, because every publish is a site deploy and Vercel's
  free plan allows 100 a day.
- **Sold money is immediately reusable.** Proceeds return to the week's budget, so an exit funds the
  next entry in the same session.

Trading is not free here: `spread_cost_pct` makes every market fill worse than the quote on both
sides, so a round trip costs about 4bp and a rotation has to beat that to be worth doing.

**A real-money caveat that does not apply in SIM.** In a US margin account, four or more day trades
in five business days makes you a pattern day trader, which requires $25,000 of equity. A cash
account avoids that rule but can only buy with settled funds, so a small balance can only be
recycled so often. Neither limit exists in the simulator, which means SIM results will overstate how
many round trips a real $400 account could actually make.

## Standing orders (why it isn't tied to the clock)

The brain is only asked every 30 minutes, but the market moves the whole time. If it only ever acted at the
moment it was asked, every fill would land at an arbitrary clock tick. So it can leave **standing orders** that
fire between checks at a price it chose in advance:

| Kind | Fires when |
|---|---|
| `buy_limit` | it falls to your level (accumulate on a dip) |
| `buy_stop` | it rises through your level (confirmation) |
| `take_profit` | it rises to your level (bank a gain) |
| `stop_loss` | it falls to your level (cap a loss) |
| `trailing_stop` | it falls N% from its high since the order was placed |

Each check replays the intraday bars it missed, so an order whose level was touched at 10:47 fills at 10:47 at
its own price. Stop orders take a small adverse slippage (`trigger_slippage_pct`) because a real stop becomes a
market order the moment it triggers. Stop-losses and trailing stops are exempt from `min_hold_days` — they are
protection, not churn — and every fill still passes the ordinary dollar caps and the ordinary ledger. The
working book is on the dashboard under **Waiting to fire**, and the levels are drawn on the full-screen chart.

## What the agent does at each check
1. Loads this week's budget, what's spent this week, what's spent today and how many orders today (`state.json`).
2. Pulls watchlist prices + momentum (yfinance), the last 30 days of Congress filings (STOCK Act) and the latest SEC Form 4 insider filings (officers, directors and big holders buying/selling their own company — this is where names like Musk or Bezos show up in public data).
3. Scores tickers by net congressional buying and by net insider buying (`followed_politicians` / `followed_people` count 3×). Tickers with net buying join the allowed list alongside the watchlist.
4. Pulls the latest headlines for every allowed ticker, plus news about each name in `followed_people` (free, yfinance).
5. Asks Claude: "this is check N of the day, deploy anything right now? into what? why?" with all of that plus its own track record and past lessons.
6. Sells first (if the brain proposed any and the rules allow), then buys. Drops any order without concrete `evidence` (a headline, a filing, a number) or outside the allowed list, applies the guardrails, fills, logs to `log.md`, and in SIM mode rewrites `portfolio.md`.

Guardrails are enforced in code, across all of the day's checks: 40% of the weekly budget per ticker (tracked for the week), 60% of the weekly budget per day (tracked for the day), max 8 buys and 3 sells per day, $5 minimum, a position must be at least 2 days old before it can be sold, and a ticker sold today can't be rebought today. Friday from 3:30 PM ET the remaining budget is deployed in full. Set `only_buy: true` to disable selling entirely.

## How it learns
- `journal.json` — every buy and every sell (with its realised result), with the signals behind it (`congress`, `insider`, `followed_person`, `news`, `momentum`, `track_record`, `etf_default`), the evidence it cited, sector, hour of day, momentum at entry, and its return at 1 week / 1 month.
- `lessons.md` — one sentence the brain writes to its future self after each check that produces one.
- At every check the brain gets the full track record: returns by sector, **by signal source ranked best-to-worst**, by hour of day, best/worst trades, plus its last 12 lessons. Guardrails stay fixed; the judgment inside them improves — over weeks it finds which sources, sectors and times of day have actually been paying off.

## The dashboard (Vercel)

`site/` is a static dashboard in the style of a stock app: pretend-portfolio equity and day change, holdings with sparklines,
the watchlist by sector, Congress + insider filings with net-buying bars, the agent's fills with their evidence, lessons and log,
a search box for any ticker, a detail sheet with 1D–5Y charts, and a **full-screen trading view** (tap "Full-screen chart" or
double-click a row): candles or line, volume, SMA 20/50, VWAP, intervals from 1 minute to 1 month, pan/zoom, crosshair readout,
your buy-in line with green profit / red loss zones, what-if buy-in and size, and the agent's buys/sells marked on the chart.
Charts use TradingView's open-source Lightweight Charts (loaded from jsDelivr). `node site-dev.mjs` previews it locally. `api/` holds three tiny Vercel functions that proxy Yahoo
Finance for quotes, charts and search (free, keyless). The agent writes its data into `site/data/` after every check.

- **Self-updating:** once the repo is on GitHub (`push.command`), link it to Vercel (project root = repo root). Every agent
  commit from GitHub Actions redeploys the site with fresh data. Nothing secret is ever in `site/`.
- **Live now:** https://finleys-stock-agent.vercel.app (Vercel project `finleys-stock-agent`). Until the GitHub link exists it shows the data from the last manual deploy.
- **One-off:** the same files can be deployed by hand from the Vercel dashboard or MCP connector.
- `python -m agent.run --publish` refreshes `site/data/` without asking the brain.

## Watching it live
- **Dashboard:** the Vercel site above, on your phone. Add it to the home screen.
- **SIM mode:** `portfolio.md` — equity, return, every holding's weight and P/L, last fills. Rewritten every check; in the GitHub repo if you use `push.command`, or in the folder if you use `autopilot-mac.command`.
- **Alpaca mode:** app.alpaca.markets on your phone (paper account shows real market prices).
- **Why it did what it did:** `log.md` and `lessons.md` in your GitHub repo — the GitHub mobile app makes this easy.

## Tuning
- `config.yaml` → `weekly_budget`, `run_every_minutes`, watchlist, `followed_politicians` (e.g. `["Nancy Pelosi"]`), `followed_people` (e.g. `["Elon Musk", "Jeff Bezos"]`), guardrails.
- `python -m agent.run --force` runs one check ignoring the weekend/market-closed gate (useful for testing; still honours `DRY_RUN`).
- `only_buy: false` lets the brain sell with evidence; `min_hold_days` and `max_sells_per_day` keep it from churning.
- `autopilot-mac.command stop` (run in Terminal: `bash autopilot-mac.command stop`) removes the Mac schedule; `bash keep-awake-mac.command stop` removes the keep-awake.
- The brain answers through a strict, schema-enforced tool call (`submit_plan`), so malformed JSON can't abort a check; a reply cut off by the token cap is rejected, transient API errors are retried once, and if it still fails the check logs `brain error` and does nothing.
- `ANTHROPIC_EFFORT` in `.env` (default `medium`; `low` is cheaper, `high` thinks longer) controls how hard the brain thinks at each check. Roughly a few cents per check at medium.
- Market calendar (NYSE holidays and 1 PM early closes through 2027) lives at the top of `agent/broker_sim.py`; update it once a year. The end-of-week cleanup fires on the week's last trading day, not literally Friday.

## Honest limits
- Congress filings lag trades by up to 45 days. You're following the paper trail, not the trade.
- **Congress feed sources, in order:** Quiver (paid key) → Financial Modeling Prep (paid tier) → **free public records**: the
  CongressWatch daily aggregate of House + Senate filings (congresswatch.us/data/trades.json) joined with the House Clerk's
  yearly index (disclosures-clerk.house.gov) for House disclosure dates. Senate rows carry only the trade date. No key, ~2
  requests per check, cached in `.cache/`. Verified live 2026-09-06: 168 trades in the trailing 30 days. These are public
  records; 5 U.S.C. 13107(c) forbids using them commercially — this is a personal tool.
- Paid alternatives if the free feed ever breaks (prices read 2026-09-06, monthly billing): Quiver Quantitative Hobbyist ~$30/mo;
  Unusual Whales ~$150/mo; Alpha Vantage premium from ~$49.99/mo (free key gives 25 requests/day, per-symbol); EODHD all-in-one
  ~$99.99/mo; Disclosed Capital Pro ~$14.99/mo; Financial Modeling Prep paid tier (see their pricing page). Finnhub's Congress
  endpoint is premium-only.
- Presidents and their families are not in this feed — only annual disclosures exist for them.
- Following a person like Musk or Bezos means: their SEC Form 4 filings (only for companies they're insiders of, e.g. TSLA, AMZN) plus news about them. Their private portfolios are not public. Big funds' holdings (13F) are quarterly and 45 days late — not wired in yet.
- The insider endpoint (`/stable/insider-trading/latest`) may need a paid Financial Modeling Prep tier; if it returns 402/403 the agent logs it and carries on with Congress + news.
- GitHub's scheduler can skip or delay a cron slot under load; the Friday cleanup also triggers when the agent sees it's the last check of the day.
- I couldn't run the live APIs from here; the code is complete and syntax-checked, but expect to fix a field name or two on first contact with real data. The log will tell you exactly where.
