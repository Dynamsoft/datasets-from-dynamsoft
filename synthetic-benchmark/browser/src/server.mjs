import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const versions = { "zxing-wasm": "3.1.2", "dynamsoft-dbr-js": "11.6.5000", "scandit-web-datacapture": "8.7.1" };
const { values: options } = parseArgs({ options: {
  images: { type: "string", default: "../dataset-by-format" },
  manifest: { type: "string" },
  output: { type: "string", default: "../.runs/browser" },
  port: { type: "string", default: "8790" },
  repetitions: { type: "string", default: "1" },
  dbrTemplate: { type: "string", default: "ReadBarcodes_Default" },
  decoders: { type: "string", default: Object.keys(versions).join(",") },
} });
const decoders = options.decoders.split(",").map((value) => value.trim());
const repetitions = Number(options.repetitions);
if (new Set(decoders).size !== decoders.length || !decoders.every((name) => Object.hasOwn(versions, name))
    || !Number.isSafeInteger(repetitions) || repetitions < 1) {
  throw new Error("Choose valid decoders and a positive number of repetitions");
}

const imageRoot = path.resolve(ROOT, options.images);
const manifest = options.manifest ? path.resolve(ROOT, options.manifest) : path.join(imageRoot, "manifest.jsonl");
const output = path.resolve(ROOT, options.output);
const jsonl = path.join(output, "results.jsonl");
const runFile = path.join(output, "run.json");
const manifestData = fs.readFileSync(manifest);
const parseJsonl = (data) => data.split("\n").filter(Boolean).map((line) => JSON.parse(line));
const samples = parseJsonl(manifestData.toString("utf8"));
const byId = new Map(samples.map((sample) => [sample.sample_id, sample]));
if (byId.size !== samples.length || !samples.length) throw new Error("Manifest sample IDs must be unique and nonempty");
const imagePaths = new Set(samples.map((sample) => sample.relative_path));
const identity = {
  protocol: "synthetic-browser-run-v1",
  manifest_sha256: createHash("sha256").update(manifestData).digest("hex"),
  decoders: [...decoders].sort(), repetitions, dbr_template: options.dbrTemplate, versions,
};
const expected = byId.size * decoders.length * repetitions;
const completed = new Set();
const recordKey = (row) => [row.sample_id, row.decoder, row.repetition].join("|");

function validateRecord(row) {
  if (!byId.has(row.sample_id) || !decoders.includes(row.decoder)
      || !Number.isSafeInteger(row.repetition) || row.repetition < 0 || row.repetition >= repetitions
      || !Number.isSafeInteger(row.decode_ns) || row.decode_ns < 0
      || !Number.isSafeInteger(row.image_load_ns) || row.image_load_ns < 0
      || (row.error !== null && typeof row.error !== "string")
      || typeof row.decoder_version !== "string" || !Array.isArray(row.predictions)
      || !row.predictions.every((item) => typeof item?.format === "string" && typeof item?.text === "string")) {
    throw new Error("Invalid benchmark record");
  }
  const { sample_id, decoder, decoder_version, repetition, image_load_ns, decode_ns, error, predictions } = row;
  return { sample_id, decoder, decoder_version, repetition, image_load_ns, decode_ns, error, predictions };
}

fs.mkdirSync(output, { recursive: true });
if (fs.existsSync(runFile)) {
  if (JSON.stringify(JSON.parse(fs.readFileSync(runFile, "utf8"))) !== JSON.stringify(identity)) {
    throw new Error("Run configuration differs. Choose a new output directory.");
  }
} else {
  if (fs.existsSync(jsonl)) throw new Error("Existing results have no run metadata");
  fs.writeFileSync(runFile, JSON.stringify(identity, null, 2) + "\n");
}
if (fs.existsSync(jsonl)) {
  for (const row of parseJsonl(fs.readFileSync(jsonl, "utf8"))) {
    const key = recordKey(validateRecord(row));
    if (completed.has(key)) throw new Error("Duplicate stored result " + key);
    completed.add(key);
  }
}

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json", ".jpg": "image/jpeg", ".png": "image/png",
  ".svg": "image/svg+xml", ".wasm": "application/wasm",
};
const scanditPackages = new Map(["core", "barcode"].map((name) => [
  name, path.join(ROOT, "node_modules", "@scandit", "web-datacapture-" + name),
]));
const localSdkPackages = new Map([
  ["zxing-wasm@" + versions["zxing-wasm"], path.join(ROOT, "node_modules", "zxing-wasm")],
  ["dynamsoft-barcode-reader-bundle@" + versions["dynamsoft-dbr-js"],
   path.join(ROOT, "node_modules", "dynamsoft-barcode-reader-bundle")],
]);
function json(res, code, data) {
  res.writeHead(code, { "content-type": "application/json", "cache-control": "no-store" });
  res.end(JSON.stringify(data));
}

