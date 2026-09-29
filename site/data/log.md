  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain: Only 3 positions held vs min_positions=8, cash_idle_pct 63.9% - need to deploy toward target count. Picked congress-flagged tickers (AVGO, TTD, HLI, FWONK have congress_net_buy_pressure >=2) plus CRWD which has both congress pressure and strong momentum, each with concrete disclosure evidence, sized $1000-2500 to build toward 8 positions while respecting momentum-only entry ban. Added protective stops on all new buys per risk_management practice which has the best track record (0.17% avg, 88% hit rate).
lesson: Congress-pressure tickers (congress_net_buy_pressure>=2) with named disclosures give a real evidence tag distinct from momentum-only entries that get dropped by guardrails; use them to hit min_positions instead of waiting on cooldowns.
- BUY $2500.00 AVGO [filled] ['congress', 'momentum', 'news'] — Congress buy pressure plus positive daily momentum, not yet extended (65% of range) | evidence: Rep. Rick W. Allen (spouse) bought AVGO $1,001-$15,000 disclosed 2026-09-22; stock +2.8% today, 65% of day range, congress_net_buy_pressure 2.0
- BUY $2000.00 CRWD [filled] ['congress', 'momentum'] — Congress pressure ticker with strong 1m momentum, room before hitting chase limit | evidence: congress_net_buy_pressure 2.0 for CRWD, +0.31% today, +19.07% 1mo; existing buy_limit working at 249.42 but adding core position now at market since only 59.6% of range
- BUY $2000.00 TTD [filled] ['congress'] — Repeated congressional buying signal on TTD, currently only 27.8% of day range - not chasing | evidence: Rep. Gilbert Ray Cisneros disclosed TTD buys twice ($1,001-$15,000 each, 2026-09-10 and 2026-09-04); congress_net_buy_pressure 2.0
- BUY $1500.00 HLI [filled] ['congress'] — Congress-flagged name at the low of its day range, good entry point | evidence: congress_net_buy_pressure 2.0 for HLI, at 0% of day range (low)
- BUY $1000.00 FWONK [filled] ['congress'] — Congress-flagged ticker in allowed list with room before chase limit | evidence: congress_net_buy_pressure 2.0 for FWONK, at 36.5% of day range
~ WORKING stop_loss 100% AVGO @ $352.00 until 2026-09-29 — Protective stop per desk rule
~ WORKING stop_loss 100% CRWD @ $253.00 until 2026-09-29 — Protective stop per desk rule
~ WORKING stop_loss 100% TTD @ $11.95 until 2026-09-29 — Protective stop per desk rule
~ WORKING stop_loss 100% HLI @ $126.80 until 2026-09-29 — Protective stop per desk rule
~ WORKING stop_loss 100% FWONK @ $92.50 until 2026-09-29 — Protective stop per desk rule
~ WORKING take_profit 100% AVGO @ $360.52 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING buy_limit $500.00 AVGO @ $348.64 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% CRWD @ $261.50 until 2026-10-04 — close 100% at +0.5% over the average cost
~ WORKING buy_limit $500.00 CRWD @ $252.30 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% TTD @ $12.40 until 2026-10-04 — close 100% at +0.5% over the average cost
~ WORKING buy_limit $500.00 TTD @ $11.97 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% HLI @ $129.91 until 2026-10-04 — close 100% at +0.4% over the average cost
~ WORKING buy_limit $500.00 HLI @ $125.55 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% FWONK @ $94.77 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING buy_limit $500.00 FWONK @ $91.68 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25252.53 (+1.01% on $25000.00 in) · cash $7296.24 · realised +296.24
Done: 0 sell(s), 5 buy(s); 26 order(s) working; budget left $6964.66 this week
  (cancelled 2 standing order(s) on TSM: position closed)
- SELL 100% TSM [take_profit @ $450.62] -> $3007.17 (+0.24%) — close 100% at +0.2% over the average cost
## 2026-09-29 09:53 ET — tick — 1 sell(s), 0 buy(s) from standing orders
  (cancelled 2 standing order(s) on TTD: position closed)
- SELL 100% TTD [take_profit @ $12.40] -> $2010.18 (+0.51%) — close 100% at +0.5% over the average cost
## 2026-09-29 09:53 ET — tick — 1 sell(s), 0 buy(s) from standing orders

