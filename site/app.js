/* Stock Agent dashboard. Static + /api functions. No keys, no build step. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const money = (v, d = 2) => v == null || isNaN(v) ? "—" : (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (v, d = 2) => v == null || isNaN(v) ? "—" : (v > 0 ? "+" : "") + v.toFixed(d) + "%";
  const signed = (v) => v == null || isNaN(v) ? "—" : (v > 0 ? "+" : v < 0 ? "-" : "") + "$" + Math.abs(v).toFixed(2);
  const cls = (v) => v > 0.0001 ? "up" : v < -0.0001 ? "down" : "flat";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const PALETTE = ["#0a84ff", "#30d158", "#ffb340", "#bf5af2", "#64d2ff", "#ff9f0a", "#ff375f", "#5e5ce6", "#ac8e68", "#98989d"];
  const state = { data: {}, quotes: {}, custom: [], tab: "holdings", timer: null };
  window.SA = { positions: () => (state.data.portfolio && state.data.portfolio.positions) || {}, journal: () => state.data.journal || [], quote: (s) => state.quotes[s] || null,
    working: () => ((state.data.signals || {}).working_orders) || [],
    guardrails: () => ((state.data.signals || {}).guardrails) || {} };

  try { state.custom = JSON.parse(localStorage.getItem("sa.custom") || "[]"); } catch (e) { state.custom = []; }
  const saveCustom = () => { try { localStorage.setItem("sa.custom", JSON.stringify(state.custom)); } catch (e) {} };

  // ---------- data ----------
  async function getJSON(url, fallback) { try { const r = await fetch(url, { cache: "no-store" }); if (!r.ok) return fallback; return await r.json(); } catch (e) { return fallback; } }
  async function getText(url) { try { const r = await fetch(url, { cache: "no-store" }); return r.ok ? await r.text() : ""; } catch (e) { return ""; } }

  async function loadData() {
    const [portfolio, st, journal, signals, lessons, log] = await Promise.all([
      getJSON("/data/portfolio.json", {}), getJSON("/data/state.json", {}), getJSON("/data/journal.json", []),
      getJSON("/data/signals.json", {}), getText("/data/lessons.md"), getText("/data/log.md")]);
    state.data = { portfolio, st, journal, signals, lessons, log };
  }

  function allSymbols() {
    const d = state.data; const set = new Set();
    Object.keys(d.portfolio.positions || {}).forEach(s => set.add(s));
    Object.values(d.signals.watchlist || {}).flat().forEach(s => set.add(s));
    (d.signals.allowed || []).forEach(s => set.add(s));
    state.custom.forEach(s => set.add(s));
    return [...set];
  }

  async function loadQuotes() {
    const syms = allSymbols(); if (!syms.length) return;
    const chunks = []; for (let i = 0; i < syms.length; i += 20) chunks.push(syms.slice(i, i + 20));
    const res = await Promise.all(chunks.map(c => getJSON("/api/quotes?symbols=" + encodeURIComponent(c.join(",")), { quotes: [] })));
    res.forEach(r => (r.quotes || []).forEach(q => { if (q && q.symbol) state.quotes[q.symbol] = q; }));
  }

  // ---------- sparkline ----------
  function spark(canvas, points, prevClose, up) {
    const dpr = window.devicePixelRatio || 1; const w = canvas.clientWidth || 96, h = canvas.clientHeight || 30;
    canvas.width = w * dpr; canvas.height = h * dpr; const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    if (!points || points.length < 2) { ctx.strokeStyle = "#3a4656"; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke(); return; }
    const ys = points.map(p => p.c); let min = Math.min(...ys), max = Math.max(...ys);
    if (prevClose != null) { min = Math.min(min, prevClose); max = Math.max(max, prevClose); }
    if (max - min < 1e-9) { max += 1; min -= 1; }
    const X = i => (i / (points.length - 1)) * (w - 2) + 1, Y = v => h - 3 - ((v - min) / (max - min)) * (h - 6);
    const color = up === null ? "#8b98a9" : up ? "#30d158" : "#ff453a";
    if (prevClose != null) { ctx.strokeStyle = "rgba(139,152,169,.45)"; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(0, Y(prevClose)); ctx.lineTo(w, Y(prevClose)); ctx.stroke(); ctx.setLineDash([]); }
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.lineJoin = "round"; ctx.beginPath();
    points.forEach((p, i) => i ? ctx.lineTo(X(i), Y(p.c)) : ctx.moveTo(X(i), Y(p.c))); ctx.stroke();
    ctx.fillStyle = color; ctx.beginPath(); ctx.arc(X(points.length - 1), Y(ys[ys.length - 1]), 2, 0, Math.PI * 2); ctx.fill();
  }

  function bigChart(canvas, c) {
    const dpr = window.devicePixelRatio || 1; const w = canvas.clientWidth || 500, h = canvas.clientHeight || 240;
    canvas.width = w * dpr; canvas.height = h * dpr; const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
    const pts = c.points || []; if (pts.length < 2) { ctx.fillStyle = "#8b98a9"; ctx.font = "13px -apple-system, sans-serif"; ctx.fillText("No chart data", 12, h / 2); return; }
    const base = c.range === "1d" ? c.prevClose : c.rangeStart; const ys = pts.map(p => p.c);
    let min = Math.min(...ys), max = Math.max(...ys); if (base != null) { min = Math.min(min, base); max = Math.max(max, base); }
    const pad = (max - min) * 0.08 || 1; min -= pad; max += pad;
    const L = 8, R = 62, T = 10, B = 26; const X = i => L + (i / (pts.length - 1)) * (w - L - R), Y = v => T + (1 - (v - min) / (max - min)) * (h - T - B);
    const up = c.change == null ? null : c.change >= 0; const color = up === null ? "#8b98a9" : up ? "#30d158" : "#ff453a";
    ctx.strokeStyle = "rgba(255,255,255,.06)"; ctx.fillStyle = "#8b98a9"; ctx.font = "11px -apple-system, sans-serif"; ctx.textAlign = "left";
    for (let g = 0; g <= 4; g++) { const v = min + (max - min) * g / 4, y = Y(v); ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(w - R + 4, y); ctx.stroke(); ctx.fillText(v >= 1000 ? v.toFixed(0) : v.toFixed(2), w - R + 8, y + 4); }
    if (base != null) { ctx.strokeStyle = "rgba(139,152,169,.6)"; ctx.setLineDash([3, 4]); ctx.beginPath(); ctx.moveTo(L, Y(base)); ctx.lineTo(w - R + 4, Y(base)); ctx.stroke(); ctx.setLineDash([]); }
    const grad = ctx.createLinearGradient(0, T, 0, h - B); grad.addColorStop(0, color + "55"); grad.addColorStop(1, color + "00");
    ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(X(i), Y(p.c)) : ctx.moveTo(X(i), Y(p.c))); ctx.lineTo(X(pts.length - 1), h - B); ctx.lineTo(X(0), h - B); ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(X(i), Y(p.c)) : ctx.moveTo(X(i), Y(p.c))); ctx.stroke();
    const fmt = c.range === "1d" ? (t) => new Date(t).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }) : (t) => new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });
    ctx.fillStyle = "#8b98a9"; ctx.textAlign = "center"; [0, 0.25, 0.5, 0.75, 1].forEach(f => { const i = Math.round(f * (pts.length - 1)); ctx.fillText(fmt(pts[i].t), X(i), h - 8); });
  }

  // ---------- rows ----------
  function stockRow(sym, extra) {
    const q = state.quotes[sym] || {}; const pos = (state.data.portfolio.positions || {})[sym];
    const row = el("button", "row" + (pos ? " held" : "")); row.type = "button";
    row.setAttribute("aria-label", `Open ${sym}${pos ? " (you hold this)" : ""}`);
    const val = pos ? pos.qty * (q.price ?? pos.avg_cost) : null;
    const id = el("div", "id", `<span class="sym">${esc(sym)}${pos ? `<span class="heldchip" title="The agent holds this">${money(val, 0)}</span>` : ""}</span><span class="nm">${esc(q.name || extra?.name || "")}</span>`);
    const cv = el("canvas"); const hold = el("div", "hold");
    if (pos) { const live = q.price != null ? pos.qty * q.price : pos.qty * pos.avg_cost; const pl = q.price != null ? (q.price / pos.avg_cost - 1) * 100 : null;
      hold.innerHTML = `<b class="num">${money(live)}</b>${pos.qty.toFixed(4)} sh · avg ${money(pos.avg_cost)} · <span style="color:${pl > 0 ? "var(--up)" : pl < 0 ? "var(--down)" : "inherit"}">${pct(pl)}</span>`; }
    else if (extra?.hint) hold.innerHTML = `<b>${esc(extra.hint)}</b>${esc(extra.sub || "")}`;
    const px = el("div", "px num", q.price != null ? money(q.price) : (q.error ? "n/a" : "…"));
    const ch = el("div", "chg"); ch.appendChild(el("span", "pill num " + (q.change == null ? "flat" : cls(q.change)), q.change == null ? "—" : `${signed(q.change)}<br><span style="font-size:11.5px;opacity:.85">${pct(q.changePct)}</span>`));
    row.append(id, cv, hold, px, ch); row.addEventListener("click", () => openSheet(sym)); row.addEventListener("dblclick", () => { closeSheet(); if (window.SATrade) window.SATrade.open(sym); });
    requestAnimationFrame(() => spark(cv, q.points, q.prevClose, q.change == null ? null : q.change >= 0));
    return row;
  }

  function renderHoldings() {
    const box = $("#holdings"); box.innerHTML = ""; const pos = state.data.portfolio.positions || {}; const syms = Object.keys(pos);
    $("#holdings-count").textContent = syms.length ? `${syms.length}` : "";
    if (!syms.length) { box.appendChild(el("div", "empty", "<b>No positions yet.</b><br>The agent's first pretend buys will appear here after its first market-hours check.")); return; }
    const head = el("div", "row head"); head.innerHTML = "<div>Symbol</div><div>Today</div><div>Position</div><div style='text-align:right'>Price</div><div style='text-align:right'>Change</div>"; box.appendChild(head);
    syms.map(s => [s, pos[s]]).sort((a, b) => (b[1].qty * (state.quotes[b[0]]?.price || b[1].avg_cost)) - (a[1].qty * (state.quotes[a[0]]?.price || a[1].avg_cost))).forEach(([s]) => box.appendChild(stockRow(s)));
  }

  // Standing orders: the levels the agent is waiting for. Distance is recomputed from the LIVE
  // quote on every 60s refresh, so this keeps moving between checks even though the book does not.
  const KIND_LABEL = { buy_limit: "Buy dip", buy_stop: "Buy break", take_profit: "Take profit", stop_loss: "Stop loss", trailing_stop: "Trail stop" };
  function renderWorking() {
    const sec = $("#working-section"), box = $("#working"); if (!sec || !box) return;
    const rows = (state.data.signals || {}).working_orders || [];
    sec.hidden = !rows.length; $("#working-count").textContent = rows.length ? `${rows.length}` : "";
    if (!rows.length) return;
    box.innerHTML = "";
    rows.map(o => {
      const live = state.quotes[o.ticker]?.price ?? o.last;
      return { ...o, away: live && o.price ? (o.price / live - 1) * 100 : null };
    }).sort((a, b) => Math.abs(a.away ?? 999) - Math.abs(b.away ?? 999)).forEach(o => {
      const isBuy = o.kind === "buy_limit" || o.kind === "buy_stop";
      const size = isBuy ? money(o.usd) : `${Math.round(o.pct_of_position)}% of position`;
      const near = o.away != null && Math.abs(o.away) <= 1.5;
      const w = el("div", "w");
      w.innerHTML = `<div class="k ${isBuy ? "buy" : "sell"}">${esc(KIND_LABEL[o.kind] || o.kind)}</div>
        <div><b>${esc(o.ticker)}</b> · ${esc(size)}${o.trail_pct ? ` · trails ${o.trail_pct}%` : ""}
        <div class="why">${esc(o.why || "")}</div></div>
        <div class="lvl"><b class="num">${money(o.price)}</b><div class="away${near ? " near" : ""}">${o.away == null ? "" : `${o.away > 0 ? "+" : ""}${o.away.toFixed(2)}% away${near ? " · close" : ""}`}</div></div>`;
      w.addEventListener("click", () => openSheet(o.ticker));
      box.appendChild(w);
    });
  }

  function renderWatchlist() {
    const box = $("#watchlist"); box.innerHTML = ""; const wl = state.data.signals.watchlist || {};
    const sectors = Object.entries(wl);
    if (state.custom.length) sectors.unshift(["my picks", state.custom]);
    const heldSyms = Object.keys(state.data.portfolio.positions || {});
    if (heldSyms.length) sectors.unshift(["holdings", heldSyms]);
    const extras = (state.data.signals.allowed || []).filter(s => !Object.values(wl).flat().includes(s) && !state.custom.includes(s));
    if (extras.length) sectors.push(["from congress & insider filings", extras]);
    if (!sectors.length) { box.appendChild(el("div", "empty", "No watchlist yet.")); return; }
    sectors.forEach(([name, syms]) => {
      const nHeld = syms.filter(s => (state.data.portfolio.positions || {})[s]).length;
      const sec = el("div", "section"); sec.appendChild(el("h3", null, `${esc(name.replace(/_/g, " "))} <span class="count">${syms.length}${nHeld ? ` · <span class="heldcount">${nHeld} held</span>` : ""}</span>`));
      const heldNow = state.data.portfolio.positions || {};
      syms = [...syms].sort((a, b) => (heldNow[b] ? 1 : 0) - (heldNow[a] ? 1 : 0));
      const list = el("div", "list"); syms.forEach(s => { const pr = state.data.signals.insider_pressure?.[s] ?? state.data.signals.congress_pressure?.[s]; list.appendChild(stockRow(s, name === "from congress & insider filings" && pr != null ? { hint: `net buying ${pr > 0 ? "+" : ""}${pr}`, sub: "insider / congress score" } : null)); });
      sec.appendChild(list); box.appendChild(sec);
    });
  }

  function pressureBars(target, map) {
    target.innerHTML = ""; const entries = Object.entries(map || {}).slice(0, 10);
    if (!entries.length) { target.appendChild(el("div", "empty", "No data")); return; }
    const mx = Math.max(...entries.map(([, v]) => Math.abs(v))) || 1;
    entries.forEach(([s, v]) => { const p = el("div", "p"); const pctW = Math.abs(v) / mx * 50; p.innerHTML = `<b>${esc(s)}</b><div class="track"><span style="${v >= 0 ? `left:50%;background:var(--up)` : `right:50%;background:var(--down)`};width:${pctW}%"></span></div><span class="v num">${v > 0 ? "+" : ""}${v}</span>`; p.style.cursor = "pointer"; p.addEventListener("click", () => openSheet(s)); target.appendChild(p); });
  }

  // Who we follow, and - the part that matters - whether their record is worth anything.
  // A ranked list looks authoritative whether or not it means something, so the verdict is
  // rendered first and the names are greyed out when nobody clears the bar.
  function renderInvestors() {
    const box = $("#investors"); if (!box) return;
    const sg = state.data.signals || {};
    const lb = sg.disclosure_leaderboard || [], sigv = sg.disclosure_significance || {};
    const wm = sg.wallet_moves || [], ws = sg.wallet_status || {};
    $("#investors-count").textContent = lb.length ? `${lb.length} scored` : "";
    if (!lb.length && !wm.length) {
      box.innerHTML = `<div class="empty" style="padding:14px">No disclosed portfolios scored yet.<br>
        <span style="font-size:12.5px">Congress filings are scored automatically. To follow crypto traders, add wallet
        addresses to <b>wallets.txt</b> in the repo.</span></div>`;
      return;
    }
    const proven = (sigv.members_weighted || 0) > 0;
    const verdict = sigv.verdict ? `
      <div class="note" style="margin-bottom:12px">
        <b>${proven ? "Some records clear the bar." : "None of these beat luck."}</b>
        ${esc(sigv.verdict)}${sigv.best_t_stat != null ? ` Best t-statistic ${esc(sigv.best_t_stat)}; it needs 2.5.` : ""}
        <br><span style="font-size:12px">${esc(sigv.how_to_read || "")}</span>
      </div>` : "";
    const rows = lb.slice(0, 10).map(r => {
      const good = r.avg_excess_pct >= 0;
      return `<div class="p" style="${proven ? "" : "opacity:.72"}">
        <b>${esc(r.who)}</b>
        <span style="color:var(--muted);font-size:12.5px">${r.disclosed_buys_scored} disclosed buys${r.beat_index_rate != null ? ` · beat the index ${Math.round(r.beat_index_rate * 100)}% of the time` : ""}</span>
        <span class="v num" style="color:${good ? "var(--up)" : "var(--down)"}">${pct(r.avg_excess_pct)}</span></div>`;
    }).join("");
    const wallets = wm.length ? `
      <h4 style="margin:16px 0 6px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">On-chain traders · live</h4>
      <div class="pressure">${wm.map(m => `<div class="p"><b>${esc(m.who)}</b>
        <span style="color:var(--muted);font-size:12.5px">${esc(m.when || "")} · ${esc((m.mint || "").slice(0, 10))}…</span>
        <span class="v num" style="color:${m.side === "buy" ? "var(--up)" : "var(--down)"}">${m.side === "buy" ? "BOUGHT" : "SOLD"}</span></div>`).join("")}</div>`
      : `<h4 style="margin:16px 0 6px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">On-chain traders</h4>
         <div class="empty" style="padding:10px;font-size:12.5px">${ws.followed_total ? `${ws.followed_total} wallet(s) followed, nothing traded recently.` : "None yet — add addresses to wallets.txt in the repo."}</div>`;
    box.innerHTML = verdict +
      `<h4 style="margin:0 0 6px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Congress · excess return vs SPY, from the day each filing went public</h4>
       <div class="pressure">${rows}</div>` + wallets;
  }

  function renderPolitics() {
    const sg = state.data.signals; const note = $("#feed-note"); note.innerHTML = "";
    const fs = sg.feed_status || {};
    if (fs.congress && fs.congress !== "ok") note.appendChild(el("div", "note", `<b>Congress trade feed:</b> ${esc(fs.congress)}. ${esc(fs.congress_notes || "")} Insider filings and news still drive the agent.`));
    else if (fs.congress_source === "congresswatch") note.appendChild(el("div", "note", `<b>Congress feed:</b> free public records via CongressWatch (daily, House + Senate) with House disclosure dates from the Clerk's index. Senate rows show the trade date only. Filings can lag trades by up to 45 days.`));
    pressureBars($("#congress-pressure"), sg.congress_pressure); pressureBars($("#insider-pressure"), sg.insider_pressure);
    const ct = sg.congress_trades || []; $("#congress-count").textContent = ct.length || ""; const cbox = $("#congress"); cbox.innerHTML = "";
    if (!ct.length) cbox.appendChild(el("div", "empty", "No Congress disclosures loaded."));
    else { const t = el("table"); t.innerHTML = "<thead><tr><th>Disclosed</th><th>Member</th><th>Ticker</th><th>Type</th><th>Amount</th><th>Traded</th></tr></thead>"; const tb = el("tbody");
      ct.forEach(r => { const tr = el("tr"); tr.innerHTML = `<td class="num">${esc(r.disclosure_date || "")}</td><td>${esc(r.who || "")}<div style="color:var(--faint);font-size:12px">${esc([r.party, r.chamber].filter(Boolean).join(" · "))}</div></td><td><b>${esc(r.ticker)}</b></td><td><span class="tag ${r.type === "buy" ? "buy" : "sell"}">${r.type === "buy" ? "BUY" : "SELL"}</span></td><td>${esc(r.amount || "")}</td><td class="num">${esc(r.transaction_date || "")}</td>`; tr.style.cursor = "pointer"; tr.addEventListener("click", () => openSheet(r.ticker)); tb.appendChild(tr); }); t.appendChild(tb); cbox.appendChild(t); }
    const it = sg.insider_trades || []; $("#insider-count").textContent = it.length || ""; const ibox = $("#insiders"); ibox.innerHTML = "";
    if (!it.length) ibox.appendChild(el("div", "empty", "No insider filings loaded."));
    else { const t = el("table"); t.innerHTML = "<thead><tr><th>Filed</th><th>Insider</th><th>Ticker</th><th>Type</th><th>Shares</th><th>Price</th></tr></thead>"; const tb = el("tbody");
      it.forEach(r => { const tr = el("tr"); tr.innerHTML = `<td class="num">${esc((r.filing_date || "").slice(0, 10))}</td><td>${esc(r.who || "")}<div style="color:var(--faint);font-size:12px">${esc(r.role || "")}</div></td><td><b>${esc(r.ticker)}</b></td><td><span class="tag ${r.type === "buy" ? "buy" : "sell"}">${r.type === "buy" ? "BUY" : "SELL"}</span></td><td class="num">${r.shares != null ? Number(r.shares).toLocaleString() : ""}</td><td class="num">${r.price != null && r.price !== 0 ? money(+r.price) : ""}</td>`; tr.style.cursor = "pointer"; tr.addEventListener("click", () => openSheet(r.ticker)); tb.appendChild(tr); }); t.appendChild(tb); ibox.appendChild(t); }
    const people = sg.people_news || {}; const ps = $("#people-section"); const pbox = $("#people"); pbox.innerHTML = "";
    if (Object.keys(people).length) { ps.hidden = false; Object.entries(people).forEach(([name, items]) => { const c = el("div", null, `<div style="padding:12px 16px 4px;font-weight:700">${esc(name)}</div>`); const ul = el("ul", "news"); ul.style.padding = "0 16px 10px"; items.forEach(n => ul.appendChild(el("li", null, `${esc(n.title)}<div class="src">${esc(n.source || "")} · ${esc(n.when || "")}${(n.tickers || []).length ? " · " + n.tickers.map(esc).join(", ") : ""}</div>`))); c.appendChild(ul); pbox.appendChild(c); }); }
    else ps.hidden = true;
  }

  function renderActivity() {
    const j = [...(state.data.journal || [])].reverse(); $("#fills-count").textContent = j.length || ""; const box = $("#fills"); box.innerHTML = "";
    if (!j.length) box.appendChild(el("div", "empty", "No fills yet."));
    j.slice(0, 60).forEach(r => { const f = el("div", "f"); const isSell = r.side === "sell";
      f.innerHTML = `<div class="when">${esc(r.date || "")}<br>${esc(r.time_et || "")}</div><div class="what"><span class="tag ${isSell ? "sell" : "buy"}">${isSell ? "SELL" : "BUY"}</span>${r.trigger ? ` <span class="tag n" title="left as a standing order at an earlier check and filled when the price got there">${esc(KIND_LABEL[r.trigger] || r.trigger)}</span>` : ""} <b>${esc(r.symbol)}</b>${isSell ? ` ${(+r.qty).toFixed(4)} sh @ ${money(+r.price)}` : ` @ ${money(+r.price)}`}<span class="chips">${(r.signals || []).map(s => `<span>${esc(s)}</span>`).join("")}</span><div class="why">${esc(r.why || "")}</div>${r.evidence ? `<div class="ev">evidence: ${esc(r.evidence)}</div>` : ""}</div><div class="amt num">${isSell ? `${money(+r.proceeds)}<br><span style="color:${r.realized_pct >= 0 ? "var(--up)" : "var(--down)"};font-size:12.5px">${pct(+r.realized_pct)}</span>` : money(+r.notional)}</div>`;
      f.style.cursor = "pointer"; f.addEventListener("click", () => openSheet(r.symbol)); box.appendChild(f); });
    renderLearning();
    const ul = $("#lessons"); ul.innerHTML = ""; const ls = (state.data.lessons || "").split("\n").filter(l => l.startsWith("- ")).slice(-12).reverse();
    if (!ls.length) ul.appendChild(el("li", null, "Nothing learned yet. Lessons appear after the first checks."));
    ls.forEach(l => { const m = l.match(/^- (\S+) \(([^)]*)\): (.*)$/); ul.appendChild(el("li", null, m ? `<span class="d">${esc(m[1])}</span>${esc(m[3])}` : esc(l.slice(2)))); });
    const log = (state.data.log || "").trim(); const pre = $("#log");
    pre.innerHTML = log ? log.split("\n").slice(-160).map(line => { const s = esc(line); if (line.startsWith("## ")) return `<span class="h">${s}</span>`; if (line.startsWith("- BUY")) return `<span class="buy">${s}</span>`; if (line.startsWith("- SELL")) return `<span class="sell">${s}</span>`; if (line.startsWith("  (")) return `<span class="dim">${s}</span>`; return s; }).join("\n") : "No log yet.";
  }

  function renderLearning() {
    const box = $("#learning"), L = (state.data.signals || {}).learning || {};
    $("#learn-count").textContent = L.decisions_recorded ? `${L.decisions_recorded} decisions recorded` : "";
    if (!box) return;
    if (!L.decisions_graded) {
      box.innerHTML = `<div class="empty" style="padding:14px">${esc(L.note || "No decisions recorded yet.")}<br><span style="font-size:12.5px">Every check is stored with the whole list of stocks it could have bought. Once a day has passed they get graded against what actually happened.</span></div>`;
      return;
    }
    const sign = v => v == null ? "var(--muted)" : v >= 0 ? "var(--up)" : "var(--down)";
    const hasBuys = L.avg_regret_pct != null;                 // regret only exists once a graded check contains a buy
    const good = hasBuys && L.avg_regret_pct < 0;
    const tone = !hasBuys ? "var(--muted)" : good ? "var(--up)" : "var(--amber)";
    const idle = L.idle_universe_avg_pct;
    const verdict = !hasBuys
      ? `No graded check contains a buy yet, so its picking can't be judged. ${idle != null ? `While it sat out, the list it watches moved ${pct(idle)} on average.` : ""}`
      : good ? "Its picking is beating a random pick from the same list."
      : "The stocks it passed over are doing better than the ones it bought. It sees this and is adjusting.";
    const row = (label, v) => `<div>${label}<b class="num" style="color:${sign(v)}">${v == null ? "—" : pct(v)}</b></div>`;
    box.innerHTML = `
      <div class="kv" style="margin-top:0">
        ${row("Its picks", L.chosen_avg_pct)}
        ${row("What it skipped", L.skipped_avg_pct)}
        <div>Regret<b class="num" style="color:${!hasBuys ? "var(--muted)" : good ? "var(--up)" : "var(--amber)"}">${hasBuys ? pct(L.avg_regret_pct) : "—"}</b></div>
        <div>Checks graded<b class="num">${L.decisions_graded}${hasBuys ? ` <span style="color:var(--muted);font-weight:400">(${L.decisions_with_buys_graded || 0} with buys)</span>` : ""}</b></div>
      </div>
      <p style="margin:12px 0 0;font-size:13px;color:${tone}">${verdict}</p>
      ${(L.biggest_misses || []).length ? `<h4 style="margin:16px 0 6px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Biggest things it passed over</h4>
        <div class="pressure">${L.biggest_misses.slice(0, 4).map(m => `<div class="p"><b>${esc(m.ticker)}</b><span style="color:var(--muted);font-size:12.5px">${esc(m.sector || "")} · ${esc((m.ts || "").slice(5, 16))}</span><span class="v num" style="color:${sign(m.fwd_pct)}">${pct(m.fwd_pct)}</span></div>`).join("")}</div>` : ""}
      ${(L.biggest_avoided || []).length ? `<h4 style="margin:14px 0 6px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Losses it dodged by passing</h4>
        <div class="pressure">${L.biggest_avoided.slice(0, 3).map(m => `<div class="p"><b>${esc(m.ticker)}</b><span style="color:var(--muted);font-size:12.5px">${esc((m.ts || "").slice(5, 16))}</span><span class="v num" style="color:${sign(m.fwd_pct)}">${pct(m.fwd_pct)}</span></div>`).join("")}</div>` : ""}
      <p style="margin:14px 0 0;font-size:12.5px;color:var(--faint)">Sat out ${Math.round((L.idle_share || 0) * 100)}% of checks. Hit rate ${L.chosen_hit_rate != null ? Math.round(L.chosen_hit_rate * 100) + "%" : "—"} on its own picks vs ${L.skipped_hit_rate != null ? Math.round(L.skipped_hit_rate * 100) + "%" : "—"} on what it skipped.</p>`;
  }

  function renderHero() {
    const p = state.data.portfolio || {}; const pos = p.positions || {}; const st = state.data.st || {}; const sg = state.data.signals || {};
    let mv = 0, cost = 0, dayChange = 0, anyLive = false, unpriced = 0;
    Object.entries(pos).forEach(([s, x]) => { const q = state.quotes[s]; if (q?.price == null) unpriced++; const price = q?.price ?? x.avg_cost; mv += x.qty * price; cost += x.qty * x.avg_cost; if (q?.change != null) { dayChange += x.qty * q.change; anyLive = true; } });
    const held = Object.keys(pos).length;
    const cash = p.cash ?? 0, equity = cash + mv, dep = p.deposited || 0, ret = dep ? (equity / dep - 1) * 100 : null;
    $("#equity").innerHTML = `${money(equity)}<small>${dep ? pct(ret) : ""}</small>`;
    $("#equity-change").innerHTML = `<span class="pill ${anyLive ? cls(dayChange) : "flat"}">${anyLive ? `${signed(dayChange)} today` : held ? "quotes unavailable · at cost" : "no positions"}</span> <span style="color:var(--muted);font-size:13px;margin-left:8px">${dep ? `${signed(equity - dep)} all time` : ""}</span>`;
    $("#deposited").textContent = money(dep); $("#cash").textContent = money(cash); $("#realized").textContent = signed(p.realized_pnl || 0); $("#unrealized").textContent = unpriced ? "—" : signed(mv - cost);
    const alloc = $("#alloc"), legend = $("#legend"); alloc.innerHTML = ""; legend.innerHTML = "";
    const parts = Object.entries(pos).map(([s, x]) => [s, x.qty * (state.quotes[s]?.price ?? x.avg_cost)]).sort((a, b) => b[1] - a[1]); parts.push(["cash", cash]);
    parts.forEach(([s, v], i) => { const c = s === "cash" ? "#3a4656" : PALETTE[i % PALETTE.length]; const w = equity ? v / equity * 100 : 0; const sp = el("span"); sp.style.width = w + "%"; sp.style.background = c; alloc.appendChild(sp); legend.appendChild(el("span", null, `<i style="background:${c}"></i>${esc(s)} ${w.toFixed(0)}%`)); });
    // "spent" is NET new money (a sell hands its proceeds back). "deployed" is GROSS money put to
    // work. The bar showed $0 deployed on a day that bought and sold three times because it read
    // the net figure. Falls back to spent for a state.json published before deployed existed.
    const budget = sg.weekly_budget || 400, spent = st.spent || 0, deployed = st.deployed ?? spent;
    $("#week-label").textContent = st.week ? `Week ${st.week}` : "This week"; $("#week-spent").textContent = `${money(deployed)} put to work · ${money(Math.max(0, budget - spent))} left of ${money(budget, 0)}`; $("#week-bar").style.width = Math.min(100, deployed / budget * 100) + "%";
    const etDay = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" }); const sameDay = st.day === etDay;
    $("#today-spent").textContent = money(sameDay ? (st.deployed_today ?? st.spent_today ?? 0) : 0); $("#today-buys").textContent = sameDay ? st.orders_today ?? 0 : 0; $("#today-sells").textContent = sameDay ? st.sells_today ?? 0 : 0;
    $("#next-check").textContent = nextCheckText();
    const fs = sg.feed_status || {}; const fmt = v => v === "ok" ? "<span style='color:var(--up)'>live</span>" : v ? `<span style='color:var(--amber)'>${esc(v)}</span>` : "—";
    $("#feed-congress").innerHTML = fmt(fs.congress); $("#feed-insiders").innerHTML = fmt(fs.insiders);
    // The brain's reasoning is carried forward on every publish; the tick note ("tick: watching")
    // is not a decision and was what this card showed for most of the day.
    const reasoning = sg.last_reasoning || "";
    const when = sg.signalsAsOf ? ` (${new Date(sg.signalsAsOf).toLocaleTimeString("en-US", {hour: "numeric", minute: "2-digit"})})` : "";
    $("#last-reasoning").textContent = reasoning ? `Last decision${when}: ${reasoning}`
      : (sg.note && !/^tick:|^market closed$|^published without a decision$/.test(sg.note) ? `Last decision: ${sg.note}` : "");
    $("#mode").textContent = (sg.broker || "sim") === "sim" ? "SIM · pretend money" : (sg.broker || "").toUpperCase();
  }

  // The old version rounded up to the next multiple of 30 FROM MIDNIGHT, so at 11:55 it said
  // "12:00 PM" when the real next decision was due at 12:13. The gate is measured from the last
  // decision, and the interval is whatever the brain asked for - so read both from the data and
  // show a countdown, which cannot be misread against a clock in another timezone.
  function nextCheckText() {
    const sg = state.data.signals || {}, st = state.data.st || {};
    const hol = new Set(sg.holidays || []), early = new Set(sg.early_close_1pm || []);
    const et = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
    const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const trading = d => d.getDay() !== 0 && d.getDay() !== 6 && !hol.has(iso(d));
    const closeMin = d => early.has(iso(d)) ? 780 : 960;
    const mins = et.getHours() * 60 + et.getMinutes();
    const g = sg.guardrails || {};
    const every = Math.max(+g.min_decision_minutes || 6,
                   Math.min(+g.max_decision_minutes || 30, +st.next_check_minutes || +sg.run_every_minutes || 30));
    if (trading(et) && mins >= 570 && mins < closeMin(et)) {
      const last = +st.last_decision_ts || 0;
      if (!last) return "any moment";
      const dueIn = Math.round((last + every * 60 - Date.now() / 1000) / 60);
      if (dueIn <= 0) return "any moment";
      const at = new Date((last + every * 60) * 1000);
      const hhmm = at.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
      return `in ${dueIn} min · ${hhmm} ET`;
    }
    if (trading(et) && mins < 570) return "at the 9:30 AM ET open";
    const d = new Date(et); for (let i = 0; i < 14; i++) { d.setDate(d.getDate() + 1); if (trading(d)) break; }
    const tomorrow = new Date(et); tomorrow.setDate(tomorrow.getDate() + 1);
    const names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    return (iso(d) === iso(tomorrow) ? "tomorrow" : names[d.getDay()]) + " 9:30 AM ET";
  }

  function renderStatus(ok) {
    const sg = state.data.signals || {}; const as = sg.asOf ? new Date(sg.asOf) : null;
    const live = Object.values(state.quotes).some(q => q.marketState === "REGULAR");
    const paused = !!sg.paused;
    // "stale" = market open, more than 45 min since the agent last checked in, and not just the first minutes after the bell
    const et = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" })); const sinceOpen = et.getHours() * 60 + et.getMinutes() - 570;
    const ageMin = as ? (Date.now() - as.getTime()) / 60000 : null;
    const stale = live && !paused && ageMin != null && ageMin > 45 && sinceOpen > 45;
    const pill = paused ? ` <span class="pill paused" title="${esc(sg.pause_reason || "")}">PAUSED</span>` : "";
    const warn = stale ? `<br><span style="color:var(--amber)">no check for ${Math.round(ageMin)} min — the watchdog should restart it</span>` : "";
    $("#status").innerHTML = `<span class="dot${live ? " live" : ""}"></span><b>${live ? "Market open" : "Market closed"}</b>${pill}<br>agent data ${as ? esc(as.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })) : "—"} · quotes ${new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}${warn}`;
    $("#asof").textContent = as ? `Agent data as of ${as.toLocaleString()}${paused ? " · agent paused" : ""}` : "";
    const mode = $("#mode"); if (mode && paused && !/PAUSED/.test(mode.textContent)) mode.textContent += " · PAUSED";
  }

  function renderAll() { renderHero(); renderWorking(); renderHoldings(); renderWatchlist(); renderPolitics(); renderInvestors(); renderActivity(); renderStatus(); }

  // ---------- detail sheet ----------
  let sheetSym = null, sheetRange = "1d";
  async function openSheet(sym, range) {
    if (!sym) return; sheetSym = sym; sheetRange = range || (sheetSym === sym && sheetRange) || "1d";
    const root = $("#sheet-root"); root.innerHTML = "";
    const bg = el("div", "sheet-bg"); bg.addEventListener("click", closeSheet);
    const sh = el("div", "sheet"); sh.setAttribute("role", "dialog"); sh.setAttribute("aria-label", sym + " details");
    const q = state.quotes[sym] || {}; const pos = (state.data.portfolio.positions || {})[sym];
    sh.innerHTML = `<button class="close" aria-label="Close">×</button>
      <div class="title"><div class="sym">${esc(sym)}</div><div class="nm">${esc(q.name || "")}${q.exchange ? " · " + esc(q.exchange) : ""}</div></div>
      <div class="price num" id="sh-price">${q.price != null ? money(q.price) : "…"}</div>
      <div class="sub" id="sh-sub">${q.change != null ? `<span class="pill ${cls(q.change)}">${signed(q.change)} (${pct(q.changePct)})</span> today` : ""}</div>
      <div class="ranges" role="group" aria-label="Range">${["1d", "5d", "1mo", "3mo", "6mo", "1y", "5y"].map(r => `<button data-r="${r}" aria-pressed="${r === sheetRange}">${r.toUpperCase().replace("MO", "M")}</button>`).join("")}</div>
      <canvas class="chart" id="sh-chart"></canvas>
      <div class="stats" id="sh-stats"></div>
      <div class="actions" id="sh-actions"><button class="btn primary" id="sh-trade">Full-screen chart</button></div>
      <div id="sh-pos"></div>
      <h4>Headlines the agent saw</h4><ul class="news" id="sh-news"></ul>
      <h4>Agent activity in ${esc(sym)}</h4><div class="list fills" id="sh-fills"></div>`;
    root.append(bg, sh); document.body.style.overflow = "hidden";
    sh.querySelector(".close").addEventListener("click", closeSheet);
    sh.querySelector("#sh-trade").addEventListener("click", () => { closeSheet(); if (window.SATrade) window.SATrade.open(sym); });
    sh.querySelectorAll(".ranges button").forEach(b => b.addEventListener("click", () => { sheetRange = b.dataset.r; sh.querySelectorAll(".ranges button").forEach(x => x.setAttribute("aria-pressed", x === b)); drawSheetChart(sym, sheetRange); }));
    const inCustom = state.custom.includes(sym), inWatch = Object.values(state.data.signals.watchlist || {}).flat().includes(sym);
    const act = $("#sh-actions"); if (!inWatch) { const b = el("button", "btn " + (inCustom ? "" : "primary"), inCustom ? "Remove from my picks" : "Add to my picks"); b.addEventListener("click", () => { if (inCustom) state.custom = state.custom.filter(s => s !== sym); else state.custom.push(sym); saveCustom(); closeSheet(); refresh(true); }); act.appendChild(b); }
    if (pos) { const live = q.price != null ? pos.qty * q.price : null; $("#sh-pos").innerHTML = `<h4>Your pretend position</h4><div class="stats"><div>Shares<b class="num">${pos.qty.toFixed(4)}</b></div><div>Avg cost<b class="num">${money(pos.avg_cost)}</b></div><div>Value<b class="num">${live != null ? money(live) : "—"}</b></div><div>P/L<b class="num" style="color:${q.price >= pos.avg_cost ? "var(--up)" : "var(--down)"}">${q.price != null ? `${signed(live - pos.qty * pos.avg_cost)} (${pct((q.price / pos.avg_cost - 1) * 100)})` : "—"}</b></div><div>Opened<b>${esc(pos.opened || "")}</b></div></div>`; }
    const news = (state.data.signals.headlines || {})[sym] || []; const ul = $("#sh-news"); ul.innerHTML = news.length ? "" : "<li style='color:var(--muted)'>None captured at the last check.</li>"; news.forEach(n => ul.appendChild(el("li", null, `${esc(n.title)}<div class="src">${esc(n.source || "")} · ${esc(n.when || "")}</div>`)));
    const fills = (state.data.journal || []).filter(r => r.symbol === sym).reverse(); const fb = $("#sh-fills"); fb.innerHTML = fills.length ? "" : "<div class='empty'>No fills in this symbol.</div>";
    fills.forEach(r => { const isSell = r.side === "sell"; fb.appendChild(el("div", "f", `<div class="when">${esc(r.date || "")}<br>${esc(r.time_et || "")}</div><div class="what"><span class="tag ${isSell ? "sell" : "buy"}">${isSell ? "SELL" : "BUY"}</span>${r.trigger ? ` <span class="tag n" title="left as a standing order at an earlier check and filled when the price got there">${esc(KIND_LABEL[r.trigger] || r.trigger)}</span>` : ""} @ ${money(+r.price)}<div class="why">${esc(r.why || "")}</div>${r.evidence ? `<div class="ev">evidence: ${esc(r.evidence)}</div>` : ""}</div><div class="amt num">${isSell ? money(+r.proceeds) : money(+r.notional)}</div>`)); });
    drawSheetChart(sym, sheetRange);
    document.addEventListener("keydown", escClose);
  }
  function escClose(e) { if (e.key === "Escape") closeSheet(); }
  function closeSheet() { $("#sheet-root").innerHTML = ""; document.body.style.overflow = ""; document.removeEventListener("keydown", escClose); }
  let chartSeq = 0;
  async function drawSheetChart(sym, range) {
    const my = ++chartSeq;
    const c = await getJSON(`/api/chart?symbol=${encodeURIComponent(sym)}&range=${range}`, null);
    if (my !== chartSeq) return;   // a newer symbol/range request superseded this one
    const cv = $("#sh-chart"); if (!cv) return;
    if (!c || c.error) { const ctx = cv.getContext("2d"); ctx.clearRect(0, 0, cv.width, cv.height); return; }
    bigChart(cv, c);
    if (c.price != null) $("#sh-price").textContent = money(c.price);
    const label = { "1d": "today", "5d": "past 5 days", "1mo": "past month", "3mo": "past 3 months", "6mo": "past 6 months", "1y": "past year", "5y": "past 5 years" }[range];
    $("#sh-sub").innerHTML = c.change != null ? `<span class="pill ${cls(c.change)}">${signed(c.change)} (${pct(c.changePct)})</span> ${label}` : "";
    const st = $("#sh-stats"); st.innerHTML = [["Prev close", (c.prevClose ?? state.quotes[sym]?.prevClose) != null ? money(c.prevClose ?? state.quotes[sym].prevClose) : "—"], ["Day range", c.dayLow != null && c.dayHigh != null ? `${money(c.dayLow)} – ${money(c.dayHigh)}` : "—"], ["52-wk range", c.low52 != null && c.high52 != null ? `${money(c.low52)} – ${money(c.high52)}` : "—"], ["Volume", c.volume != null ? Number(c.volume).toLocaleString() : "—"], ["Currency", c.currency || "USD"], ["Market", c.marketState || "—"]].map(([k, v]) => `<div>${k}<b class="num">${v}</b></div>`).join("");
  }

  // ---------- search ----------
  const q = $("#q"), results = $("#results"); let searchTimer = null;
  q.addEventListener("input", () => { clearTimeout(searchTimer); const v = q.value.trim(); if (!v) { results.hidden = true; return; } searchTimer = setTimeout(() => doSearch(v), 220); });
  q.addEventListener("keydown", e => { if (e.key === "Escape") { results.hidden = true; q.blur(); } if (e.key === "Enter") { const first = results.querySelector("button"); if (first) first.click(); } });
  document.addEventListener("click", e => { if (!e.target.closest(".search")) results.hidden = true; });
  async function doSearch(v) {
    const r = await getJSON("/api/search?q=" + encodeURIComponent(v), { results: [] }); results.innerHTML = "";
    if (!r.results.length) { results.appendChild(el("div", "empty", "No matches")); results.hidden = false; return; }
    r.results.slice(0, 8).forEach(x => { const b = el("button", null, `<span class="sym">${esc(x.symbol)}</span><span class="nm">${esc(x.name)} · ${esc(x.exchange || "")}</span><span class="add">Open</span>`); b.type = "button"; b.addEventListener("click", () => { results.hidden = true; q.value = ""; if (!state.quotes[x.symbol]) { getJSON("/api/quotes?symbols=" + encodeURIComponent(x.symbol), { quotes: [] }).then(rr => { (rr.quotes || []).forEach(qq => state.quotes[qq.symbol] = qq); openSheet(x.symbol); }); } else openSheet(x.symbol); }); results.appendChild(b); });
    results.hidden = false;
  }

  // ---------- tabs ----------
  $("#tabs").addEventListener("click", e => { const b = e.target.closest("button[data-tab]"); if (!b) return; state.tab = b.dataset.tab; document.querySelectorAll("#tabs button").forEach(x => x.setAttribute("aria-selected", x === b)); document.querySelectorAll(".panel").forEach(p => p.hidden = p.id !== "panel-" + state.tab); try { localStorage.setItem("sa.tab", state.tab); } catch (err) {} });
  try { const t = localStorage.getItem("sa.tab"); if (t) { const b = document.querySelector(`#tabs button[data-tab="${t}"]`); if (b) b.click(); } } catch (e) {}

  // ---------- refresh loop ----------
  async function refresh(force) {
    try { await loadData(); await loadQuotes(); renderAll(); } catch (e) { console.error(e); $("#status").innerHTML = `<span class="dot"></span><b>Couldn't load</b><br>${esc(e.message || e)}`; }
    clearTimeout(state.timer); state.timer = setTimeout(() => refresh(), 60000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  refresh();
})();
