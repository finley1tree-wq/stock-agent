// Dashboard tests: node --test tests/test_dashboard.mjs   (the "live" tests need network access)
// Read-only: fetches from github.com / raw.githubusercontent.com, writes nothing.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const api = require(path.join(ROOT, "api/data.js"));
const REPO = "finley1tree-wq/stock-agent";

// ---------- (a) pkt-line parser on a captured sample ----------
// Captured 2026-09-15 06:01Z from https://github.com/finley1tree-wq/stock-agent.git/info/refs?service=git-upload-pack
const SAMPLE =
  "001e# service=git-upload-pack\n" + "0000" +
  "015939d20dbccceec42e2a864965e1d10aa15a707061 HEAD\0multi_ack thin-pack side-band side-band-64k ofs-delta shallow deepen-since deepen-not deepen-relative no-progress include-tag multi_ack_detailed allow-tip-sha1-in-want allow-reachable-sha1-in-want no-done symref=HEAD:refs/heads/main filter object-format=sha1 agent=git/github-0fe9e8c85cc2-Linux\n" +
  "003d39d20dbccceec42e2a864965e1d10aa15a707061 refs/heads/main\n" + "0000";
const pkt = s => (s.length + 4).toString(16).padStart(4, "0") + s;

test("parser: captured sample, framing lengths are the real ones", () => {
  assert.equal(SAMPLE.length, 444);                       // byte size of the captured body
  assert.equal(api.parseRefAdvertisement(SAMPLE, "main"), "39d20dbccceec42e2a864965e1d10aa15a707061");
  assert.equal(api.parseRefAdvertisement(Buffer.from(SAMPLE, "latin1"), "main"), "39d20dbccceec42e2a864965e1d10aa15a707061");
  assert.equal(api.parseRefAdvertisement(SAMPLE, "refs/heads/main"), "39d20dbccceec42e2a864965e1d10aa15a707061");
  assert.equal(api.parseRefAdvertisement(SAMPLE, "HEAD"), null);  // "HEAD" is not refs/heads/HEAD
});

test("parser: other branches, peeled tags, sha256, absent ref, corrupt bodies", () => {
  const a = "a".repeat(40), b = "b".repeat(40), c = "c".repeat(40), d = "d".repeat(64);
  const body = pkt("# service=git-upload-pack\n") + "0000" + pkt(`${a} HEAD\0caps symref=HEAD:refs/heads/main\n`) +
    pkt(`${b} refs/heads/main-old\n`) + pkt(`${a} refs/heads/main\n`) + pkt(`${b} refs/tags/v1\n`) +
    pkt(`${c} refs/tags/v1^{}\n`) + pkt(`${d} refs/heads/sha256\n`) + "0000";
  assert.equal(api.parseRefAdvertisement(body, "main"), a);          // not fooled by main-old
  assert.equal(api.parseRefAdvertisement(body, "main-old"), b);
  assert.equal(api.parseRefAdvertisement(body, "v1"), c);            // annotated tag peeled to its commit
  assert.equal(api.parseRefAdvertisement(body, "sha256"), d);
  assert.equal(api.parseRefAdvertisement(body, "nope"), null);
  assert.equal(api.parseRefAdvertisement(SAMPLE.slice(0, 200), "main"), null);             // truncated
  assert.equal(api.parseRefAdvertisement("<html>rate limited</html>", "main"), null);      // not pkt-line
  assert.equal(api.parseRefAdvertisement("", "main"), null);
  // a ref line without a trailing newline is still valid pkt-line
  assert.equal(api.parseRefAdvertisement(pkt(`${a} refs/heads/x`) + "0000", "x"), a);
});

// ---------- (b) live ----------
const lsRemote = () => execFileSync("git", ["ls-remote", `https://github.com/${REPO}`, "refs/heads/main"], { encoding: "utf8" }).split(/\s/)[0];

