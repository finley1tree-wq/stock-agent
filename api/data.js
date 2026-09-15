// GET /api/data -> every dashboard data file, read live from GitHub, in one response.
//
// Why this exists. The agent commits its state on every publish, and each commit made Vercel
// rebuild the site: one deploy per publish, against a Hobby limit of 100 a day. On 2026-09-11 that
// ceiling was hit by mid-afternoon (108 used) and the site froze - still serving correct-looking
// data while running two-day-old JavaScript, which is the worst kind of failure because nothing
// looks wrong. At more than a hundred trades a day the architecture simply could not work.
//
// The limit is on BUILDS, not on function invocations. So the data no longer travels through the
// build at all: this route fetches it from the repository at request time. Deploys are now needed
// only when the code itself changes, which is rare, and the data is as fresh as the last commit
// whatever the agent's trading rate.
//
// One request returns all six files, so a 60-second page refresh costs one invocation, not six.
//
// Why files are read BY COMMIT, not by branch. raw.githubusercontent.com caches a branch URL for
// about five minutes and a ?t= query string does not reliably bust it. Observed 2026-09-14 14:53 ET:
// the repo held HLI and NEM (last fill 14:52) while this route returned no positions and a last
// fill of 14:48, so the chart's target/stop zones could not appear. A commit URL is immutable, so
// its cache can never be stale. The branch head is resolved from git's smart-HTTP ref advertisement
// (the same endpoint `git ls-remote` uses) - not the REST API, which allows 60 unauthenticated calls
// an hour. If that lookup fails or is slow, the old branch URL is used so the page never blanks.
const REPO = process.env.DATA_REPO || "finley1tree-wq/stock-agent";
const REF = process.env.DATA_REF || "main";
const RAW = `https://raw.githubusercontent.com/${REPO}`;
const BASE = `${RAW}/${REF}`;
const REFS_URL = `https://github.com/${REPO}.git/info/refs?service=git-upload-pack`;
const SHA_TTL_MS = 5000;          // one lookup per warm instance every 5 s at most
const RESOLVE_TIMEOUT_MS = 2500;  // past this, serve the branch URL rather than keep the page waiting
const UA = { "User-Agent": "stock-agent-dashboard" };

// text files are tailed here rather than shipped whole: the page only ever renders the recent part
const FILES = [
  { key: "portfolio", path: "portfolio.json", json: true, fallback: {} },
  { key: "st", path: "state.json", json: true, fallback: {} },
  { key: "signals", path: "site/data/signals.json", json: true, fallback: {} },
  { key: "journal", path: "journal.json", json: true, fallback: [], tail: 1500 },
  { key: "lessons", path: "lessons.md", json: false, fallback: "" },
  { key: "log", path: "log.md", json: false, fallback: "", lines: 400 },
];

// Parse a git smart-HTTP v0 ref advertisement (pkt-line framing) and return the object id of
// `ref`: "main" means refs/heads/main (then a tag of that name, peeled); a full "refs/..." name is
// matched exactly. Each pkt-line is 4 hex digits of total length (including those 4) then the
// payload; "0000" is a flush. The first ref line carries capabilities after a NUL. Returns null
// when the ref is absent or the body is not a well-formed advertisement.
function parseRefAdvertisement(body, ref) {
  const buf = Buffer.isBuffer(body) ? body
    : typeof body === "string" ? Buffer.from(body, "latin1") : Buffer.from(new Uint8Array(body));
  const refs = new Map();
  let i = 0;
  while (i + 4 <= buf.length) {
    const hex = buf.toString("latin1", i, i + 4);
    if (!/^[0-9a-f]{4}$/i.test(hex)) return null;               // not pkt-line framed
    const len = parseInt(hex, 16);
    if (len === 0 || len === 1 || len === 2) { i += 4; continue; }  // flush / delim / response-end
    if (len < 4 || i + len > buf.length) return null;           // truncated or corrupt
    let line = buf.toString("latin1", i + 4, i + len);
    i += len;
    if (line.endsWith("\n")) line = line.slice(0, -1);
    if (line.startsWith("#")) continue;                        // "# service=git-upload-pack"
    const nul = line.indexOf("\0");
    if (nul >= 0) line = line.slice(0, nul);                   // drop capabilities
    const m = /^([0-9a-f]{40}|[0-9a-f]{64}) (\S+)$/.exec(line);
    if (m) refs.set(m[2], m[1]);
  }
  const wanted = String(ref || "").startsWith("refs/") ? [ref]
    : [`refs/heads/${ref}`, `refs/tags/${ref}^{}`, `refs/tags/${ref}`];
  for (const w of wanted) if (refs.has(w)) return refs.get(w);
  return null;
}

