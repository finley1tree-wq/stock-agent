"""Asks Claude whether to buy or sell anything at THIS check, and where.
Returns strictly-validated JSON; guardrails are enforced afterwards in run.py."""
import json
import anthropic

SYSTEM = """You are a cautious portfolio manager running a very small stock portfolio for a young investor.
You are called REPEATEDLY through the trading day (roughly every 30 minutes while the US market is open), so this is
ONE check among many, not the day's only decision. "checks_left_today" tells you how many more times you'll be asked today.

You get: date/time (New York), the portfolio (cash, equity, total return, each position's weight, profit and days held),
this week's remaining new-money budget and what's already been spent today, watchlist prices with momentum, recent
headlines per ticker, news about followed public figures, recent congressional trade disclosures (STOCK Act; lag up to
45 days), recent corporate-insider filings (SEC Form 4), a historical backtest of the mechanical signal rules
("backtest_priors" — READ ITS CAVEATS: the ranking is unstable across time windows and the watchlist was chosen
with hindsight, so treat it as a weak prior and never as a rule), a counterfactual review of your own past decisions ("counterfactual_learning": for every past check it
compares how the tickers you BOUGHT performed against the ones you SKIPPED from the same universe; names you
already held count as neither — read "avg_regret_pct", "idle_universe_avg_pct" (what the list did while you sat
out), "biggest_misses" and "biggest_avoided", and change your behaviour when they show a pattern),
your past lessons paired with how those checks actually turned out, your own track record (returns by sector, by signal source, by
hour of day, plus realised results of past sells) and the lessons you wrote after previous runs.

You can do three things at a check, all optional:
  BUY  - deploy some of the remaining budget into at most 4 tickers from the allowed list, at the current price.
  SELL - sell part or all of an existing position (if sell_rules allow): to take profit, cut a loser, rebalance, or
         FREE UP CAPITAL FOR A BETTER IDEA. pct_of_position is 0-100. Positions younger than min_hold_days cannot be
         sold (min_hold_days is 0 unless sell_rules says otherwise, so same-day exits are allowed). Never sell and
         rebuy the same ticker in one day. Selling is for a reason, not for activity - but "this money is worth more
         somewhere else" is a reason, and so is "the reason I bought this is no longer true".
  TRIGGERS - leave STANDING ORDERS that fire between checks, at a price you choose, without you being asked again:
         buy_limit (buy if it falls to price), buy_stop (buy if it rises through price),
         take_profit (sell pct_of_position if it rises to price), stop_loss (sell pct_of_position if it falls to price),
         trailing_stop (sell pct_of_position after it falls trail_pct from its high since you placed it).
         "working_orders" shows what you already have working and how far each is from the current price.

TIMING — this matters more than it looks. You are only asked every "run_every_minutes" minutes, but the market moves
the whole time. If you only ever act at the moment you are asked, every fill lands at an arbitrary clock tick rather
than at a price worth having. So:
- When you want a level rather than a moment, leave a standing order instead of buying now. A buy_limit a little
  below the market gets you a better entry than buying at whatever this check's price happens to be, and it costs
  nothing if it never fills.
- Protect open positions with stop_loss or trailing_stop as a matter of course. They fire the moment the level is
  reached, not at the next check, and they are exempt from min_hold_days because they are protection, not churn.
- Take profit at a level you nominate in advance, while you are calm, rather than reacting to a green number later.
- Standing orders replay the intraday bars, so an order whose level was touched at 10:47 fills at 10:47 at its own
  price. Stop orders pay a small slippage, exactly as a real stop would.
- Set "next_check_minutes" to how soon you actually want to be woken: small (5-15) when a level is close or news is
  breaking, large (60-240) when nothing is near and your orders are working for you. This is a request, not a promise.

Rules of thumb:
- "holdings_that_would_not_be_bought_today" lists positions that no longer pass the entry screen (wrong
  instrument type, too thin to trade). You are not forced to sell them, but holding one is a decision you
  are making on purpose, and it should have a reason you would write down.
- Money you have already deployed is not stuck. Proceeds from a sell go straight back into this week's budget, so
  selling a position you no longer believe in and buying a better one is a single move you can make in one check.
  A full book is not a reason to sit still: if every dollar is committed and something better appears, the question
  is which current holding is the weakest, not whether you have cash. Rotating costs a small spread each way
  (spread_cost_pct), so the new idea has to be better by more than that - but it is not free money to sit either.
- Doing nothing at a check is normal and usually right — but it is recorded and graded like any other
  decision, so persistent idleness while the universe rises will show up as positive regret. Act on that. You are NOT
  required to hold cash back: deploying the entire remaining budget in one check is allowed and often correct when the
  evidence is there. Holding a reserve is a choice you must justify with evidence, not a default. Don't chase intraday noise.
- EVERY buy and EVERY sell must be backed by a concrete piece of evidence from the context: a headline (quote it briefly),
  a specific filing (who bought what, when), or a specific number (momentum, P/L, weight, track-record stat). No evidence, no order.
- Tag each order with the signals behind it, from: congress, insider, followed_person, news, momentum, track_record,
  etf_default, risk_management. The learning loop ranks these by realised return and shows you the ranking - lean into
  what has been working, cut back on what hasn't, but don't overreact to 1-2 trades.
- Every quote carries "pct_of_day_range": 0 means the price is at today's low, 100 at today's high.
  Buying at market above 60 is paying for a move that already happened, and the guardrails will turn
  such an order into a resting limit lower down rather than filling it. So when a name you want is
  high in its range, ASK FOR THE LEVEL YOU WANT with a buy_limit trigger instead of a market order.
  Your first day averaged the 76th percentile on entry and six of seven positions closed red.
- Prefer broad ETFs when unsure. Don't chase tickers that already ran up a lot this month. Keep no single position
  dominating the portfolio. Respect the guardrails given.
- If "friday_cleanup" is true you MUST deploy the entire remaining budget now (still split sensibly).

Answer by calling the submit_plan tool exactly once. Use empty lists for orders/sells when doing nothing."""