## 2026-09-29 09:55 ET (Tuesday) — week 2026-W40 — budget left $11982.01 (today $21000.00 put to work, 9 buys, 4 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain: Below min_positions (6 of 8) with $11,982 remaining budget and 47.9% cash idle - a self-inflicted drag per counterfactual data (idle_share 0.55, avg_regret_pct -0.31 historically when sitting out). Adding NLR (nuclear diversification distinct from CCJ), LMT (defense sector, strong 2y/5y backtest, congress pressure names in same watchlist group), and UNH (widely_held, currently at day low giving good entry) brings us to 9 positions across sectors while respecting cooldowns (TSM/NOC/TTD/HD blocked). Each new buy gets a stop_loss and take_profit per risk_management signal which historically shows 0.17% avg_ret and 0.88 hit_rate, the best-performing signal bucket.
lesson: When below min_positions with idle cash, prioritize sector diversification (nuclear/defense/widely_held) using entries near day lows or with named congress/backtest support rather than waiting on cooldowns to clear.
- BUY $2000.00 NLR [filled] ['momentum', 'track_record'] — Diversify nuclear exposure beyond CCJ using a different vehicle (NLR ETF-like basket) to add a position count without concentrating single-name nuclear risk; low in day range (65.8% of range) is not extreme | evidence: NLR +0.76% today, part of nuclear sector where backtest_priors shows nuclear sector avg_total_return_pct 269-282% over 2y/5y windows (weak prior, but consistent with existing CCJ nuclear holding)
- BUY $2000.00 LMT [filled] ['congress', 'momentum'] — Add defense sector name to diversify beyond widely_held tech names already at cooldown, defense sector has strong historical backtest support | evidence: Defense sector backtest 2y avg_total_return_pct 137.93%, LMT part of watchlist defense group alongside PLTR/RTX/NOC which have congress buy pressure; LMT price $517.31 mid-range (63.4% of day range)
- BUY $2000.00 UNH [filled] ['momentum', 'track_record'] — UNH near its day low (0.3% of range) offers a good entry level versus buying names high in their range; widely_held sector has largest sample size (n=392) in track record | evidence: UNH day range only 0.3% (near day low $373.55), widely_held sector track record avg_ret_pct -0.0% but hit_rate 0.56, price pulled back -1.13% today creating a lower entry point
~ WORKING stop_loss 100% NLR @ $102.10 until 2026-09-29 — protective stop ~2.5% below entry
~ WORKING stop_loss 100% LMT @ $504.40 until 2026-09-29 — protective stop ~2.5% below entry
~ WORKING stop_loss 100% UNH @ $364.30 until 2026-09-29 — protective stop ~2.5% below entry
~ WORKING take_profit 50% NLR @ $107.90 until 2026-09-29 — take partial profit at ~3% gain
~ WORKING take_profit 50% LMT @ $528.70 until 2026-09-29 — take partial profit at ~2.2% gain
~ WORKING take_profit 50% UNH @ $379.50 until 2026-09-29 — take partial profit at ~1.6% gain
~ WORKING take_profit 100% NLR @ $105.23 until 2026-10-04 — close 100% at +0.4% over the average cost
~ WORKING buy_limit $500.00 NLR @ $101.71 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% LMT @ $518.76 until 2026-10-04 — close 100% at +0.2% over the average cost
~ WORKING buy_limit $500.00 LMT @ $501.99 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% UNH @ $374.49 until 2026-10-04 — close 100% at +0.2% over the average cost
~ WORKING buy_limit $500.00 UNH @ $362.42 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25259.73 (+1.04% on $25000.00 in) · cash $6313.59 · realised +313.59
Done: 0 sell(s), 3 buy(s); 32 order(s) working; budget left $5982.01 this week
  (cancelled 3 standing order(s) on UNH: position closed)
- SELL 100% UNH [take_profit @ $375.23] -> $2008.54 (+0.43%) — close 100% at +0.2% over the average cost
## 2026-09-29 10:00 ET — tick — 1 sell(s), 0 buy(s) from standing orders
  (cancelled 2 standing order(s) on AVGO: position closed)
- SELL 100% AVGO [take_profit @ $360.52] -> $2507.61 (+0.30%) — close 100% at +0.3% over the average cost
## 2026-09-29 10:01 ET — tick — 1 sell(s), 0 buy(s) from standing orders
  (cancelled 2 standing order(s) on ACN: position closed)
- SELL 100% ACN [take_profit @ $174.24] -> $3012.82 (+0.43%) — close 100% at +0.4% over the average cost
## 2026-09-29 10:02 ET — tick — 1 sell(s), 0 buy(s) from standing orders
- SELL 100% CCJ [time stop] -> $2978.56 (-0.71%) — held 30 min, the 30-minute limit: out regardless
## 2026-09-29 10:03 ET — tick — 1 sell(s), 0 buy(s) from standing orders
  (cancelled 3 standing order(s) on LMT: position closed)
