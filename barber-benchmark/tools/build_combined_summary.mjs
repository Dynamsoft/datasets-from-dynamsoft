/**
 * Build the combined result table and a lightweight comparison page from the two
 * published runs. No benchmark is re-run here; everything is read from the
 * shipped summary.json files so the numbers stay auditable.
 *
 *   node tools/build_combined_summary.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "results");
const SCORED = 8411;
const IMAGES = 7894;
const ANNOTATIONS = 8615;

const RUNS = [
  {
    runtime: "web",
    label: "Web / JavaScript (WASM)",
    summary: path.join(ROOT, "js", "results", "full", "summary.json"),
    environment: path.join(ROOT, "js", "configs", "benchmark_environment.json"),
    products: {
      "dynamsoft-dbr-js": "Dynamsoft Barcode Reader JS 11.6.5000",
      "scandit-web-datacapture": "Scandit Data Capture SDK 8.7.1 (Web)",
      "zxing-wasm": "zxing-wasm 3.1.2",
    },
  },
  {
    runtime: "cpp",
    label: "C++ / Linux (native)",
    summary: path.join(ROOT, "cpp", "results", "full_linux", "summary.json"),
    environment: path.join(ROOT, "cpp", "configs", "benchmark_environment.json"),
    products: {
      "dynamsoft-dbr": "Dynamsoft Barcode Reader 11.6.50.29329 (Linux)",
      "scandit-linux": "Scandit Barcode Scanner SDK 8.7.1 (Linux)",
      "zxing-cpp": "ZXing-C++ 3.1.1",
    },
  },
];

const esc = (v) => String(v).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const rows = [];
const runs = [];
for (const run of RUNS) {
  const summary = JSON.parse(fs.readFileSync(run.summary, "utf8"));
  const env = fs.existsSync(run.environment)
    ? JSON.parse(fs.readFileSync(run.environment, "utf8")) : {};
  const runInfo = {
    runtime: run.runtime,
    label: run.label,
    operating_system: env.operating_system || "",
    processor: env.processor || "",
    repetitions: env.repetitions ?? 1,
    measured_at: env.measured_at || "",
    records: Object.values(summary.decoders).reduce((n, d) => n + d.records, 0),
    decoders: [],
  };
  for (const [decoder, product] of Object.entries(run.products)) {
    const d = summary.decoders[decoder];
    if (!d) throw new Error(`missing decoder ${decoder} in ${run.summary}`);
    const row = {
      runtime: run.runtime,
      decoder,
      product,
      records: d.records,
      images: IMAGES,
      scored_ground_truth: SCORED,
      correct: d.correct,
      recall_pct: +(d.coverage_adjusted_recall * 100).toFixed(2),
      wrong_reads: d.wrong_reads,
      no_read: d.no_read,
      extra_result: d.outcomes.extra_result || 0,
      unsupported_format: d.outcomes.unsupported_format || 0,
      mean_decode_ms: +d.mean_decode_ms.toFixed(2),
      median_decode_ms: +d.median_decode_ms.toFixed(2),
      p95_decode_ms: +d.p95_decode_ms.toFixed(2),
    };
    rows.push(row);
    runInfo.decoders.push(row);
  }
  runs.push(runInfo);
}

const combined = {
  dataset: "BarBeR public real-world barcode dataset",
  dataset_url: "https://ditto.ing.unimore.it/barber/",
  images: IMAGES,
  audited_annotations: ANNOTATIONS,
  scored_ground_truth: SCORED,
  excluded_placeholders: ANNOTATIONS - SCORED,
  note: "Recall = correct / 8,411. Extra results (predictions no annotation claims) are reported as raw counts; precision is not reported because BarBeR annotations are not exhaustive and the canonical-format table scores 196 annotations as unsupported. Decode times are not comparable across runtimes.",
  sources: [
    "js/results/full/summary.json",
    "cpp/results/full_linux/summary.json",
  ],
  runs,
  results: rows,
};

fs.mkdirSync(OUT, { recursive: true });
fs.writeFileSync(path.join(OUT, "combined-summary.json"), JSON.stringify(combined, null, 2) + "\n");

const columns = [
  "runtime", "decoder", "product", "records", "images", "scored_ground_truth",
  "correct", "recall_pct", "wrong_reads", "no_read",
  "extra_result", "unsupported_format", "mean_decode_ms", "median_decode_ms", "p95_decode_ms",
];
const csv = [columns.join(",")].concat(rows.map((r) => columns.map((c) => {
  const v = String(r[c]);
  return /[",\n]/.test(v) ? `"${v.replaceAll('"', '""')}"` : v;
}).join(","))).join("\n") + "\n";
fs.writeFileSync(path.join(OUT, "combined-summary.csv"), csv);

// --- lightweight comparison page ------------------------------------------
function table(run) {
  const body = run.decoders.map((d) => `<tr>
    <td>${esc(d.product)}</td>
    <td class="num"><strong>${d.correct.toLocaleString()}</strong> / ${SCORED.toLocaleString()}</td>
    <td class="num"><strong>${d.recall_pct.toFixed(2)}%</strong></td>
    <td class="num">${d.extra_result.toLocaleString()}</td>
    <td class="num">${d.wrong_reads.toLocaleString()}</td>
    <td class="num">${d.no_read.toLocaleString()}</td>
    <td class="num">${d.mean_decode_ms.toFixed(2)}</td>
    <td class="num">${d.median_decode_ms.toFixed(2)}</td>
    <td class="num">${d.p95_decode_ms.toFixed(2)}</td>
  </tr>`).join("");
  return `<h2>${esc(run.label)}</h2>
  <p class="muted">${esc(run.operating_system)} &middot; ${esc(run.processor)} &middot; ${run.records.toLocaleString()} decode records &middot; ${run.repetitions} repetition</p>
  <table><thead><tr><th>Decoder</th><th>Correct</th><th>Recall</th><th>Extra results</th><th>Wrong reads</th><th>No read</th><th>Mean ms</th><th>Median ms</th><th>P95 ms</th></tr></thead><tbody>${body}</tbody></table>`;
}

const COLORS = { web: "#2563eb", cpp: "#0f9d8a" };
function barChart(metric, suffix) {
  const W = 660, H = 260, left = 170, top = 24, rowH = 34, max = 100;
  const bars = [];
  let y = top;
  for (const run of runs) {
    for (const d of run.decoders) {
      const value = d[metric];
      const width = Math.max(2, (value / max) * (W - left - 60));
      bars.push(`<text x="${left - 10}" y="${y + 15}" text-anchor="end" class="lbl">${esc(d.decoder)}</text>`);
      bars.push(`<rect x="${left}" y="${y + 3}" width="${width.toFixed(1)}" height="18" rx="3" fill="${COLORS[run.runtime]}"/>`);
      bars.push(`<text x="${left + width + 6}" y="${y + 17}" class="val">${value.toFixed(2)}${suffix}</text>`);
      bars.push(`<text x="${W - 6}" y="${y + 17}" text-anchor="end" class="rt">${run.runtime}</text>`);
      y += rowH;
    }
    y += 8;
  }
  return `<svg viewBox="0 0 ${W} ${y + 8}" role="img" aria-label="${esc(metric)} comparison">${bars.join("")}</svg>`;
}

const page = `<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>BarBeR Benchmark — Web vs C++</title>
<style>
:root{--ink:#172033;--muted:#60708a;--line:#dbe2ea;--bg:#f5f7fa}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 Segoe UI,Arial,sans-serif;color:var(--ink);background:var(--bg)}
header{padding:36px max(5vw,28px);color:#fff;background:linear-gradient(120deg,#102649,#1769e0 62%,#00a495)}
header h1{margin:0 0 6px;font-size:clamp(26px,4vw,44px)}header p{margin:0;opacity:.9}
.wrap{max-width:1100px;margin:auto;padding:24px}section{background:#fff;border:1px solid var(--line);border-radius:14px;margin:16px 0;padding:22px;box-shadow:0 3px 18px #1026490c}
h2{margin-top:0}.muted{color:var(--muted);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:11px;padding:16px}.metric{font-size:28px;font-weight:750}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px;border-bottom:1px solid var(--line);text-align:left}
th{background:#edf3fa}.num{text-align:right;font-variant-numeric:tabular-nums}
svg{width:100%;height:auto}.lbl{font-size:11px;fill:#172033}.val{font-size:11px;fill:#172033;font-weight:600}.rt{font-size:10px;fill:#60708a}
a{color:#1769e0}@media print{body{background:#fff}section{box-shadow:none;break-inside:avoid}}
</style>
<header><h1>BarBeR Benchmark — Web vs C++</h1><p>Dynamsoft Barcode Reader, Scandit and ZXing on the same 7,894-image public dataset</p></header>
<main class="wrap">
<section><h2>Dataset</h2><div class="cards">
<div class="card"><div class="metric">${IMAGES.toLocaleString()}</div><span class="muted">unique audited images</span></div>
<div class="card"><div class="metric">${ANNOTATIONS.toLocaleString()}</div><span class="muted">audited annotations</span></div>
<div class="card"><div class="metric">${SCORED.toLocaleString()}</div><span class="muted">scored ground truth (204 <code>^</code> placeholders excluded)</span></div>
<div class="card"><div class="metric">3</div><span class="muted">decoders &times; 2 runtimes</span></div>
</div><p class="muted">Source: <a href="https://ditto.ing.unimore.it/barber/">BarBeR</a>, University of Modena and Reggio Emilia. Both runs use the same audited manifest and the same one-to-one multiset matching rules.</p></section>
<section>${table(runs[0])}</section>
<section>${table(runs[1])}</section>
<section><h2>Recall (%)</h2>${barChart("recall_pct", "%")}
<p class="muted">Blue = Web/JavaScript, teal = C++/Linux. Extra results are listed as counts rather than a precision rate: BarBeR's annotations are curated rather than exhaustive, and the canonical-format table scores 196 underscored annotations as unsupported, so the ratio would measure annotation coverage as much as decoder error. Decode times are <strong>not</strong> comparable across runtimes: the C++ run used four worker processes on a shared CPU inside Docker, while the Web run used a single headless Chrome session. Compare accuracy within each runtime and compare decoders within each run.</p></section>
<section><h2>Full reports and raw data</h2><ul>
<li><a href="../js/report/index.html">Web / JavaScript interactive report</a> (searchable per-image records)</li>
<li><a href="../cpp/report/index.html">C++ / Linux interactive report</a> (searchable per-image records)</li>
<li><a href="combined-summary.json">combined-summary.json</a> &middot; <a href="combined-summary.csv">combined-summary.csv</a></li>
<li>Raw streams: <code>js/results/full/results.jsonl</code>, <code>cpp/results/full_linux/results.jsonl</code></li>
</ul><p class="muted">Both commercial readers require your own trial license; see <a href="../licenses/README.md">licenses/README.md</a>. No key is bundled.</p></section>
</main></html>
`;
fs.writeFileSync(path.join(OUT, "comparison.html"), page);

for (const r of rows) {
  console.log(`${r.runtime.padEnd(4)} ${r.decoder.padEnd(26)} ${String(r.correct).padStart(5)}/${SCORED} ` +
    `recall=${r.recall_pct.toFixed(2)}% extras=${r.extra_result} mean=${r.mean_decode_ms} ms`);
}
console.log("wrote results/combined-summary.json, combined-summary.csv, comparison.html");
