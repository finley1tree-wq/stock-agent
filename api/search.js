// GET /api/search?q=palantir -> [{symbol, name, exchange, type}]
const { HEADERS } = require("./_yahoo.js");

module.exports = async (req, res) => {
  const q = String(req.query.q || "").trim().slice(0, 40);
  if (q.length < 1) return res.status(200).json({ results: [] });
  try {
    const r = await fetch(`https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(q)}&quotesCount=8&newsCount=0&listsCount=0`, { headers: HEADERS });
    const d = await r.json();
    const results = (d.quotes || [])
      .filter(x => x.symbol && ["EQUITY", "ETF", "INDEX", "MUTUALFUND", "CRYPTOCURRENCY"].includes(x.quoteType))
      .map(x => ({ symbol: x.symbol, name: x.shortname || x.longname || x.symbol, exchange: x.exchDisp || x.exchange, type: x.quoteType }));
    res.setHeader("Cache-Control", "s-maxage=3600");
    res.status(200).json({ results });
  } catch (e) {
    res.status(502).json({ results: [], error: String(e.message || e) });
  }
};
