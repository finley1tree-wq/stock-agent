// Local preview of the dashboard: serves site/ and runs the api/ functions in-process. `node site-dev.mjs` -> http://localhost:8787
import http from "node:http"; import fs from "node:fs"; import path from "node:path"; import { createRequire } from "node:module"; import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url); const ROOT = path.dirname(fileURLToPath(import.meta.url)); const SITE = path.join(ROOT, "site");
const TYPES = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".json": "application/json", ".md": "text/markdown", ".svg": "image/svg+xml" };
http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://x"); const p = u.pathname;
  if (p.startsWith("/api/")) {
    const mod = path.join(ROOT, "api", p.slice(5).replace(/[^a-z_]/g, "") + ".js");
    if (!fs.existsSync(mod)) { res.writeHead(404); return res.end("no such function"); }
    const fn = require(mod); const fake = { setHeader: (k, v) => res.setHeader(k, v), status(c) { res.statusCode = c; return this; }, json(o) { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(o)); return this; } };
    try { await fn({ query: Object.fromEntries(u.searchParams) }, fake); } catch (e) { res.statusCode = 500; res.end(String(e)); }
    return;
  }
  let f = path.join(SITE, p === "/" ? "index.html" : p); if (!fs.existsSync(f) && fs.existsSync(f + ".html")) f += ".html";
  if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end("not found"); }
  res.setHeader("Content-Type", TYPES[path.extname(f)] || "application/octet-stream"); res.setHeader("Cache-Control", "no-store"); fs.createReadStream(f).pipe(res);
}).listen(8787, () => console.log("dashboard preview: http://localhost:8787"));
