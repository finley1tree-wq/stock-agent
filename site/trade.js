/* Full-screen trading view: candles/line, volume, SMA/VWAP, crosshair readout, buy-in line with profit/loss zones,
   agent buy/sell markers, pan/zoom. Uses TradingView Lightweight Charts 4.x (loaded in index.html). */
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
  const T = { sym: null, range: "1d", interval: null, type: "candles", show: { vol: true, sma20: false, sma50: false, vwap: false, buyin: true }, data: null, chart: null, series: {}, entry: null, entryMode: "auto", size: null, seq: 0, resize: null };
  const prefs = (() => { try { return JSON.parse(localStorage.getItem("sa.trade") || "{}"); } catch (e) { return {}; } })();
  Object.assign(T, { range: prefs.range || "1d", type: prefs.type || "candles", show: { ...T.show, ...(prefs.show || {}) } });
  const savePrefs = () => { try { localStorage.setItem("sa.trade", JSON.stringify({ range: T.range, type: T.type, show: T.show })); } catch (e) {} };

  function ctx() { return window.SA || { positions: () => ({}), journal: () => [], quote: () => null }; }

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
        <div class="t-price"><span class="num" id="t-price">…</span><span id="t-chg" class="t-chg"></span></div>
      </div>
      <div class="t-bar">
        <div class="chips" id="t-ranges">${RANGES.map(r => `<button data-r="${r}" aria-pressed="${r === T.range}">${RLABEL[r]}</button>`).join("")}</div>
        <div class="chips" id="t-intervals"></div>
        <div class="chips" id="t-type"><button data-t="candles" aria-pressed="${T.type === "candles"}">Candles</button><button data-t="line" aria-pressed="${T.type === "line"}">Line</button></div>
        <div class="chips" id="t-toggles">
          <button data-k="vol" aria-pressed="${T.show.vol}">Vol</button><button data-k="sma20" aria-pressed="${T.show.sma20}">SMA 20</button><button data-k="sma50" aria-pressed="${T.show.sma50}">SMA 50</button><button data-k="vwap" aria-pressed="${T.show.vwap}">VWAP</button><button data-k="buyin" aria-pressed="${T.show.buyin}">Buy-in</button>
        </div>
      </div>
      <div class="t-read" id="t-read"><span class="dim">Move over the chart for O / H / L / C / volume and P/L at that price. Drag to pan, pinch or scroll to zoom.</span></div>
      <div class="t-chart" id="t-chart"></div>
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
    $("#t-ranges").addEventListener("click", e => { const b = e.target.closest("button[data-r]"); if (!b) return; T.range = b.dataset.r; T.interval = null; pressed("#t-ranges", "r", T.range); savePrefs(); load(); });
    $("#t-type").addEventListener("click", e => { const b = e.target.closest("button[data-t]"); if (!b) return; T.type = b.dataset.t; pressed("#t-type", "t", T.type); savePrefs(); draw(); });
    $("#t-toggles").addEventListener("click", e => { const b = e.target.closest("button[data-k]"); if (!b) return; T.show[b.dataset.k] = !T.show[b.dataset.k]; b.setAttribute("aria-pressed", T.show[b.dataset.k]); savePrefs(); draw(); });
    $("#t-entry").addEventListener("change", e => { const v = parseFloat(e.target.value); if (v > 0) { T.entry = v; T.entryMode = "manual"; drawEntry(); } });
    $("#t-size").addEventListener("change", e => { const v = parseFloat(e.target.value); T.size = v > 0 ? v : null; updatePL(T.lastPrice); });
    $("#t-entry-reset").addEventListener("click", () => { T.entryMode = "auto"; T.entry = null; T.size = null; $("#t-size").value = ""; drawEntry(); });
    $("#t-entry-cursor").addEventListener("click", () => { if (T.cursorPrice) { T.entry = +T.cursorPrice.toFixed(2); T.entryMode = "manual"; $("#t-entry").value = T.entry; drawEntry(); } });
    load();
  }
  function pressed(sel, attr, val) { document.querySelectorAll(`${sel} button`).forEach(b => b.setAttribute("aria-pressed", b.dataset[attr] === val)); }
  function escClose(e) { if (e.key === "Escape") close(); }
  function close() { if (T.chart) { try { T.chart.remove(); } catch (e) {} T.chart = null; } if (T.resize) { window.removeEventListener("resize", T.resize); T.resize = null; } $("#trade-root").innerHTML = ""; document.body.style.overflow = ""; document.removeEventListener("keydown", escClose); }

  async function load() {
    const my = ++T.seq; const read = $("#t-read"); if (read) read.innerHTML = `<span class="dim">Loading ${esc(T.sym)} ${RLABEL[T.range]}…</span>`;
    const url = `/api/chart?symbol=${encodeURIComponent(T.sym)}&range=${T.range}${T.interval ? "&interval=" + T.interval : ""}`;
    let c = null; try { const r = await fetch(url, { cache: "no-store" }); c = r.ok ? await r.json() : null; } catch (e) { c = null; }
    if (my !== T.seq || !$("#t-chart")) return;
    if (!c || c.error || !(c.bars || []).length) { $("#t-read").innerHTML = `<span style="color:${DOWN}">No chart data for ${esc(T.sym)} (${esc(c?.error || "empty")}).</span>`; return; }
    T.data = c; T.interval = c.interval;
    $("#t-name").textContent = c.name || ""; $("#t-price").textContent = money(c.price);
    const cls = c.change > 0 ? "up" : c.change < 0 ? "down" : "flat";
    $("#t-chg").innerHTML = c.change != null ? `<span class="pill ${cls}">${signed(c.change)} (${pct(c.changePct)})</span> <span class="dim">${T.range === "1d" ? "today" : RLABEL[T.range]}</span>` : "";
    $("#t-intervals").innerHTML = (c.intervals || []).map(i => `<button data-i="${i}" aria-pressed="${i === c.interval}">${i}</button>`).join("");
    $("#t-intervals").onclick = e => { const b = e.target.closest("button[data-i]"); if (!b) return; T.interval = b.dataset.i; load(); };
    if (T.entryMode === "auto") { const pos = ctx().positions()[T.sym]; T.entry = pos ? pos.avg_cost : c.price; $("#t-entry").value = T.entry != null ? (+T.entry).toFixed(2) : ""; }
    draw();
    const rd = $("#t-read"); if (rd) rd.innerHTML = HINT;
  }

  function sma(bars, n) { const out = []; let sum = 0; for (let i = 0; i < bars.length; i++) { sum += bars[i].c; if (i >= n) sum -= bars[i - n].c; if (i >= n - 1) out.push({ time: bars[i].time, value: +(sum / n).toFixed(4) }); } return out; }
  function vwap(bars) { const out = []; let pv = 0, vv = 0, day = null; for (const b of bars) { const d = new Date(b.t).toLocaleDateString("en-US", { timeZone: "America/New_York" }); if (d !== day) { day = d; pv = 0; vv = 0; } const tp = (b.h + b.l + b.c) / 3; pv += tp * b.v; vv += b.v; if (vv > 0) out.push({ time: b.time, value: +(pv / vv).toFixed(4) }); } return out; }

  function draw() {
    const c = T.data; if (!c) return; const LW = window.LightweightCharts; const host = $("#t-chart"); if (!host) return;
    if (T.chart) { try { T.chart.remove(); } catch (e) {} T.chart = null; }
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
    drawEntry();
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
    T.resize = () => { if (T.chart && host) T.chart.applyOptions({ width: host.clientWidth, height: host.clientHeight }); };
    window.addEventListener("resize", T.resize);
    T.lastPrice = c.price; updatePL(c.price);
  }

  function drawEntry() {
    const s = T.series.main; if (!s) return;
    if (T.series.entryLine) { try { s.removePriceLine(T.series.entryLine); } catch (e) {} T.series.entryLine = null; }
    if (T.series.zone) { try { T.chart.removeSeries(T.series.zone); } catch (e) {} T.series.zone = null; }
    if (!T.show.buyin || !T.entry || !T.data) { updatePL(T.lastPrice); return; }
    const pos = ctx().positions()[T.sym]; const label = pos && T.entryMode === "auto" ? "your buy-in" : "buy-in";
    T.series.entryLine = s.createPriceLine({ price: T.entry, color: AMBER, lineWidth: 1, lineStyle: window.LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: label });
    // profit / loss zones: translucent baseline around the entry price
    const bars = T.data.bars.map(b => ({ time: Math.floor(b.t / 1000), value: b.c }));
    T.series.zone = T.chart.addBaselineSeries({ baseValue: { type: "price", price: T.entry }, topLineColor: "rgba(0,0,0,0)", bottomLineColor: "rgba(0,0,0,0)", topFillColor1: "rgba(48,209,88,.16)", topFillColor2: "rgba(48,209,88,.03)", bottomFillColor1: "rgba(255,69,58,.03)", bottomFillColor2: "rgba(255,69,58,.16)", priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
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
