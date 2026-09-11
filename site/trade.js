/* Full-screen trading view: candles/line, volume, SMA/VWAP, crosshair readout, buy-in line with profit/loss zones,
   agent buy/sell markers, pan/zoom. Uses TradingView Lightweight Charts 4.x (loaded in index.html).

   Four layers answer "where is this thing actually going to move":
     LIQUIDITY  a volume profile drawn down the right edge - how much stock changed hands at each
                price. The fat bar is the Point of Control, the price the market keeps coming back
                to; the shaded band is the value area holding 70% of the volume. Price leaving the
                band and price returning to the POC are the two things worth watching.
     LEVELS     today's open, yesterday's close, and the running high and low of the session.
     CLOCK      every position is force-closed after max_hold_minutes, so an open position shows a
                live countdown and the bar where it will be sold.
     BUY-IN     the average cost, with the live gain or loss written into the axis label. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const money = (v, d = 2) => v == null || isNaN(v) ? "—" : (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (v, d = 2) => v == null || isNaN(v) ? "—" : (v > 0 ? "+" : "") + v.toFixed(d) + "%";
  const signed = (v) => v == null || isNaN(v) ? "—" : (v > 0 ? "+" : v < 0 ? "-" : "") + "$" + Math.abs(v).toFixed(2);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const RANGES = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "5y"];
  const RLABEL = { "1d": "1D", "5d": "5D", "1mo": "1M", "3mo": "3M", "6mo": "6M", "1y": "1Y", "5y": "5Y" };
  const UP = "#30d158", DOWN = "#ff453a", AMBER = "#ffb340", BLUE = "#0a84ff", MUTED = "#8b98a9";
  const fmtNY = (ms, withDate) => new Date(ms).toLocaleString("en-US", { timeZone: "America/New_York", ...(withDate ? { month: "short", day: "numeric" } : {}), hour: "numeric", minute: "2-digit" });
  const fmtDay = (ms) => new Date(ms).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", year: "2-digit" });

  const HINT = `<span class="dim">Move over the chart for O / H / L / C / volume and P/L at that price. Drag to pan, pinch or scroll to zoom.</span>`;
  // The fastest useful view: today, one-minute candles, volume + the layers that matter. "Reset
  // view" puts you back here in one click, because a saved preference from weeks ago (a 30-minute
  // interval, say) silently makes the chart look like it is barely moving.
  const FAST = { range: "1d", type: "candles", intervals: { "1d": "1m", "5d": "5m" },
                 show: { vol: true, sma20: false, sma50: false, vwap: false, buyin: true, orders: true, liq: true, levels: true } };
  const T = { sym: null, range: "1d", interval: null, type: "candles", show: { vol: true, sma20: false, sma50: false, vwap: false, buyin: true, orders: true, liq: true, levels: true }, data: null, chart: null, series: {}, entry: null, entryMode: "auto", size: null, seq: 0, resize: null };
  const prefs = (() => { try { return JSON.parse(localStorage.getItem("sa.trade") || "{}"); } catch (e) { return {}; } })();
  Object.assign(T, { range: prefs.range || "1d", type: prefs.type || "candles", show: { ...T.show, ...(prefs.show || {}) },
    intervals: prefs.intervals || { "1d": "1m", "5d": "5m" } });
  const savePrefs = () => { try { localStorage.setItem("sa.trade", JSON.stringify({ range: T.range, type: T.type, show: T.show, intervals: T.intervals })); } catch (e) {} };

  function ctx() { return window.SA || { positions: () => ({}), journal: () => [], quote: () => null, working: () => [] }; }

  function open(sym) {
    if (!window.LightweightCharts) { alert("Chart library didn't load. Check your connection and try again."); return; }
    T.sym = sym; T.entryMode = "auto"; T.entry = null; T.size = null; T.interval = null;
    const pos = ctx().positions()[sym];
    const root = $("#trade-root"); root.innerHTML = "";
    const v = document.createElement("div"); v.className = "trade"; v.setAttribute("role", "dialog"); v.setAttribute("aria-label", sym + " trading view");
    v.innerHTML = `
      <div class="t-head">
        <button class="t-close" aria-label="Close">×</button>
        <div class="t-title"><span class="t-sym">${esc(sym)}</span><span class="t-name" id="t-name"></span></div>
        <div class="t-price"><span class="num" id="t-price">…</span><span id="t-chg" class="t-chg"></span><span id="t-clock" class="t-clock" hidden></span><span id="t-live" class="t-live" hidden></span></div>
        <div class="t-pos" id="t-pos" hidden></div>
      </div>
      <div class="t-bar">
        <div class="chips" id="t-ranges">${RANGES.map(r => `<button data-r="${r}" aria-pressed="${r === T.range}">${RLABEL[r]}</button>`).join("")}</div>
        <div class="chips" id="t-intervals"></div>
        <div class="chips" id="t-reset"><button data-reset="1" title="Back to today, 1-minute candles - the fastest view">Reset view</button></div>
        <div class="chips" id="t-type"><button data-t="candles" aria-pressed="${T.type === "candles"}">Candles</button><button data-t="line" aria-pressed="${T.type === "line"}">Line</button></div>
        <div class="chips" id="t-toggles">
          <button data-k="vol" aria-pressed="${T.show.vol}">Vol</button><button data-k="sma20" aria-pressed="${T.show.sma20}">SMA 20</button><button data-k="sma50" aria-pressed="${T.show.sma50}">SMA 50</button><button data-k="vwap" aria-pressed="${T.show.vwap}">VWAP</button><button data-k="buyin" aria-pressed="${T.show.buyin}">Buy-in</button><button data-k="orders" aria-pressed="${T.show.orders}">Orders</button><button data-k="liq" aria-pressed="${T.show.liq}" title="Volume profile: how much stock traded at each price">Liquidity</button><button data-k="levels" aria-pressed="${T.show.levels}" title="Session open, prior close, day high and low">Levels</button>
        </div>
      </div>
      <div class="t-read" id="t-read"><span class="dim">Move over the chart for O / H / L / C / volume and P/L at that price. Drag to pan, pinch or scroll to zoom.</span></div>
      <div class="t-chart" id="t-chart"><canvas id="t-liq" class="t-liq" aria-hidden="true"></canvas><div class="t-legend" id="t-legend" hidden></div></div>
      <div class="t-foot">
        <div class="t-entry">
          <label>Buy-in <input id="t-entry" type="number" step="0.01" inputmode="decimal" aria-label="Buy-in price"></label>
          <button class="btn" id="t-entry-cursor" title="Use the price under the crosshair">Set at cursor</button>
          <button class="btn" id="t-entry-reset" title="${pos ? "Back to your real average cost" : "Back to the current price"}">Reset</button>
          <label>Size $<input id="t-size" type="number" step="10" inputmode="decimal" aria-label="Position size in dollars"></label>
        </div>
        <div class="t-pl" id="t-pl"></div>
      </div>`;
    root.appendChild(v); document.body.style.overflow = "hidden";
    v.querySelector(".t-close").addEventListener("click", close);
    document.addEventListener("keydown", escClose);
    $("#t-ranges").addEventListener("click", e => { const b = e.target.closest("button[data-r]"); if (!b) return; T.range = b.dataset.r; T.interval = T.intervals[T.range] || null; pressed("#t-ranges", "r", T.range); savePrefs(); startLive(); load(); });
    $("#t-reset").addEventListener("click", () => {
      Object.assign(T, { range: FAST.range, type: FAST.type, show: { ...FAST.show },
                         intervals: { ...FAST.intervals }, entry: null, entryMode: "auto", size: null });
      T.interval = T.intervals[T.range];
      try { localStorage.removeItem("sa.trade"); } catch (e) {}
      savePrefs();
      pressed("#t-ranges", "r", T.range); pressed("#t-type", "t", T.type);
      document.querySelectorAll("#t-toggles button").forEach(b => b.setAttribute("aria-pressed", !!T.show[b.dataset.k]));
      const sz = $("#t-size"); if (sz) sz.value = "";
      startLive(); load();
    });
    $("#t-type").addEventListener("click", e => { const b = e.target.closest("button[data-t]"); if (!b) return; T.type = b.dataset.t; pressed("#t-type", "t", T.type); savePrefs(); draw(); });
    $("#t-toggles").addEventListener("click", e => { const b = e.target.closest("button[data-k]"); if (!b) return; T.show[b.dataset.k] = !T.show[b.dataset.k]; b.setAttribute("aria-pressed", T.show[b.dataset.k]); savePrefs(); draw(); });
    $("#t-entry").addEventListener("change", e => { const v = parseFloat(e.target.value); if (v > 0) { T.entry = v; T.entryMode = "manual"; drawEntry(); } });
    $("#t-size").addEventListener("change", e => { const v = parseFloat(e.target.value); T.size = v > 0 ? v : null; updatePL(T.lastPrice); });
    $("#t-entry-reset").addEventListener("click", () => { T.entryMode = "auto"; T.entry = null; T.size = null; $("#t-size").value = ""; drawEntry(); });
    $("#t-entry-cursor").addEventListener("click", () => { if (T.cursorPrice) { T.entry = +T.cursorPrice.toFixed(2); T.entryMode = "manual"; $("#t-entry").value = T.entry; drawEntry(); } });
    T.interval = T.intervals[T.range] || null;
    startLive();
    document.addEventListener("visibilitychange", onVis);
    load();
  }
  function onVis() { if (!document.hidden && $("#t-chart")) { load(true); pollPrice(); } }

  // ---------------------------------------------------------------------------------------------
  // LIVE CANDLES. Refetching the whole series and rebuilding the chart every 15 seconds is why the
  // view looked frozen and then jumped: the chart object was destroyed and recreated, losing the
  // animation and the user's place. A real trading view does two different things at two different
  // speeds, so that is what this does now:
  //   every ~2s   poll the price alone and UPDATE the forming candle in place (series.update) -
  //               the bar grows, its high and low stretch, the volume bar follows, nothing redraws
  //   every ~30s  refetch the bars to true up the OHLC the exchange actually printed, and to pick
  //               up bars that closed while we were extrapolating
  const BAR_SECONDS = { "1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600, "1d": 86400, "1wk": 604800, "1mo": 2592000 };
  function barSeconds() { return BAR_SECONDS[(T.data && T.data.interval) || ""] || 60; }

  async function pollPrice() {
    if (document.hidden || !T.sym || !T.chart || !T.data) return;
    let q = null;
    try {
      const r = await fetch("/api/quotes?symbols=" + encodeURIComponent(T.sym), { cache: "no-store" });
      if (r.ok) q = ((await r.json()).quotes || [])[0];
    } catch (e) { return; }
    const price = q && +q.price;
    if (!(price > 0) || !T.series.main) return;
    applyLivePrice(price, q);
  }

  function applyLivePrice(price, q) {
    const bars = T.data.bars; if (!bars || !bars.length) return;
    const sec = barSeconds(), nowS = Math.floor(Date.now() / 1000);
    const last = bars[bars.length - 1];
    const lastStart = Math.floor(last.t / 1000);
    let bar;
    if (nowS - lastStart >= sec) {
      // the forming bar closed while we were watching: open a new one at this price
      bar = { t: (lastStart + Math.floor((nowS - lastStart) / sec) * sec) * 1000,
              o: price, h: price, l: price, c: price, v: 0 };
      bars.push(bar);
      if (bars.length > 3000) bars.shift();
    } else {
      bar = last;
      bar.c = price;
      if (price > bar.h) bar.h = price;
      if (price < bar.l) bar.l = price;
    }
    const time = Math.floor(bar.t / 1000);
    try {
      if (T.type === "candles") T.series.main.update({ time, open: bar.o, high: bar.h, low: bar.l, close: bar.c });
      else T.series.main.update({ time, value: bar.c });
      if (T.series.vol) {
        const prev = bars.length > 1 ? bars[bars.length - 2].c : bar.o;
        T.series.vol.update({ time, value: bar.v, color: bar.c >= prev ? "rgba(48,209,88,.35)" : "rgba(255,69,58,.35)" });
      }
    } catch (e) { return; }          // a stale time (out of order) is not worth throwing over
    T.lastPrice = price;
    T.lastTickAt = Date.now();
    T.data.price = price;
    if (q) { if (q.changePct != null) T.data.change = +q.changePct; T.quote = q; }
    paintHeader(price, q);
    drawEntry();
    drawPosition();                   // the badge is the number the owner actually reads
    drawLevels();                     // the day's high and low move while the session runs
    drawLiquidity();
    if (!T.cursorPrice) updatePL(price);
  }

  function paintHeader(price, q) {
    const el = $("#t-price"); if (!el) return;
    el.textContent = money(price);
    el.classList.remove("pulse"); void el.offsetWidth; el.classList.add("pulse");
    const chg = q && q.changePct != null ? +q.changePct : T.data && T.data.change;
    const c = $("#t-chg");
    if (c && chg != null) {
      const abs = q && q.change != null ? +q.change : null;
      c.innerHTML = `<span style="color:${chg >= 0 ? UP : DOWN}">${abs != null ? signed(abs) + " " : ""}${pct(chg)}</span>`;
    }
  }

  function drawPosition() {
    const el = $("#t-pos"); if (!el) return;
    const pos = ctx().positions()[T.sym];
    const live = T.lastPrice || (T.data && T.data.price);
    if (!pos || !T.entry || !live || T.entryMode !== "auto") { el.hidden = true; return; }
    const perShare = live - T.entry, perPct = (live / T.entry - 1) * 100;
    const dollars = perShare * (+pos.qty || 0);
    const up = perShare >= 0;
    el.hidden = false;
    el.className = "t-pos " + (up ? "up" : "down");
    el.innerHTML = `<span class="t-pos-arrow">${up ? "\u25B2" : "\u25BC"}</span>`
      + `<span class="t-pos-big">${signed(dollars)}</span>`
      + `<span class="t-pos-pct">${pct(perPct)}</span>`
      + `<span class="t-pos-sub">since you bought at ${money(T.entry)}</span>`;
  }

  function tickClock() {
    drawClock();
    drawPosition();
    // Say plainly how fresh the price is. The feed is free Yahoo data, so a few seconds between
    // ticks is normal and a long gap means something is actually wrong - worth being able to see.
    const el = $("#t-live"); if (!el) return;
    if (!T.lastTickAt) { el.hidden = true; return; }
    const age = Math.round((Date.now() - T.lastTickAt) / 1000);
    el.hidden = false;
    el.textContent = age < 3 ? "LIVE" : `LIVE · ${age}s`;
    el.className = "t-live" + (age > 30 ? " stale" : "");
    el.title = `Price last changed ${age}s ago. Polled every 2 seconds; the free quote feed updates every few seconds.`;
  }
  function startLive() {
    clearInterval(T.clockTimer); T.clockTimer = setInterval(tickClock, 1000);
    clearInterval(T.live); clearInterval(T.priceTimer);
    const intraday = T.range === "1d" || T.range === "5d";
    // the price poll is the fast one; the full refetch only has to true up what we extrapolated
    T.priceTimer = setInterval(pollPrice, intraday ? 2000 : 10000);
    T.live = setInterval(() => { if (!document.hidden && $("#t-chart")) load(true); }, intraday ? 30000 : 120000);
  }
  function pressed(sel, attr, val) { document.querySelectorAll(`${sel} button`).forEach(b => b.setAttribute("aria-pressed", b.dataset[attr] === val)); }
  function escClose(e) { if (e.key === "Escape") close(); }
  function close() { clearInterval(T.live); clearInterval(T.clockTimer); clearInterval(T.priceTimer); document.removeEventListener("visibilitychange", onVis); if (T.chart) { try { T.chart.remove(); } catch (e) {} T.chart = null; } if (T.resize) { window.removeEventListener("resize", T.resize); T.resize = null; } $("#trade-root").innerHTML = ""; document.body.style.overflow = ""; document.removeEventListener("keydown", escClose); }

  async function load(silent) {
    const my = ++T.seq; const read = $("#t-read");
    if (read && !silent) read.innerHTML = `<span class="dim">Loading ${esc(T.sym)} ${RLABEL[T.range]}…</span>`;
    const url = `/api/chart?symbol=${encodeURIComponent(T.sym)}&range=${T.range}${T.interval ? "&interval=" + T.interval : ""}`;
    let c = null; try { const r = await fetch(url, { cache: "no-store" }); c = r.ok ? await r.json() : null; } catch (e) { c = null; }
    if (my !== T.seq || !$("#t-chart")) return;
    if (!c || c.error || !(c.bars || []).length) { $("#t-read").innerHTML = `<span style="color:${DOWN}">No chart data for ${esc(T.sym)} (${esc(c?.error || "empty")}).</span>`; return; }
    T.data = c; T.interval = c.interval;
    $("#t-name").textContent = c.name || ""; $("#t-price").textContent = money(c.price);
    const cls = c.change > 0 ? "up" : c.change < 0 ? "down" : "flat";
    $("#t-chg").innerHTML = c.change != null ? `<span class="pill ${cls}">${signed(c.change)} (${pct(c.changePct)})</span> <span class="dim">${T.range === "1d" ? "today" : RLABEL[T.range]}</span>` : "";
    $("#t-intervals").innerHTML = (c.intervals || []).map(i => `<button data-i="${i}" aria-pressed="${i === c.interval}">${i}</button>`).join("");
    $("#t-intervals").onclick = e => { const b = e.target.closest("button[data-i]"); if (!b) return; T.interval = b.dataset.i; T.intervals[T.range] = b.dataset.i; savePrefs(); load(); };
    if (T.entryMode === "auto") { const pos = ctx().positions()[T.sym]; T.entry = pos ? pos.avg_cost : c.price; $("#t-entry").value = T.entry != null ? (+T.entry).toFixed(2) : ""; }
    draw(silent);
    const rd = $("#t-read"); if (rd && !silent) rd.innerHTML = HINT;
  }

  function sma(bars, n) { const out = []; let sum = 0; for (let i = 0; i < bars.length; i++) { sum += bars[i].c; if (i >= n) sum -= bars[i - n].c; if (i >= n - 1) out.push({ time: bars[i].time, value: +(sum / n).toFixed(4) }); } return out; }
  function vwap(bars) { const out = []; let pv = 0, vv = 0, day = null; for (const b of bars) { const d = new Date(b.t).toLocaleDateString("en-US", { timeZone: "America/New_York" }); if (d !== day) { day = d; pv = 0; vv = 0; } const tp = (b.h + b.l + b.c) / 3; pv += tp * b.v; vv += b.v; if (vv > 0) out.push({ time: b.time, value: +(pv / vv).toFixed(4) }); } return out; }

  function draw(keepView) {
    const c = T.data; if (!c) return; const LW = window.LightweightCharts; const host = $("#t-chart"); if (!host) return;
    let view = null;
    if (T.chart) {
      // a live refresh must not yank the view back to fit: keep wherever the user is looking
      if (keepView) { try { view = T.chart.timeScale().getVisibleLogicalRange(); } catch (e) {} }
      try { T.chart.remove(); } catch (e) {} T.chart = null;
    }
    if (T.resize) { window.removeEventListener("resize", T.resize); }
    const intraday = /m$|h$/.test(c.interval);
    const bars = c.bars.map(b => ({ ...b, time: Math.floor(b.t / 1000) }));
    const chart = LW.createChart(host, {
      layout: { background: { type: LW.ColorType.Solid, color: "#0a0e13" }, textColor: MUTED, fontFamily: "-apple-system, BlinkMacSystemFont, Inter, sans-serif", fontSize: 11 },
      grid: { vertLines: { color: "rgba(255,255,255,.04)" }, horzLines: { color: "rgba(255,255,255,.06)" } },
      crosshair: { mode: LW.CrosshairMode.Normal, vertLine: { color: "rgba(139,152,169,.5)", labelBackgroundColor: "#182130" }, horzLine: { color: "rgba(139,152,169,.5)", labelBackgroundColor: "#182130" } },
      rightPriceScale: { borderColor: "#1f2a38", scaleMargins: { top: 0.08, bottom: T.show.vol ? 0.26 : 0.08 } },
      timeScale: { borderColor: "#1f2a38", timeVisible: intraday, secondsVisible: false, rightOffset: 4, barSpacing: intraday ? 6 : 8,
        tickMarkFormatter: (t) => intraday ? fmtNY(t * 1000) : fmtDay(t * 1000) },
      localization: { timeFormatter: (t) => intraday ? fmtNY(t * 1000, true) + " ET" : fmtDay(t * 1000), priceFormatter: p => p >= 1000 ? p.toFixed(0) : p.toFixed(2) },
      handleScroll: true, handleScale: true, autoSize: false, width: host.clientWidth, height: host.clientHeight,
    });
    T.chart = chart; T.series = {};
    if (T.type === "candles") {
      T.series.main = chart.addCandlestickSeries({ upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN, priceLineVisible: true, lastValueVisible: true });
      T.series.main.setData(bars.map(b => ({ time: b.time, open: b.o, high: b.h, low: b.l, close: b.c })));
    } else {
      const up = c.change == null ? null : c.change >= 0; const col = up === null ? MUTED : up ? UP : DOWN;
      T.series.main = chart.addAreaSeries({ lineColor: col, topColor: col + "55", bottomColor: col + "00", lineWidth: 2, priceLineVisible: true });
      T.series.main.setData(bars.map(b => ({ time: b.time, value: b.c })));
    }
    if (T.show.vol) {
      T.series.vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 }, borderVisible: false });
      T.series.vol.setData(bars.map((b, i) => ({ time: b.time, value: b.v, color: (b.c >= (i ? bars[i - 1].c : b.o)) ? "rgba(48,209,88,.35)" : "rgba(255,69,58,.35)" })));
    }
    if (T.show.sma20 && bars.length > 20) { T.series.sma20 = chart.addLineSeries({ color: BLUE, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }); T.series.sma20.setData(sma(bars, 20)); }
    if (T.show.sma50 && bars.length > 50) { T.series.sma50 = chart.addLineSeries({ color: "#bf5af2", lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }); T.series.sma50.setData(sma(bars, 50)); }
    if (T.show.vwap && intraday) { T.series.vwap = chart.addLineSeries({ color: AMBER, lineWidth: 1, lineStyle: LW.LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }); T.series.vwap.setData(vwap(bars)); }
    // agent fills as markers (only those inside the visible range)
    const fills = ctx().journal().filter(r => r.symbol === T.sym && r.date);
    const t0 = bars[0].time, t1 = Math.max(bars[bars.length - 1].time, Math.floor(Date.now() / 1000)) + 86400;
    const fillTime = r => r.ts ? +r.ts : Math.floor(new Date(`${r.date}T${r.time_et || "12:00"}:00-04:00`).getTime() / 1000);
    const markers = fills.map(r => ({ ts: fillTime(r), r })).filter(m => m.ts >= t0 && m.ts <= t1)
      .map(m => { const near = bars.reduce((a, b) => Math.abs(b.time - m.ts) < Math.abs(a.time - m.ts) ? b : a, bars[0]); const sell = m.r.side === "sell";
        const amt = sell ? (+m.r.proceeds || 0) : (+m.r.notional || 0);
        return { time: near.time, position: sell ? "aboveBar" : "belowBar", color: sell ? AMBER : UP,
                 shape: sell ? "arrowDown" : "arrowUp",
                 text: `${sell ? "SELL" : "BUY"} ${money(amt, 0)} @ ${money(+m.r.price)}` }; })
      .sort((a, b) => a.time - b.time);
    if (markers.length) T.series.main.setMarkers(markers);
    T.profile = volumeProfile(bars.filter(b => b.v > 0));
    drawWorking();
    drawLevels();
    drawEntry();
    drawClock();
    drawPosition();
    // the profile is painted on our own canvas, so it has to follow every pan, zoom and resize
    const repaint = () => drawLiquidity();
    chart.timeScale().subscribeVisibleLogicalRangeChange(repaint);
    requestAnimationFrame(repaint);
    chart.subscribeCrosshairMove(param => {
      const read = $("#t-read"); if (!read) return;
      if (!param.time || !param.seriesData || !param.seriesData.get(T.series.main)) { T.cursorPrice = null; read.innerHTML = HINT; updatePL(c.price); return; }
      const d = param.seriesData.get(T.series.main); const bar = bars.find(b => b.time === param.time) || {}; const price = d.close ?? d.value; T.cursorPrice = price;
      const vol = bar.v != null ? bar.v.toLocaleString() : "—"; const when = intraday ? fmtNY(param.time * 1000, true) + " ET" : fmtDay(param.time * 1000);
      const chg = bar.o ? ((bar.c / bar.o - 1) * 100) : null;
      read.innerHTML = `<span class="dim">${esc(when)}</span> O <b class="num">${money(bar.o)}</b> H <b class="num">${money(bar.h)}</b> L <b class="num">${money(bar.l)}</b> C <b class="num" style="color:${chg >= 0 ? UP : DOWN}">${money(bar.c)}</b> <span class="dim">Vol</span> <b class="num">${vol}</b>` + (T.entry ? ` <span class="dim">· vs buy-in</span> <b class="num" style="color:${price >= T.entry ? UP : DOWN}">${signed(price - T.entry)} (${pct((price / T.entry - 1) * 100)})</b>` : "");
      updatePL(price);
    });
    chart.timeScale().fitContent();
    if (view) { try { chart.timeScale().setVisibleLogicalRange(view); } catch (e) {} }
    T.resize = () => { if (T.chart && host) { T.chart.applyOptions({ width: host.clientWidth, height: host.clientHeight }); drawLiquidity(); } };
    window.addEventListener("resize", T.resize);
    T.lastPrice = c.price; updatePL(c.price);
    pollPrice();                       // start moving immediately instead of waiting for the timer
  }

  // ---------------------------------------------------------------------------------------------
  // LIQUIDITY: a volume profile. Bucket every visible bar's volume into price bins and draw them
  // as horizontal bars down the right edge. This is the honest version of "where is the liquidity":
  // the widest bin is the price at which the most stock actually changed hands.
  function volumeProfile(bars, bins = 48) {
    const lo = Math.min(...bars.map(b => b.l)), hi = Math.max(...bars.map(b => b.h));
    if (!(hi > lo)) return null;
    const step = (hi - lo) / bins, vol = new Array(bins).fill(0);
    for (const b of bars) {
      // spread each bar's volume across the bins its range covers, so a wide bar does not all
      // land on its close
      const a = Math.max(0, Math.floor((b.l - lo) / step)), z = Math.min(bins - 1, Math.floor((b.h - lo) / step));
      const share = (b.v || 0) / (z - a + 1);
      for (let i = a; i <= z; i++) vol[i] += share;
    }
    const total = vol.reduce((x, y) => x + y, 0);
    if (!total) return null;
    let poc = 0;
    for (let i = 1; i < bins; i++) if (vol[i] > vol[poc]) poc = i;
    // value area: grow out from the point of control until 70% of the volume is inside
    let lowI = poc, highI = poc, acc = vol[poc];
    while (acc < total * 0.7 && (lowI > 0 || highI < bins - 1)) {
      const below = lowI > 0 ? vol[lowI - 1] : -1, above = highI < bins - 1 ? vol[highI + 1] : -1;
      if (above >= below) { highI++; acc += vol[highI]; } else { lowI--; acc += vol[lowI]; }
    }
    const at = i => lo + step * (i + 0.5);
    return { lo, hi, step, vol, max: vol[poc], poc: at(poc), vah: at(highI), val: at(lowI), total };
  }

  function drawLiquidity() {
    const cv = $("#t-liq"), host = $("#t-chart"), s = T.series.main;
    if (!cv || !host || !s) return;
    const dpr = window.devicePixelRatio || 1, w = host.clientWidth, h = host.clientHeight;
    cv.width = w * dpr; cv.height = h * dpr; cv.style.width = w + "px"; cv.style.height = h + "px";
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    const legend = $("#t-legend");
    if (!T.show.liq || !T.profile) { if (legend) legend.hidden = true; return; }
    const p = T.profile, maxW = Math.min(140, w * 0.22), x0 = w - 64;   // stop short of the price axis
    g.globalAlpha = 1;
    // the value area as a soft band behind everything
    const yTop = s.priceToCoordinate(p.vah), yBot = s.priceToCoordinate(p.val);
    if (yTop != null && yBot != null) {
      g.fillStyle = "rgba(10,132,255,.07)";
      g.fillRect(0, Math.min(yTop, yBot), w, Math.abs(yBot - yTop));
    }
    for (let i = 0; i < p.vol.length; i++) {
      const price = p.lo + p.step * (i + 0.5), y = s.priceToCoordinate(price);
      if (y == null || y < 0 || y > h) continue;
      const bw = (p.vol[i] / p.max) * maxW;
      const inVA = price >= p.val && price <= p.vah;
      g.fillStyle = inVA ? "rgba(10,132,255,.30)" : "rgba(139,152,169,.20)";
      const bh = Math.max(1, (s.priceToCoordinate(p.lo) - s.priceToCoordinate(p.lo + p.step)) || 2);
      g.fillRect(x0 - bw, y - bh / 2, bw, Math.max(1, bh - 1));
    }
    // the point of control: the price the market kept coming back to
    const yPoc = s.priceToCoordinate(p.poc);
    if (yPoc != null) {
      g.fillStyle = "rgba(255,179,64,.85)";
      g.fillRect(x0 - maxW, yPoc - 1, maxW, 2);
      g.font = "600 10px -apple-system, BlinkMacSystemFont, Inter, sans-serif";
      g.fillStyle = "#ffb340"; g.textAlign = "right";
      g.textAlign = "left";
      g.fillText("POC " + money(p.poc), x0 - maxW + 2, yPoc - 5);   // left of the profile, clear of the buy-in label
    }
    if (legend) {
      legend.hidden = false;
      legend.innerHTML = `<b>Liquidity</b> most traded <b class="num">${money(p.poc)}</b> · value area <b class="num">${money(p.val)}</b>–<b class="num">${money(p.vah)}</b>`;
    }
  }

  // LEVELS: the handful of prices every day-trader actually watches.
  function drawLevels() {
    const s = T.series.main; if (!s) return;
    (T.series.levelLines || []).forEach(l => { try { s.removePriceLine(l); } catch (e) {} });
    T.series.levelLines = [];
    if (!T.show.levels || !T.data) return;
    const LWs = window.LightweightCharts.LineStyle;
    const bars = T.data.bars || []; if (!bars.length) return;
    const dayOf = ms => new Date(ms).toLocaleDateString("en-US", { timeZone: "America/New_York" });
    const last = dayOf(bars[bars.length - 1].t);
    const today = bars.filter(b => dayOf(b.t) === last);
    const prior = bars.filter(b => dayOf(b.t) !== last);
    const add = (price, color, title, style) => {
      if (!(price > 0)) return;
      T.series.levelLines.push(s.createPriceLine({ price: +price, color, lineWidth: 1,
        lineStyle: style ?? LWs.Dashed, axisLabelVisible: true, title }));
    };
    // the quote carries the exchange's own session figures; they beat anything derived from bars
    const q = T.quote || ctx().quote(T.sym) || {};
    if (today.length) add(today[0].o, "rgba(139,152,169,.9)", "open", LWs.Dotted);
    add(q.dayHigh != null ? +q.dayHigh : (today.length ? Math.max(...today.map(b => b.h)) : 0),
        "rgba(48,209,88,.55)", "day high", LWs.Dotted);
    add(q.dayLow != null ? +q.dayLow : (today.length ? Math.min(...today.map(b => b.l)) : 0),
        "rgba(255,69,58,.55)", "day low", LWs.Dotted);
    add(q.prevClose != null ? +q.prevClose : (prior.length ? prior[prior.length - 1].c : 0),
        "rgba(191,90,242,.8)", "prev close", LWs.Dashed);
  }

  // CLOCK: every position is sold after max_hold_minutes, so show how long this one has left.
  function drawClock() {
    const el = $("#t-clock"); if (!el) return;
    const pos = ctx().positions()[T.sym];
    const limit = +(ctx().guardrails().max_hold_minutes || 0);
    const openedTs = pos && (pos.opened_ts || pos.last_buy_ts);
    if (!pos || !limit || !openedTs) { el.hidden = true; T.clockAt = null; return; }
    const heldMin = (Date.now() / 1000 - +openedTs) / 60;
    const leftMin = limit - heldMin;
    T.clockAt = (+openedTs + limit * 60) * 1000;
    el.hidden = false;
    if (leftMin <= 0) { el.textContent = "past the " + limit + "-min limit — selling"; el.className = "t-clock over"; return; }
    const m = Math.floor(leftMin), sec = Math.floor((leftMin - m) * 60);
    el.textContent = `sold in ${m}:${String(sec).padStart(2, "0")}`;
    el.className = "t-clock" + (leftMin <= 5 ? " soon" : "");
    el.title = `Held ${Math.floor(heldMin)} min of the ${limit}-minute maximum`;
  }

  // Standing orders drawn where they sit: the levels the agent is waiting for, on the same chart
  // as the fills it already made. Buy levels green, protective levels red, profit targets amber.
  const ORDER_LINE = { buy_limit: [UP, "Buy dip"], buy_stop: [UP, "Buy break"], take_profit: [AMBER, "Take profit"], stop_loss: [DOWN, "Stop"], trailing_stop: [DOWN, "Trail stop"] };
  function drawWorking() {
    const s = T.series.main; if (!s) return;
    (T.series.orderLines || []).forEach(l => { try { s.removePriceLine(l); } catch (e) {} });
    T.series.orderLines = [];
    if (!T.show.orders) return;
    (ctx().working() || []).filter(o => o.ticker === T.sym && o.price > 0).forEach(o => {
      const [color, label] = ORDER_LINE[o.kind] || [BLUE, o.kind];
      const size = (o.kind === "buy_limit" || o.kind === "buy_stop")
        ? money(o.usd, 0) : `${Math.round(o.pct_of_position)}%`;
      T.series.orderLines.push(s.createPriceLine({
        price: +o.price, color, lineWidth: 1, lineStyle: window.LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true, title: `${label} ${size}` }));
    });
  }

  function drawEntry() {
    const s = T.series.main; if (!s) return;
    if (T.series.entryLine) { try { s.removePriceLine(T.series.entryLine); } catch (e) {} T.series.entryLine = null; }
    if (T.series.zone) { try { T.chart.removeSeries(T.series.zone); } catch (e) {} T.series.zone = null; }
    if (!T.show.buyin || !T.entry || !T.data) { updatePL(T.lastPrice); return; }
    const pos = ctx().positions()[T.sym];
    // Short label on purpose: the long one collided with the POC label and the price tag at the
    // same height and became unreadable. The number lives in the badge at the top instead.
    const label = pos && T.entryMode === "auto" ? "YOU BOUGHT HERE" : "what-if";
    T.series.entryLine = s.createPriceLine({ price: T.entry, color: AMBER, lineWidth: 3,
      lineStyle: window.LightweightCharts.LineStyle.Solid, axisLabelVisible: true, title: label });
    // profit / loss zones: translucent baseline around the entry price
    const bars = T.data.bars.map(b => ({ time: Math.floor(b.t / 1000), value: b.c }));
    T.series.zone = T.chart.addBaselineSeries({ baseValue: { type: "price", price: T.entry }, topLineColor: "rgba(0,0,0,0)", bottomLineColor: "rgba(0,0,0,0)", topFillColor1: "rgba(48,209,88,.26)", topFillColor2: "rgba(48,209,88,.04)", bottomFillColor1: "rgba(255,69,58,.04)", bottomFillColor2: "rgba(255,69,58,.26)", priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    T.series.zone.setData(bars);
    updatePL(T.lastPrice);
  }

  function updatePL(price) {
    const el = $("#t-pl"); if (!el || !T.data) return; price = price ?? T.data.price;
    const pos = ctx().positions()[T.sym]; const entry = T.entry;
    if (!entry || !price) { el.innerHTML = ""; return; }
    const shares = T.size ? T.size / entry : (pos && T.entryMode === "auto" ? pos.qty : null);
    const perShare = price - entry, perPct = (price / entry - 1) * 100; const col = perShare >= 0 ? UP : DOWN;
    const dollars = shares ? perShare * shares : null; const basis = shares ? shares * entry : null;
    el.innerHTML = `<div><span class="dim">${pos && T.entryMode === "auto" ? "Your position" : "What-if"}</span> ${shares ? `<b class="num">${shares.toFixed(4)} sh</b> <span class="dim">·</span> <b class="num">${money(basis)}</b> in` : `<span class="dim">enter a size to see dollars</span>`}</div>
      <div><span class="dim">At ${money(price)}:</span> <b class="num" style="color:${col}">${signed(perShare)}/sh (${pct(perPct)})</b>${dollars != null ? ` <span class="dim">→</span> <b class="num" style="color:${col}">${signed(dollars)}</b>` : ""}</div>
      <div class="dim">Break-even ${money(entry)} · ${perShare >= 0 ? "in profit above" : "in loss below"} the amber line</div>`;
  }

  window.SATrade = { open, close };
})();