async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 1024 * 1024) throw new Error("Request exceeds size limit");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function serveFile(res, root, relative) {
  const file = path.resolve(root, relative);
  if (!file.startsWith(path.resolve(root) + path.sep) || !fs.statSync(file, { throwIfNoEntry: false })?.isFile()) {
    return json(res, 404, { error: "File not found" });
  }
  res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream", "cache-control": "no-store" });
  const stream = fs.createReadStream(file);
  stream.on("error", () => res.destroy());
  return stream.pipe(res);
}

function finalize() {
  const scorer = spawnSync(process.env.BENCHMARK_PYTHON || "python", [
    path.join(ROOT, "score.py"), manifest, output,
  ], { encoding: "utf8" });
  if (scorer.error) throw scorer.error;
  if (scorer.status !== 0) throw new Error(scorer.stderr.trim() || "Scoring failed");
  return JSON.parse(fs.readFileSync(path.join(output, "summary.json"), "utf8"));
}

const server = http.createServer(async (req, res) => {
  try {
    const host = "127.0.0.1:" + server.address().port;
    const origin = "http://" + host;
    if (req.headers.host !== host || (req.headers.origin && req.headers.origin !== origin)) {
      return json(res, 403, { error: "Use the loopback address printed by the server" });
    }
    const route = new URL(req.url, origin).pathname;
    const progress = { completed_records: completed.size, expected_records: expected };
    if (req.method === "GET") {
      if (route === "/progress") return json(res, 200, progress);
      if (route === "/state") return json(res, 200, {
        ...progress, total_images: samples.length, decoders, repetitions,
        completed: [...completed], manifest_sha256: identity.manifest_sha256, dbr_template: options.dbrTemplate,
      });
      if (route === "/manifest") {
        res.writeHead(200, { "content-type": "application/x-ndjson", "cache-control": "no-store" });
        return res.end(manifestData);
      }
      if (route.startsWith("/images/")) {
        const relative = decodeURIComponent(route.slice("/images/".length));
        if (imagePaths.has(relative)) return serveFile(res, imageRoot, relative);
        return json(res, 404, { error: "Image is outside the manifest" });
      }
      if (route.startsWith("/scandit/")) {
        const [name, ...parts] = decodeURIComponent(route.slice("/scandit/".length)).split("/");
        if (scanditPackages.has(name)) return serveFile(res, scanditPackages.get(name), parts.join("/"));
        return json(res, 404, { error: "SDK package not found" });
      }
      if (route.startsWith("/sdk/")) {
        const [name, ...parts] = decodeURIComponent(route.slice("/sdk/".length)).split("/");
        if (localSdkPackages.has(name)) return serveFile(res, localSdkPackages.get(name), parts.join("/"));
        return json(res, 404, { error: "SDK package not found" });
      }
      return serveFile(res, path.join(ROOT, "web"), route === "/" ? "index.html" : route.slice(1));
    }
    if (req.method === "POST" && route === "/environment") {
      const browser = await readBody(req);
      const environment = {
        measured_at: new Date().toISOString(), os: os.platform() + " " + os.release(), architecture: os.arch(),
        processor: os.cpus()[0]?.model, logical_processors: os.cpus().length, node: process.version, browser,
      };
      fs.writeFileSync(path.join(output, "environment.json"), JSON.stringify(environment, null, 2) + "\n");
      return json(res, 200, { ok: true });
    }
    if (req.method === "POST" && route === "/record") {
      const row = validateRecord(await readBody(req));
      const key = recordKey(row);
      if (!completed.has(key)) {
        fs.appendFileSync(jsonl, JSON.stringify(row) + "\n");
        completed.add(key);
      }
      return json(res, 200, { ok: true, completed: completed.size });
    }
    if (req.method === "POST" && route === "/finalize") {
      if (completed.size !== expected) return json(res, 409, { error: "The run is incomplete" });
      return json(res, 200, finalize());
    }
    return json(res, 404, { error: "Route not found" });
  } catch (error) {
    console.error(error.message);
    json(res, 500, { error: error.message });
  }
});

server.listen(Number(options.port), "127.0.0.1", () => {
  console.log("Benchmark server on http://127.0.0.1:" + server.address().port);
  console.log(manifest + " (" + samples.length + " images)");
  console.log(jsonl + " (" + completed.size + " existing records)");
});
