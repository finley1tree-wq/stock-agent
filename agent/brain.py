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
with hindsight, so treat it as a weak prior and never as a rule), your own track record (returns by sector, by signal source, by
hour of day, plus realised results of past sells) and the lessons you wrote after previous runs.

You can do two things at a check, both optional:
  BUY  - deploy some of the remaining budget into at most 4 tickers from the allowed list.
  SELL - sell part or all of an existing position (if sell_rules allow): to take profit, cut a loser, or rebalance.
         pct_of_position is 0-100. Positions younger than min_hold_days cannot be sold. Never sell and rebuy the same
         ticker in one day. Selling is for a reason, not for activity.

Rules of thumb:
- Doing nothing at a check is normal and usually right. Put the week's money to work in a few well-reasoned tranches,
  not a little at every check. Don't chase intraday noise.
- EVERY buy and EVERY sell must be backed by a concrete piece of evidence from the context: a headline (quote it briefly),
  a specific filing (who bought what, when), or a specific number (momentum, P/L, weight, track-record stat). No evidence, no order.
- Tag each order with the signals behind it, from: congress, insider, followed_person, news, momentum, track_record,
  etf_default, risk_management. The learning loop ranks these by realised return and shows you the ranking - lean into
  what has been working, cut back on what hasn't, but don't overreact to 1-2 trades.
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
TOOL = {"name": "submit_plan", "description": "Submit the buy/sell plan for this check.", "strict": True, "input_schema": {
    "type": "object", "properties": {
        "deploy_now_usd": {"type": "number", "description": "dollars of new budget to deploy at this check (0 is fine)"},
        "orders": {"type": "array", "items": ORDER, "description": "buys, at most 4"},
        "sells": {"type": "array", "items": SELL, "description": "sells of existing positions, may be empty"},
        "reasoning": {"type": "string", "description": "2-3 sentences"},
        "lesson": {"type": "string", "description": "one sentence for your future self, or empty string"}},
    "required": ["deploy_now_usd", "orders", "sells", "reasoning", "lesson"], "additionalProperties": False}}

def _num(v, default=0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return default

def _normalize(plan: dict) -> dict:
    plan = dict(plan or {})
    plan["deploy_now_usd"] = _num(plan.get("deploy_now_usd", 0))
    for key in ("orders", "sells"):
        rows = plan.get(key) or []
        plan[key] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    for o in plan["orders"]: o["usd"] = _num(o.get("usd", 0))
    for s in plan["sells"]: s["pct_of_position"] = _num(s.get("pct_of_position", 0))
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