test("live: resolved SHA equals git ls-remote, and portfolio.json parses at that SHA", async () => {
  let sha, remote, before;
  for (let attempt = 1; attempt <= 3; attempt++) {    // the bot commits every few minutes; retry a race
    api._resetShaCache();
    before = lsRemote();
    sha = await api.resolveSha();
    remote = lsRemote();
    console.log(`  attempt ${attempt}: resolveSha=${sha} ls-remote(before)=${before} ls-remote(after)=${remote}`);
    if (sha === remote || sha === before) break;
  }
  assert.match(sha, /^[0-9a-f]{40}$/);
  assert.ok(sha === remote || sha === before, `resolved ${sha} != ls-remote ${before}/${remote}`);
  const r = await fetch(`https://raw.githubusercontent.com/${REPO}/${sha}/portfolio.json`);
  assert.equal(r.status, 200);
  const p = JSON.parse(await r.text());
  assert.equal(typeof p, "object");
  assert.ok("cash" in p && "positions" in p, "portfolio.json has cash and positions");
  console.log(`  portfolio@${sha.slice(0, 7)}: cash=${p.cash} positions=[${Object.keys(p.positions || {}).join(",")}]`);
});

function mockRes() {
  const res = { headers: {}, code: null, body: null };
  res.setHeader = (k, v) => { res.headers[k] = v; };
  res.status = c => { res.code = c; return res; };
  res.json = b => { res.body = b; return res; };
  return res;
}

test("live: handler reads every file at the resolved commit and keeps the response shape", async () => {
  api._resetShaCache();
  const res = mockRes();
  await api({}, res);
  const b = res.body;
  assert.equal(res.code, 200);
  assert.equal(res.headers["Cache-Control"], "s-maxage=10, stale-while-revalidate=60");
  assert.deepEqual(Object.keys(b), ["portfolio", "st", "signals", "journal", "lessons", "log", "servedAt", "source", "meta"]);
  assert.equal(b.source, `${REPO}@main`);
  assert.match(b.meta.sha, /^[0-9a-f]{40}$/);
  assert.deepEqual(Object.values(b.meta.via), ["sha", "sha", "sha", "sha", "sha", "sha"]);
  assert.ok(b.portfolio.positions && typeof b.st === "object" && b.signals.guardrails);
  assert.ok(Array.isArray(b.journal) && b.journal.length <= 1500);
  assert.ok(b.log.split("\n").length <= 400);
  console.log(`  meta=${JSON.stringify(b.meta)}`);
});

test("fallback: a hung ref lookup times out (~2.5s) and the branch URL is served, not a blank page", async () => {
  api._resetShaCache();
  const realFetch = globalThis.fetch;
  let refsCalls = 0;
  globalThis.fetch = (url, opts = {}) => {
    if (String(url).includes("/info/refs")) {
      refsCalls++;
      return new Promise((_, rej) => opts.signal?.addEventListener("abort", () => rej(new Error("aborted"))));
    }
    return realFetch(url, opts);
  };
  try {
    const t0 = Date.now();
    const res = mockRes();
    await api({}, res);
    const took = Date.now() - t0;
    assert.equal(res.body.meta.sha, null);
    assert.deepEqual(Object.values(res.body.meta.via), ["branch", "branch", "branch", "branch", "branch", "branch"]);
    assert.ok(res.body.portfolio.positions, "branch data still served");
    assert.ok(took >= 2400, `waited ${took}ms for the timeout`);
    // the failure is cached for the TTL: a second request does not wait again
    const t1 = Date.now(); await api({}, mockRes());
    assert.equal(refsCalls, 1);
    console.log(`  first request ${took}ms (timeout), second ${Date.now() - t1}ms, ref lookups=${refsCalls}`);
  } finally {
    globalThis.fetch = realFetch;
    api._resetShaCache();
  }
});

test("cache: SHA resolved at most once per ~5s, concurrent requests share one lookup", async () => {
  api._resetShaCache();
  const realFetch = globalThis.fetch;
  let refsCalls = 0;
  globalThis.fetch = (url, opts) => { if (String(url).includes("/info/refs")) refsCalls++; return realFetch(url, opts); };
  try {
    const shas = await Promise.all([api.resolveSha(), api.resolveSha(), api.resolveSha()]);
    await api.resolveSha();
    assert.equal(refsCalls, 1);
    assert.equal(new Set(shas).size, 1);
    await api.resolveSha(Date.now() + 6000);
    assert.equal(refsCalls, 2, "re-resolved after the TTL");
  } finally {
    globalThis.fetch = realFetch;
    api._resetShaCache();
  }
});

// ---------- next check (site/app.js) ----------
// Pull nextCheckFor out of the page script (it lives inside an IIFE that needs a DOM).
function extract(src, name) {
  const start = src.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  let i = src.indexOf("{", start), depth = 0;
  for (; i < src.length; i++) { if (src[i] === "{") depth++; else if (src[i] === "}" && --depth === 0) break; }
  return new Function(`return (${src.slice(start, i + 1)})`)();
}
const nextCheckFor = extract(readFileSync(path.join(ROOT, "site/app.js"), "utf8"), "nextCheckFor");