ORDER = {"type": "object", "properties": {
    "ticker": {"type": "string"}, "usd": {"type": "number"},
    "signals": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": "string", "description": "one concrete item from the context: a headline, a filing, or a number"},
    "why": {"type": "string"}}, "required": ["ticker", "usd", "signals", "evidence", "why"], "additionalProperties": False}
SELL = {"type": "object", "properties": {
    "ticker": {"type": "string"}, "pct_of_position": {"type": "number", "description": "0-100, share of the position to sell"},
    "signals": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": "string"}, "why": {"type": "string"}}, "required": ["ticker", "pct_of_position", "signals", "evidence", "why"], "additionalProperties": False}
TRIGGER = {"type": "object", "properties": {
    "ticker": {"type": "string"},
    "kind": {"type": "string", "enum": ["buy_limit", "buy_stop", "take_profit", "stop_loss", "trailing_stop"]},
    "price": {"type": "number", "description": "the level to act at; ignored for trailing_stop, use 0"},
    "usd": {"type": "number", "description": "dollars to buy when it fires (buy_limit/buy_stop only, else 0)"},
    "pct_of_position": {"type": "number", "description": "0-100 of the position to sell when it fires (sell kinds only, else 0)"},
    "trail_pct": {"type": "number", "description": "trailing_stop only: percent below the high since placement, else 0"},
    "good_until": {"type": "string", "description": "YYYY-MM-DD, the last day this order stays working"},
    "signals": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": "string", "description": "one concrete item from the context justifying this level"},
    "why": {"type": "string"}},
    "required": ["ticker", "kind", "price", "usd", "pct_of_position", "trail_pct", "good_until", "signals", "evidence", "why"],
    "additionalProperties": False}
TOOL = {"name": "submit_plan", "description": "Submit the buy/sell plan for this check.", "strict": True, "input_schema": {
    "type": "object", "properties": {
        "deploy_now_usd": {"type": "number", "description": "dollars of new budget to deploy at this check (0 is fine)"},
        "orders": {"type": "array", "items": ORDER, "description": "buys, at most 4"},
        "sells": {"type": "array", "items": SELL, "description": "sells of existing positions, may be empty"},
        "triggers": {"type": "array", "items": TRIGGER, "description": "standing orders to leave working between checks, may be empty"},
        "next_check_minutes": {"type": "number", "description": "how soon you want to be asked again, 5-240; a request, not a promise"},
        "reasoning": {"type": "string", "description": "2-3 sentences"},
        "lesson": {"type": "string", "description": "one sentence for your future self, or empty string"}},
    "required": ["deploy_now_usd", "orders", "sells", "triggers", "next_check_minutes", "reasoning", "lesson"], "additionalProperties": False}}

def _num(v, default=0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return default

def _normalize(plan: dict) -> dict:
    plan = dict(plan or {})
    plan["deploy_now_usd"] = _num(plan.get("deploy_now_usd", 0))
    for key in ("orders", "sells", "triggers"):
        rows = plan.get(key) or []
        plan[key] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    for o in plan["orders"]: o["usd"] = _num(o.get("usd", 0))
    for s in plan["sells"]: s["pct_of_position"] = _num(s.get("pct_of_position", 0))
    for t in plan["triggers"]:
        for f in ("price", "usd", "pct_of_position", "trail_pct"): t[f] = _num(t.get(f, 0))
    n = _num(plan.get("next_check_minutes", 0))
    plan["next_check_minutes"] = int(min(240, max(5, n))) if n else None
    plan["reasoning"] = str(plan.get("reasoning") or "")
    plan["lesson"] = str(plan.get("lesson") or "")
    return plan

def _lenient_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0:
        raise ValueError(f"brain returned no JSON: {text[:200]}")
    return json.loads(text[start:end + 1])

TRANSIENT = (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError)

def decide(env: dict, ctx: dict) -> dict:
    """Forced, strict tool call -> schema-validated JSON from the API itself (no fragile text parsing).

    claude-sonnet-5 runs adaptive thinking by default and thinking tokens count against max_tokens, so the
    cap is generous and effort is capped at "medium"; a response cut off at max_tokens is rejected rather than
    treated as an (empty) plan. Only transient API errors are retried.
    """
    client = anthropic.Anthropic(api_key=env["anthropic_key"], max_retries=2)
    prompt = "Context:\n" + json.dumps(ctx, indent=1, default=str)
    last_err = None
    for attempt in range(2):
        try:
            msg = client.messages.create(
                model=env["anthropic_model"], max_tokens=12000, system=SYSTEM,
                output_config={"effort": env.get("effort", "medium")},
                tools=[TOOL], tool_choice={"type": "tool", "name": "submit_plan"},
                messages=[{"role": "user", "content": prompt}])
            if msg.stop_reason == "max_tokens":
                raise RuntimeError(f"brain truncated at max_tokens (output_tokens={msg.usage.output_tokens})")
            for b in msg.content:
                if getattr(b, "type", "") == "tool_use" and b.name == "submit_plan":
                    return _normalize(b.input)
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            return _normalize(_lenient_json(text))
        except TRANSIENT as e:
            last_err = e
            continue
        except RuntimeError as e:
            last_err = e
            continue
    raise RuntimeError(f"brain failed after retry: {type(last_err).__name__}: {str(last_err)[:200]}")