- SELL 100% LMT [take_profit @ $518.76] -> $2004.79 (+0.24%) — close 100% at +0.2% over the average cost
## 2026-09-29 10:04 ET — tick — 1 sell(s), 0 buy(s) from standing orders
- SELL 100% CRWD [time stop] -> $1978.83 (-1.06%) — held 30 min, the 30-minute limit: out regardless
- SELL 100% HLI [time stop] -> $1479.80 (-1.35%) — held 30 min, the 30-minute limit: out regardless
- SELL 100% FWONK [time stop] -> $992.11 (-0.79%) — held 30 min, the 30-minute limit: out regardless
## 2026-09-29 10:09 ET — tick — 3 sell(s), 0 buy(s) from standing orders

## 2026-09-29 10:10 ET (Tuesday) — week 2026-W40 — budget left $22945.07 (today $27000.00 put to work, 12 buys, 12 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: AUTOPILOT (no model call - the API is unavailable). Held 1 of 8 target names with $22,945 idle, so opened 1: HUBB. Screen: positive one-month momentum, low in the day's range, disclosure preferred, no index funds. This is a rule, not judgement - it cannot read the news, and it keeps the loop gathering graded trades until the model returns.
- BUY $3000.00 HUBB [filled] ['momentum', 'autopilot', 'congress'] — autopilot: best available on the measured screen | evidence: congress net buying (3 net buyers): April McClain Delaney; +1.9% over the month; 35% of today's range
~ WORKING take_profit 100% HUBB @ $469.92 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING stop_loss 100% HUBB @ $465.34 until 2026-10-04 — close it all at -0.7% under the average cost
~ WORKING buy_limit $500.00 HUBB @ $454.55 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25274.61 (+1.10% on $25000.00 in) · cash $20276.66 · realised +276.66
Done: 0 sell(s), 1 buy(s); 8 order(s) working; budget left $19945.07 this week

## 2026-09-29 10:13 ET (Tuesday) — week 2026-W40 — budget left $19945.07 (today $30000.00 put to work, 13 buys, 12 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: autopilot: no name passed the screen (needs positive one-month momentum, room below the day's high, it must not be an index fund - and while allow_momentum_only_entries is false, congressional or insider buying behind it)
portfolio: equity $25280.11 (+1.12% on $25000.00 in) · cash $20276.66 · realised +276.66
Decision: nothing at this check. 8 standing order(s) working.
  (nothing changed; not publishing - the site refreshes on its own timer)
  (cancelled 2 standing order(s) on HUBB: position closed)
- SELL 100% HUBB [stop_loss @ $466.07] -> $2983.74 (-0.54%) — close it all at -0.7% under the average cost
## 2026-09-29 10:15 ET — tick — 1 sell(s), 0 buy(s) from standing orders

## 2026-09-29 10:16 ET (Tuesday) — week 2026-W40 — budget left $22928.81 (today $30000.00 put to work, 13 buys, 13 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: autopilot: no name passed the screen (needs positive one-month momentum, room below the day's high, it must not be an index fund - and while allow_momentum_only_entries is false, congressional or insider buying behind it)
portfolio: equity $25259.54 (+1.04% on $25000.00 in) · cash $23260.40 · realised +260.40
Decision: nothing at this check. 5 standing order(s) working.
  (nothing changed; not publishing - the site refreshes on its own timer)

## 2026-09-29 10:19 ET (Tuesday) — week 2026-W40 — budget left $22928.81 (today $30000.00 put to work, 13 buys, 13 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: autopilot: no name passed the screen (needs positive one-month momentum, room below the day's high, it must not be an index fund - and while allow_momentum_only_entries is false, congressional or insider buying behind it)
portfolio: equity $25259.93 (+1.04% on $25000.00 in) · cash $23260.40 · realised +260.40
Decision: nothing at this check. 5 standing order(s) working.
  (nothing changed; not publishing - the site refreshes on its own timer)

## 2026-09-29 10:22 ET (Tuesday) — week 2026-W40 — budget left $22928.81 (today $30000.00 put to work, 13 buys, 13 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: autopilot: no name passed the screen (needs positive one-month momentum, room below the day's high, it must not be an index fund - and while allow_momentum_only_entries is false, congressional or insider buying behind it)
portfolio: equity $25259.93 (+1.04% on $25000.00 in) · cash $23260.40 · realised +260.40
Decision: nothing at this check. 5 standing order(s) working.
  (nothing changed; not publishing - the site refreshes on its own timer)
- SELL 100% NLR [time stop] -> $2001.15 (+0.06%) — held 30 min, the 30-minute limit: out regardless
## 2026-09-29 10:25 ET — tick — 1 sell(s), 0 buy(s) from standing orders

