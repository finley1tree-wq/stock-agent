// GET /api/chart?symbol=SPY&range=1mo&interval=1h  -> one symbol, one range (1d 5d 1mo 3mo 6mo 1y 5y), optional interval (whitelisted per range)
const { chart, withChange } = require("./_yahoo.js");
const RANGES = new Set(["1d", "5d", "1mo", "3mo", "6mo", "1y", "5y"]);

module.exports = async (req, res) => {
  const symbol = String(req.query.symbol || "").trim().toUpperCase();
  const range = RANGES.has(req.query.range) ? req.query.range : "1d";
  if (!symbol) return res.status(400).json({ error: "symbol required" });
  try {
    const c = withChange(await chart(symbol, range, String(req.query.interval || "")));
    const intraday = /m$|h$/.test(c.interval);
    res.setHeader("Cache-Control", intraday ? "s-maxage=60, stale-while-revalidate=120" : "s-maxage=900, stale-while-revalidate=3600");
    res.status(200).json(c);
  } catch (e) {
    res.status(502).json({ symbol, range, error: String(e.message || e) });
  }
};
