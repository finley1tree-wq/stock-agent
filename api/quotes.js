// GET /api/quotes?symbols=SPY,GLD  -> day quotes + intraday sparkline for up to 40 symbols
const { chart, withChange } = require("./_yahoo.js");

module.exports = async (req, res) => {
  const symbols = String(req.query.symbols || "").split(",").map(s => s.trim().toUpperCase()).filter(Boolean).slice(0, 40);
  if (!symbols.length) return res.status(400).json({ error: "symbols required" });
  const quotes = await Promise.all(symbols.map(async s => {
    try { return withChange(await chart(s, "1d")); }
    catch (e) { return { symbol: s, error: String(e.message || e) }; }
  }));
  res.setHeader("Cache-Control", "s-maxage=60, stale-while-revalidate=120");
  res.status(200).json({ asOf: Date.now(), quotes });
};