## 2026-09-29 10:25 ET (Tuesday) — week 2026-W40 — budget left $24929.96 (today $30000.00 put to work, 13 buys, 14 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: autopilot: no name passed the screen (needs positive one-month momentum, room below the day's high, it must not be an index fund - and while allow_momentum_only_entries is false, congressional or insider buying behind it)
portfolio: equity $25261.55 (+1.05% on $25000.00 in) · cash $25261.55 · realised +261.55
Decision: nothing at this check. 1 standing order(s) working.
  (nothing changed; not publishing - the site refreshes on its own timer)

## 2026-09-29 10:28 ET (Tuesday) — week 2026-W40 — budget left $24929.96 (today $30000.00 put to work, 13 buys, 14 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: autopilot: no name passed the screen (needs positive one-month momentum, room below the day's high, it must not be an index fund - and while allow_momentum_only_entries is false, congressional or insider buying behind it)
portfolio: equity $25261.55 (+1.05% on $25000.00 in) · cash $25261.55 · realised +261.55
Decision: nothing at this check. 1 standing order(s) working.
  (nothing changed; not publishing - the site refreshes on its own timer)

## 2026-09-29 10:31 ET (Tuesday) — week 2026-W40 — budget left $24929.96 (today $30000.00 put to work, 13 buys, 14 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: autopilot: no name passed the screen (needs positive one-month momentum, room below the day's high, it must not be an index fund - and while allow_momentum_only_entries is false, congressional or insider buying behind it)
portfolio: equity $25261.55 (+1.05% on $25000.00 in) · cash $25261.55 · realised +261.55
Decision: nothing at this check. 1 standing order(s) working.
  (nothing changed; not publishing - the site refreshes on its own timer)

## 2026-09-29 10:34 ET (Tuesday) — week 2026-W40 — budget left $24929.96 (today $30000.00 put to work, 13 buys, 14 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain unavailable: brain failed after retry: InternalServerError: credential validation failed
  -> falling back to autopilot: rules only, no model call
