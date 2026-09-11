// GET /api/quotes?symbols=SPY,GLD  -> day quotes + intraday sparkline for up to 40 symbols
const { chart, withChange } = require("./_yahoo.js");

module.exports = async (req, res) => {
  const symbols = String(req.query.symbols || "").split(",").map(s => s.trim().toUpperCase()).filter(Boolean).slice(0, 40);
  if (!symbols.length) return res.status(400).json({ error: "symbols required" });
  const quotes = await Promise.all(symbols.map(async s => {
    try { return withChange(await chart(s, "1d")); }
    catch (e) { return { symbol: s, error: String(e.message || e) }; }
  }));
  // The edge cache was the real speed limit on the live chart: at s-maxage=60 the trading view
  // polled every 2 seconds and got the same cached number for a full minute, so the candle sat
  // still and then jumped. Five seconds is fresh enough to look live and still absorbs the poll -
  // every viewer of the same symbol shares one upstream fetch per 5s window.
  res.setHeader("Cache-Control", "s-maxage=5, stale-while-revalidate=30");
  res.status(200).json({ asOf: Date.now(), quotes });
};