// published data as it stood on 2026-09-14 (signals.json guardrails + state.json)
const SG = { run_every_minutes: 30, holidays: ["2026-09-07", "2026-11-26"], early_close_1pm: ["2026-11-27"],
  guardrails: { autopilot_decision_minutes: 2, min_decision_minutes: 6, max_decision_minutes: 30 } };
const at = (iso) => Date.parse(iso);                       // ET is UTC-4 in September
const NOW = at("2026-09-14T14:53:00-04:00");                // a Monday, market open

test("next check: autopiloted=true uses autopilot_decision_minutes (2)", () => {
  const st = { autopiloted: true, next_check_minutes: null, last_decision_ts: NOW / 1000 - 60 };
  assert.equal(nextCheckFor(SG, st, NOW), "in 1 min · 2:54 PM ET");
  assert.equal(nextCheckFor(SG, { ...st, last_decision_ts: NOW / 1000 - 180 }, NOW), "any moment");
  // cadence not published (older signals.json): config default 2
  assert.equal(nextCheckFor({ ...SG, guardrails: {} }, st, NOW), "in 1 min · 2:54 PM ET");
  // a different published cadence is honoured
  assert.equal(nextCheckFor({ ...SG, guardrails: { ...SG.guardrails, autopilot_decision_minutes: 4 } }, st, NOW), "in 3 min · 2:56 PM ET");
});

test("next check: autopiloted=false keeps the brain's clamped window", () => {
  const st = { autopiloted: false, next_check_minutes: null, last_decision_ts: NOW / 1000 - 240 };
  assert.equal(nextCheckFor(SG, st, NOW), "in 26 min · 3:19 PM ET");           // null -> run_every 30
  assert.equal(nextCheckFor(SG, { ...st, next_check_minutes: 10 }, NOW), "in 6 min · 2:59 PM ET");
  assert.equal(nextCheckFor(SG, { ...st, next_check_minutes: 2 }, NOW), "in 2 min · 2:55 PM ET"); // floored to 6
  assert.equal(nextCheckFor(SG, { ...st, last_decision_ts: 0 }, NOW), "any moment");
});

test("next check: market closed / pre-open / weekend / holiday", () => {
  const st = { autopiloted: true, last_decision_ts: at("2026-09-14T15:53:00-04:00") / 1000 };
  assert.equal(nextCheckFor(SG, st, at("2026-09-14T16:10:00-04:00")), "tomorrow 9:30 AM ET");
  assert.equal(nextCheckFor(SG, st, at("2026-09-15T08:00:00-04:00")), "at the 9:30 AM ET open");
  assert.equal(nextCheckFor(SG, st, at("2026-09-12T12:00:00-04:00")), "Monday 9:30 AM ET");     // Saturday
  assert.equal(nextCheckFor(SG, st, at("2026-09-04T17:00:00-04:00")), "Tuesday 9:30 AM ET");    // Fri before Labor Day
  assert.equal(nextCheckFor(SG, st, at("2026-11-27T13:30:00-05:00")), "Monday 9:30 AM ET");     // early close passed
});

test("next check: the observed bug - old code said 26 min under autopilot, new code says any moment", () => {
  let old;
  try { old = execFileSync("git", ["-C", ROOT, "show", "origin/main:site/app.js"], { encoding: "utf8" }); } catch (e) { return; }
  // old nextCheckText read globals; wrap it so it can be driven with the same inputs
  const s = old.indexOf("function nextCheckText("); let i = old.indexOf("{", s), dep = 0;
  for (; i < old.length; i++) { if (old[i] === "{") dep++; else if (old[i] === "}" && --dep === 0) break; }
  const body = old.slice(s, i + 1).replace(/Date\.now\(\)/g, "NOW").replace("new Date().toLocaleString", "new Date(NOW).toLocaleString");
  const oldFn = new Function("state", "NOW", `${body}; return nextCheckText();`);
  const st = { autopiloted: true, next_check_minutes: null, last_decision_ts: NOW / 1000 - 240 };
  const was = oldFn({ data: { signals: SG, st } }, NOW), now = nextCheckFor(SG, st, NOW);
  console.log(`  autopiloted, last decision 4 min ago: old="${was}"  new="${now}"`);
  assert.equal(was, "in 26 min · 3:19 PM ET");
  assert.equal(now, "any moment");
});