let shaCache = { sha: null, at: 0 };   // module scope: survives between requests on a warm instance
let inflight = null;

async function resolveSha(now = Date.now()) {
  if (/^([0-9a-f]{40}|[0-9a-f]{64})$/i.test(REF)) return REF;  // already pinned to a commit
  if (now - shaCache.at < SHA_TTL_MS) return shaCache.sha;       // a failure is remembered too, so a
  if (inflight) return inflight;                                  // GitHub outage costs 2.5 s once per TTL
  inflight = (async () => {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), RESOLVE_TIMEOUT_MS);
    let sha = null;
    try {
      const r = await fetch(REFS_URL, { headers: UA, signal: ctl.signal });
      if (r.ok) sha = parseRefAdvertisement(Buffer.from(await r.arrayBuffer()), REF);
    } catch (e) {
      sha = null;
    } finally {
      clearTimeout(timer);
    }
    shaCache = { sha, at: Date.now() };
    return sha;
  })();
  try { return await inflight; } finally { inflight = null; }
}

async function fetchText(url, headers) {
  const r = await fetch(url, { headers });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.text();
}

async function one(f, sha) {
  // By commit when the head is known (immutable, so never stale); otherwise by branch with a
  // cache-bust. A commit URL that fails is retried by branch: one missing file must never blank
  // the whole dashboard, and stale beats empty.
  const byBranch = `${BASE}/${f.path}?t=${Date.now()}`;
  let text = null, via = "branch";
  if (sha) {
    try { text = await fetchText(`${RAW}/${sha}/${f.path}`, UA); via = "sha"; } catch (e) { text = null; }
  }
  try {
    if (text == null) text = await fetchText(byBranch, { ...UA, "Cache-Control": "no-cache" });
    if (!f.json) return { v: f.lines ? text.split("\n").slice(-f.lines).join("\n") : text, via };
    const v = JSON.parse(text);
    return { v: f.tail && Array.isArray(v) ? v.slice(-f.tail) : v, via };
  } catch (e) {
    return { v: f.fallback, via: "fallback" };
  }
}

async function handler(req, res) {
  const out = {};
  const sha = await resolveSha();
  const got = await Promise.all(FILES.map(f => one(f, sha)));
  FILES.forEach((f, i) => { out[f.key] = got[i].v; });
  out.servedAt = Date.now();
  out.source = `${REPO}@${REF}`;
  // which commit the files were read at; via[] names any file that had to use the branch URL
  out.meta = { sha: sha || null, ref: REF, via: Object.fromEntries(FILES.map((f, i) => [f.key, got[i].via])) };
  // 10s at the edge: enough to absorb a burst of viewers, short enough to feel live
  res.setHeader("Cache-Control", "s-maxage=10, stale-while-revalidate=60");
  res.status(200).json(out);
}

module.exports = handler;
module.exports.parseRefAdvertisement = parseRefAdvertisement;
module.exports.resolveSha = resolveSha;
module.exports._resetShaCache = () => { shaCache = { sha: null, at: 0 }; inflight = null; };