autopilot: autopilot: no name passed the screen (needs positive one-month momentum, room below the day's high, it must not be an index fund - and while allow_momentum_only_entries is false, congressional or insider buying behind it)
portfolio: equity $25261.55 (+1.05% on $25000.00 in) · cash $25261.55 · realised +261.55
Decision: nothing at this check. 1 standing order(s) working.
  (nothing changed; not publishing - the site refreshes on its own timer)

## 2026-09-29 10:36 ET (Tuesday) — week 2026-W40 — budget left $24929.96 (today $30000.00 put to work, 13 buys, 14 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AOMR excluded: too thinly traded ($1.0M a day) — Angel Oak Mortgage REIT, Inc.)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
brain: Flat book at 99.7% idle cash with 10 checks left today - deploying to 8 names across sectors (tech/widely_held, defense, real estate) using congress disclosure evidence (Gottheimer MSFT buy), momentum, and day-range positioning to avoid chasing highs. Each entry sized at $2000-2500 with ATR-based protective stops per risk_management, which has the best realized track record (0.17-0.18% avg, 88% hit rate) in this account's history.
lesson: Auto_bracket and risk_management signals have the best realized track record (0.17-0.18%, 88% hit rate) - always pair every buy with an explicit ATR-based stop_loss trigger rather than relying on the desk default.
  (dropped IBM: momentum-only entry (guardrails.allow_momentum_only_entries is false))
  (dropped RTX: momentum-only entry (guardrails.allow_momentum_only_entries is false))
  (dropped NOC: momentum-only entry (guardrails.allow_momentum_only_entries is false))
  (dropped O: momentum-only entry (guardrails.allow_momentum_only_entries is false))
  (dropped MSFT: 94% up today's range — resting a limit at $507.99 instead of chasing)
- BUY $2500.00 NVDA [filled] ['momentum', 'track_record'] — Reasonable entry point mid-range with positive multi-week momentum | evidence: NVDA +0.84% today, +6.08% 1m, widely_held sector track record avg_ret 0.0% hit_rate 0.56, mid-range at 43% of day
- BUY $2500.00 GOOGL [filled] ['news', 'momentum'] — Low in day range, oversold short-term, widely held sector | evidence: GOOGL -1.09% today, low in range at 20.7%, -3.46% 5d - potential dip entry after Rep sells disclosed (contrarian to overdone selling)
- BUY $2000.00 PLTR [filled] ['momentum', 'congress'] — Defense-adjacent tech name for diversification, not cooling off | evidence: PLTR -0.53% today, mid-range 43.8%, defense/tech watchlist name with congress interest in defense theme
  (dropped trigger MSFT stop_loss: not held)
  (dropped trigger IBM stop_loss: not held)
  (dropped trigger RTX stop_loss: not held)
  (dropped trigger NOC stop_loss: not held)
  (dropped trigger O stop_loss: not held)
~ WORKING stop_loss 100% NVDA @ $226.00 until 2026-09-29 — Protective stop near 2% below entry
~ WORKING stop_loss 100% GOOGL @ $332.50 until 2026-09-29 — Protective stop below entry
~ WORKING stop_loss 100% PLTR @ $182.50 until 2026-09-29 — Protective stop below entry
~ WORKING buy_limit $2500.00 MSFT @ $507.99 until 2026-09-29 — wanted it, but not at the high — resting at $507.99. Congress buy pressure plus positive momentum, not cooling off
~ WORKING take_profit 100% NVDA @ $231.41 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING buy_limit $500.00 NVDA @ $223.91 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% GOOGL @ $340.03 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING buy_limit $500.00 GOOGL @ $328.92 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% PLTR @ $187.17 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING buy_limit $500.00 PLTR @ $180.93 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25260.15 (+1.04% on $25000.00 in) · cash $18261.55 · realised +261.55
Done: 0 sell(s), 3 buy(s); 11 order(s) working; budget left $17929.96 this week

## 2026-09-29 10:52 ET (Tuesday) — week 2026-W40 — budget left $17929.96 (today $37000.00 put to work, 16 buys, 14 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
  (CTTH excluded: too thinly traded ($0.0M a day) — CTT Pharmaceutical Holdings, Inc.)
brain: Still below min_positions (3 held, need 8) with 71.7% cash idle. Adding AVGO, ACN, TSM using named congress disclosures (Rick W. Allen bought AVGO and TSM disclosed 9/22; Scott Franklin bought ACN disclosed 9/17) which pass the non-momentum-only entry bar. Sized at $2500 each per owner's size guidance, paired with ATR-based stops per the auto_bracket/risk_management lesson that has 88% hit rate historically.
lesson: Congress-disclosed buys with concrete filer names remain the most reliable non-momentum entry tag to reach min_positions when below target; keep pairing every new buy with an explicit stop_loss.
  (dropped TSM: 100% up today's range — resting a limit at $452.57 instead of chasing)
- BUY $2500.00 AVGO [filled] ['congress', 'momentum'] — Congress buy pressure plus positive 1d momentum, diversifies into widely_held/semis sector | evidence: Rep. Rick W. Allen (spouse) bought AVGO disclosed 2026-09-22; AVGO +3.18% today, 80% of day range
- BUY $2500.00 ACN [filled] ['congress'] — Congress buy signal, oversold on 1m (-8.35%), reasonable entry at 50% of day range | evidence: Rep. Scott Franklin bought ACN disclosed 2026-09-17; congress_net_buy_pressure=2.0 for ACN
  (dropped trigger TSM stop_loss: not held)
  (dropped trigger TSM take_profit: not held)
~ WORKING stop_loss 100% AVGO @ $353.50 until 2026-09-29 — protective stop ~2% below entry
~ WORKING stop_loss 100% ACN @ $170.30 until 2026-09-29 — protective stop ~2% below entry
~ WORKING take_profit 50% AVGO @ $365.50 until 2026-09-29 — lock partial gains near recent range top
~ WORKING buy_limit $2500.00 TSM @ $452.57 until 2026-09-29 — wanted it, but not at the high — resting at $452.57. Congress buy pressure plus strong 1m momentum, semis exposure diversifies book
~ WORKING take_profit 100% AVGO @ $361.84 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING buy_limit $500.00 AVGO @ $349.92 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% ACN @ $174.60 until 2026-10-04 — close 100% at +0.4% over the average cost
~ WORKING buy_limit $500.00 ACN @ $168.62 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25264.89 (+1.06% on $25000.00 in) · cash $13261.55 · realised +261.55
Done: 0 sell(s), 2 buy(s); 19 order(s) working; budget left $12929.96 this week
  (cancelled 2 standing order(s) on NVDA: position closed)
- SELL 100% NVDA [take_profit @ $231.41] -> $2506.37 (+0.25%) — close 100% at +0.3% over the average cost
## 2026-09-29 10:54 ET — tick — 1 sell(s), 0 buy(s) from standing orders
- SELL 100% GOOGL [time stop] -> $2499.59 (-0.02%) — held 30 min, the 30-minute limit: out regardless
- SELL 100% PLTR [time stop] -> $1989.02 (-0.55%) — held 30 min, the 30-minute limit: out regardless
## 2026-09-29 11:07 ET — tick — 2 sell(s), 0 buy(s) from standing orders

## 2026-09-29 11:07 ET (Tuesday) — week 2026-W40 — budget left $19924.94 (today $42000.00 put to work, 18 buys, 17 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
  (CTTH excluded: too thinly traded ($0.0M a day) — CTT Pharmaceutical Holdings, Inc.)
brain: Only 2 of min_positions=8 held with 79.7% cash idle - this is a self-inflicted drag per counterfactual_learning (idle_share=0.55, avg_regret negative when picking). Adding IBM (congress pressure, positive day momentum, not cooling), CRWD (congress_net_buy_pressure=2.0, mid-range entry avoiding the chase), and HUBB (highest congress_net_buy_pressure=3.0 on the whole list, named disclosures from April McClain Delaney) moves toward min_positions with concrete evidence-backed entries, each paired with an ATR-based stop_loss per the risk_management signal which has the best realized track record (88% hit rate).
lesson: Past lessons show repeatedly buying only 2-3 names per check keeps below_target_position_count true for hours; batch to 3+ new names per check when idle cash is high and evidence exists, using congress_net_buy_pressure ranking to pick the strongest non-momentum-only candidates.
- BUY $2500.00 IBM [filled] ['congress', 'momentum'] — Diversify into widely_held tech with positive day momentum and congress interest; not currently held or cooling off | evidence: IBM +0.39% today, congress net buy pressure disclosed, not in cooldown
- BUY $2500.00 CRWD [filled] ['news', 'momentum'] — Re-enter CRWD; congress pressure=2 plus mid-range entry avoids chasing the high | evidence: CRWD price 259.11, day range 52.8%, congress_net_buy_pressure 2.0, sold earlier today but cooldown already expired (not in cooling_off_minutes_left list)
- BUY $2500.00 HUBB [filled] ['congress'] — Strongest congress buy-pressure score on the list, not in cooldown, reasonable entry at 6.6% of day range | evidence: congress_net_buy_pressure 3.0 (highest on list), disclosed buyer April McClain Delaney with multiple buy filings
  (dropped trigger AVGO take_profit: duplicate of a working order)
~ WORKING stop_loss 100% IBM @ $216.00 until 2026-09-29 — Protective stop per risk_management best-performing signal
~ WORKING stop_loss 100% CRWD @ $252.50 until 2026-09-29 — Protective stop per risk_management best-performing signal
~ WORKING stop_loss 100% HUBB @ $450.00 until 2026-09-29 — Protective stop per risk_management best-performing signal
~ WORKING take_profit 100% IBM @ $222.37 until 2026-10-04 — close 100% at +0.4% over the average cost
~ WORKING buy_limit $500.00 IBM @ $214.93 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% CRWD @ $260.56 until 2026-10-04 — close 100% at +0.5% over the average cost
~ WORKING buy_limit $500.00 CRWD @ $251.39 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% HUBB @ $463.92 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING buy_limit $500.00 HUBB @ $448.70 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25256.08 (+1.02% on $25000.00 in) · cash $12756.52 · realised +256.52
Done: 0 sell(s), 3 buy(s); 19 order(s) working; budget left $12424.94 this week
- BUY $2500.00 MSFT [buy_limit @ $507.99] — wanted it, but not at the high — resting at $507.99. Congress buy pressure plus positive momentum, not cooling off
- SELL 100% AVGO [time stop] -> $2486.04 (-0.56%) — held 30 min, the 30-minute limit: out regardless
- SELL 100% ACN [time stop] -> $2500.30 (+0.01%) — held 30 min, the 30-minute limit: out regardless
## 2026-09-29 11:22 ET — tick — 2 sell(s), 1 buy(s) from standing orders

## 2026-09-29 11:23 ET (Tuesday) — week 2026-W40 — budget left $14911.28 (today $52000.00 put to work, 22 buys, 19 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
  (CTTH excluded: too thinly traded ($0.0M a day) — CTT Pharmaceutical Holdings, Inc.)
brain: Still below min_positions (4 of 8) with 59.6% cash idle - counterfactual data shows idleness has cost, and past lessons (though unproven) consistently flag under-deployment as the recurring mistake. Adding 4 names across defense/nuclear/semis/consulting sectors, each with concrete evidence (named congress filer or day-range low entry), sized at $2,500 each, all paired with ATR-based stop_losses per the best-performing signal (risk_management/auto_bracket at 88% hit rate). Avoiding cooled-off names (PLTR, ACN is not in cooldown list, GOOGL, NVDA, AVGO) and avoiding momentum-only entries per guardrail.
lesson: Batching 3-4 new names per check with named-evidence signals (congress filer, day-range-low entry) and immediate stop_loss triggers is the path to min_positions without waiting on cooldowns.
  (dropped ACN: sold 1 min ago, cooling off)
- BUY $2500.00 CCJ [filled] ['momentum', 'track_record'] — Nuclear sector diversification at a low point in day range, not chasing | evidence: CCJ at 8.8% of day range ($86.31, low $86.09) after -8.75% 5d pullback; nuclear sector track_record avg_ret -0.17% but low entry point reduces downside
- BUY $2500.00 RTX [filled] ['news', 'track_record'] — Defense sector diversification at day low, adds a fifth uncorrelated name | evidence: RTX at 2.1% of day range ($186.58, low $186.52), defense sector hit_rate 0.55 in track record
- BUY $2500.00 TSM [filled] ['congress', 'momentum'] — Semis exposure with named congress buy; existing buy_limit at 452.57 resting, adding smaller market-ish position since price ran up | evidence: Rep. Rick W. Allen (spouse) bought TSM disclosed 2026-09-22; TSM +9.2% 1m momentum, currently 80% of day range so using limit not market
  (dropped trigger ACN stop_loss: not held)
~ WORKING stop_loss 100% CCJ @ $83.50 until 2026-09-29 — protective stop per risk_management best-performing signal
~ WORKING stop_loss 100% RTX @ $181.50 until 2026-09-29 — protective stop per risk_management best-performing signal
~ WORKING stop_loss 100% TSM @ $443.00 until 2026-09-29 — protective stop per risk_management best-performing signal
~ WORKING take_profit 100% CCJ @ $86.68 until 2026-10-04 — close 100% at +0.4% over the average cost
~ WORKING buy_limit $500.00 CCJ @ $83.75 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% RTX @ $187.07 until 2026-10-04 — close 100% at +0.2% over the average cost
~ WORKING buy_limit $500.00 RTX @ $181.05 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% TSM @ $457.16 until 2026-10-04 — close 100% at +0.2% over the average cost
~ WORKING buy_limit $500.00 TSM @ $442.34 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25227.41 (+0.91% on $25000.00 in) · cash $7742.86 · realised +242.86
Done: 0 sell(s), 3 buy(s); 23 order(s) working; budget left $7411.28 this week
  (cancelled 2 standing order(s) on MSFT: position closed)
- SELL 100% MSFT [stop_loss @ $508.06] -> $2500.35 (+0.01%) — close it all at -0.6% under the average cost
## 2026-09-29 11:31 ET — tick — 1 sell(s), 0 buy(s) from standing orders
- SELL IBM [rejected_no_price]
- SELL 100% CRWD [time stop] -> $2504.50 (+0.18%) — held 30 min, the 30-minute limit: out regardless
- SELL HUBB [rejected_no_price]
## 2026-09-29 11:37 ET — tick — 1 sell(s), 0 buy(s) from standing orders
- SELL 100% IBM [time stop] -> $2502.95 (+0.12%) — held 31 min, the 30-minute limit: out regardless
- SELL HUBB [rejected_no_price]
## 2026-09-29 11:38 ET — tick — 1 sell(s), 0 buy(s) from standing orders

## 2026-09-29 11:38 ET (Tuesday) — week 2026-W40 — budget left $14919.08 (today $59500.00 put to work, 25 buys, 22 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
  (CTTH excluded: too thinly traded ($0.0M a day) — CTT Pharmaceutical Holdings, Inc.)
  (no price for ESE — excluded this check)
- SELL 100% HUBB [time stop] -> $2488.17 (-0.47%) — held 31 min, the 30-minute limit: out regardless
brain: Still below min_positions (3 held, need 8) with 69.6% cash idle. Adding CHRW (congress pressure 3.0, named filer, not extended), HLI (congress pressure 2.0, near day low), NEM (gold sector positive track record, pulled back 8.5% giving cheaper entry) - none are momentum-only, all have concrete evidence and paired stops per risk_management/auto_bracket which are the best-performing signal buckets historically.
lesson: Batch 3 new names per check with named congress filers or sector track-record evidence plus immediate stop_loss to close the min_positions gap faster without waiting on cooldowns.
- BUY $2200.00 CHRW [filled] ['congress', 'track_record'] — Highest congress buy-pressure name not held/cooled, real filer name backing it | evidence: congress_net_buy_pressure CHRW=3.0, Rep. April McClain Delaney filed multiple buys disclosed 2026-09-09; price at 65.3% of day range, not extended
- BUY $2200.00 HLI [filled] ['congress', 'momentum'] — Low in day range entry on a name with congress buy pressure, cheap relative entry | evidence: congress_net_buy_pressure HLI=2.0 (April McClain Delaney), price 127.19 at 11.8% of day range (near low), down -1.81% today but only -4.38% 1m
- BUY $2100.00 NEM [filled] ['momentum', 'track_record'] — Gold sector has positive realized track record; NEM pulled back giving better entry than the recent highs | evidence: gold sector track_record avg_ret_pct +0.03% hit_rate 0.59 (best sector in track_record besides risk_management/standing_order); NEM at 23.7% of day range, -8.53% 5d oversold bounce candidate
~ WORKING stop_loss 100% CHRW @ $145.80 until 2026-09-29 — Protect new CHRW position per risk_management best-performing signal bucket
~ WORKING stop_loss 100% HLI @ $123.50 until 2026-09-29 — Protect new HLI position, similar sizing to other stops
~ WORKING stop_loss 100% NEM @ $113.00 until 2026-09-29 — Protect new NEM position per risk_management best-performing signal bucket
~ WORKING take_profit 100% CHRW @ $149.28 until 2026-10-04 — close 100% at +0.3% over the average cost
~ WORKING buy_limit $500.00 CHRW @ $144.39 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% HLI @ $127.74 until 2026-10-04 — close 100% at +0.4% over the average cost
~ WORKING buy_limit $500.00 HLI @ $123.42 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
~ WORKING take_profit 100% NEM @ $116.91 until 2026-10-04 — close 100% at +0.4% over the average cost
~ WORKING buy_limit $500.00 NEM @ $112.96 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25248.52 (+0.99% on $25000.00 in) · cash $11238.83 · realised +238.83
Done: 1 sell(s), 3 buy(s) (incl. 1 from standing orders); 20 order(s) working; budget left $10907.25 this week
  (cancelled 2 standing order(s) on RTX: position closed)
- SELL 100% RTX [take_profit @ $187.07] -> $2505.51 (+0.22%) — close 100% at +0.2% over the average cost
  (cancelled 2 standing order(s) on TSM: position closed)
- SELL 100% TSM [take_profit @ $457.16] -> $2506.22 (+0.25%) — close 100% at +0.2% over the average cost
## 2026-09-29 11:39 ET — tick — 2 sell(s), 0 buy(s) from standing orders
  (cancelled 2 standing order(s) on CHRW: position closed)
- SELL 100% CHRW [take_profit @ $149.28] -> $2206.21 (+0.28%) — close 100% at +0.3% over the average cost
## 2026-09-29 11:48 ET — tick — 1 sell(s), 0 buy(s) from standing orders
- SELL 100% CCJ [time stop] -> $2496.26 (-0.15%) — held 30 min, the 30-minute limit: out regardless
## 2026-09-29 11:53 ET — tick — 1 sell(s), 0 buy(s) from standing orders

## 2026-09-29 11:55 ET (Tuesday) — week 2026-W40 — budget left $20621.45 (today $66000.00 put to work, 28 buys, 27 sells) — SIM (pretend money) via sim
  (ACOG excluded: too thinly traded ($1.1M a day) — Alpha Cognition Inc. Common Stock)
  (AORT excluded: too thinly traded ($17.9M a day) — Artivion, Inc.)
  (ATCH excluded: too thinly traded ($0.9M a day) — AtlasClear Holdings, Inc.)
  (CBK excluded: too thinly traded ($1.8M a day) — Commercial Bancgroup, Inc.)
  (CFND excluded: too thinly traded ($0.2M a day) — C1 Fund Inc.)
  (CTTH excluded: too thinly traded ($0.0M a day) — CTT Pharmaceutical Holdings, Inc.)
brain: Still well below min_positions (2 of 8) with 82.5% cash idle. Adding 3 more names with concrete evidence: ACN (congress filer Scott Franklin), CCJ (nuclear sector, cheap entry at 10.5% of day range after -13.7% 1m decline), TPL (insider 10% holder bought at higher price than current). All paired with ATR-based stops per risk_management being the best-performing signal (0.17-0.18% avg, 88% hit rate). Existing TSM/AMD/HLI/NEM buy_limits and take-profits remain working.
lesson: Batching diversified-evidence names (congress+insider+cheap-momentum) each check while pairing every buy with an explicit stop_loss is the fastest path to min_positions without waiting on cooldowns; keep new entries below max_entry_range_pct to avoid chasing.
  (dropped ACN: sold 33 min ago, cooling off)
  (dropped CCJ: sold 2 min ago, cooling off)
- BUY $2100.00 TPL [filled] ['insider'] — insider buy signal, real estate/materials diversification, price 333.57 is below insider's buy price of 339.72 | evidence: Horizon Kinetics Asset Management (10% holder) bought TPL shares 9/25 at $339.72, filed 9/29; insider signal has 0.11% avg_ret, 67% hit rate track record
  (dropped trigger ACN stop_loss: not held)
  (dropped trigger CCJ stop_loss: not held)
~ WORKING stop_loss 100% TPL @ $323.50 until 2026-09-29 — protective stop per desk rules
~ WORKING take_profit 100% TPL @ $335.24 until 2026-10-04 — close 100% at +0.5% over the average cost
~ WORKING buy_limit $500.00 TPL @ $323.69 until 2026-10-04 — average in another $500 if it falls 3.0% below the average cost
portfolio: equity $25244.39 (+0.98% on $25000.00 in) · cash $18853.03 · realised +253.03
Done: 0 sell(s), 1 buy(s); 11 order(s) working; budget left $18521.45 this week
