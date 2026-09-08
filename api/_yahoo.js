// Shared Yahoo Finance fetch helpers for the Vercel functions. Free, keyless, unofficial.
const HEADERS = { "User-Agent": "Mozilla/5.0 (Macintosh) StockAgentDashboard/1.0", "Accept": "application/json" };
// default interval per range, and the intervals a range may be viewed at (finer = more bars, Yahoo caps 1m to ~7 days)
const INTERVAL = { "1d": "5m", "5d": "15m", "1mo": "1d", "3mo": "1d", "6mo": "1d", "1y": "1wk", "5y": "1mo" };
const ALLOWED = {
  "1d": ["1m", "2m", "5m", "15m", "30m"], "5d": ["5m", "15m", "30m", "1h"], "1mo": ["30m", "1h", "1d"],
  "3mo": ["1h", "1d", "1wk"], "6mo": ["1d", "1wk"], "1y": ["1d", "1wk"], "5y": ["1wk", "1mo"],
};
function pickInterval(range, want) {
  const ok = ALLOWED[range] || ["1d"];
  return want && ok.includes(want) ? want : (INTERVAL[range] || "1d");
}

function yahooSymbol(t) { return t.includes(".") && !t.endsWith(".TO") ? t.replace(/\./g, "-") : t; }

async function chart(symbol, range = "1d", wantInterval) {
  const interval = pickInterval(range, wantInterval);
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(yahooSymbol(symbol))}?range=${range}&interval=${interval}&includePrePost=false`;
  const r = await fetch(url, { headers: HEADERS });
  if (!r.ok) throw new Error(`yahoo ${r.status}`);
  const d = await r.json();
  const res = d && d.chart && d.chart.result && d.chart.result[0];
  if (!res) throw new Error((d && d.chart && d.chart.error && d.chart.error.description) || "no result");
  const m = res.meta || {};
  const ts = res.timestamp || [];
  const q = (res.indicators && res.indicators.quote && res.indicators.quote[0]) || {};
  const points = [], bars = [];
  for (let i = 0; i < ts.length; i++) {
    const c = (q.close || [])[i];
    if (c == null) continue;
    const t = ts[i] * 1000;
    points.push({ t, c: +c.toFixed(4) });
    const o = (q.open || [])[i], h = (q.high || [])[i], l = (q.low || [])[i], v = (q.volume || [])[i];
    bars.push({ t, o: +(o ?? c).toFixed(4), h: +(h ?? c).toFixed(4), l: +(l ?? c).toFixed(4), c: +c.toFixed(4), v: v == null ? 0 : Math.round(v) });
  }
  // v8 chart meta has no marketState; derive it from the regular session window.
  const reg = (m.currentTradingPeriod && m.currentTradingPeriod.regular) || {};
  const nowS = Math.floor(Date.now() / 1000);
  const marketState = m.instrumentType === "CRYPTOCURRENCY" ? "24H" : (reg.start && reg.end ? (nowS >= reg.start && nowS < reg.end ? "REGULAR" : "CLOSED") : (m.marketState || "UNKNOWN"));
  const price = m.regularMarketPrice != null ? m.regularMarketPrice : (points.length ? points[points.length - 1].c : null);
  // previousClose = the real prior-session close (Yahoo sends it for intraday ranges); chartPreviousClose = the close just before the requested range.
  const prevClose = m.previousClose != null ? m.previousClose : (range === "1d" && m.chartPreviousClose != null ? m.chartPreviousClose : null);
  return {
    symbol,   // keep the caller's spelling (BRK.B), not Yahoo's (BRK-B)
    yahooSymbol: m.symbol || yahooSymbol(symbol), name: m.longName || m.shortName || symbol, currency: m.currency || "USD",
    exchange: m.fullExchangeName || m.exchangeName, marketState, tz: m.exchangeTimezoneName,
    price, prevClose, dayHigh: m.regularMarketDayHigh, dayLow: m.regularMarketDayLow, volume: m.regularMarketVolume,
    high52: m.fiftyTwoWeekHigh, low52: m.fiftyTwoWeekLow, range, interval, intervals: ALLOWED[range] || ["1d"], points,
    bars, regularStart: (reg.start || null) && reg.start * 1000, regularEnd: (reg.end || null) && reg.end * 1000, gmtoffset: m.gmtoffset,
    rangeStart: m.chartPreviousClose != null ? m.chartPreviousClose : (points.length ? points[0].c : null),
  };
}

function withChange(c) {
  const price = c.price, prev = c.range === "1d" ? c.prevClose : c.rangeStart;
  const change = price != null && prev != null ? price - prev : null;
  return { ...c, change, changePct: change != null && prev ? (price / prev - 1) * 100 : null };
}

module.exports = { chart, withChange, HEADERS, ALLOWED, pickInterval, yahooSymbol };
