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
const REPO = process.env.DATA_REPO || "finley1tree-wq/stock-agent";
const REF = process.env.DATA_REF || "main";
const BASE = `https://raw.githubusercontent.com/${REPO}/${REF}`;

// text files are tailed here rather than shipped whole: the page only ever renders the recent part
const FILES = [
  { key: "portfolio", path: "portfolio.json", json: true, fallback: {} },
  { key: "st", path: "state.json", json: true, fallback: {} },
  { key: "signals", path: "site/data/signals.json", json: true, fallback: {} },
  { key: "journal", path: "journal.json", json: true, fallback: [], tail: 1500 },
  { key: "lessons", path: "lessons.md", json: false, fallback: "" },
  { key: "log", path: "log.md", json: false, fallback: "", lines: 400 },
];

async function one(f) {
  // cache-bust per request so a five-minute CDN cache cannot pin the dashboard to stale state
  const url = `${BASE}/${f.path}?t=${Date.now()}`;
  try {
    const r = await fetch(url, { headers: { "User-Agent": "stock-agent-dashboard", "Cache-Control": "no-cache" } });
    if (!r.ok) return f.fallback;
    const text = await r.text();
    if (!f.json) return f.lines ? text.split("\n").slice(-f.lines).join("\n") : text;
    const v = JSON.parse(text);
    return f.tail && Array.isArray(v) ? v.slice(-f.tail) : v;
  } catch (e) {
    return f.fallback;          // one missing file must never blank the whole dashboard
  }
}

module.exports = async (req, res) => {
  const out = {};
  const got = await Promise.all(FILES.map(f => one(f)));
  FILES.forEach((f, i) => { out[f.key] = got[i]; });
  out.servedAt = Date.now();
  out.source = `${REPO}@${REF}`;
  // 10s at the edge: enough to absorb a burst of viewers, short enough to feel live
  res.setHeader("Cache-Control", "s-maxage=10, stale-while-revalidate=60");
  res.status(200).json(out);
};
