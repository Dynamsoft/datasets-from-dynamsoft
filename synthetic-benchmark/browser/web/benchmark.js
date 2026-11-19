/**
 * Browser harness for the zxing-wasm vs. Dynamsoft Barcode Reader vs. Scandit benchmark.
 *
 * Browser protocol:
 * - The server supplies the synthetic manifest and its images.
 * - Each image is fetched once and decoded into an ImageBitmap, then painted
 *   onto a shared canvas. That stage is recorded as image_load_ns and never
 *   enters the decode clock.
 * - All three decoders receive the same canvas/raw pixels; only the decoder
 *   call is timed.
 * - Decoder order is shuffled per (sample, repetition) with a seeded PRNG.
 * - Each record is POSTed to the collector server, which scores it with the
 *   shared matching rules at finalization and appends it to results.jsonl (resumable).
 *
 * Scandit runs in BarcodeBatch (MatrixScan) mode. One ImageFrameSource is built
 * per image from the shared canvas' ImageData; it emits exactly one frame and
 * turns itself off. didUpdateSession fires for every processed frame (with or
 * without barcodes), so it is used as the "frame processed" signal.
 */

import {
  DataCaptureContext, ImageFrameSource, FrameSourceState,
} from "@scandit/web-datacapture-core";
import {
  barcodeCaptureLoader, BarcodeBatch, BarcodeBatchSettings,
  Checksum, Symbology, SymbologyDescription,
} from "@scandit/web-datacapture-barcode";

const ZXING_NAME = "zxing-wasm";
const DBR_NAME = "dynamsoft-dbr-js";
const SCANDIT_NAME = "scandit-web-datacapture";
const ZXING_PINNED = "3.1.2";
const DBR_PINNED = "11.6.5000";
const SCANDIT_PINNED = "8.7.1";

const SCANDIT_SYMBOLOGIES = [
  Symbology.EAN13UPCA, Symbology.UPCE, Symbology.EAN8,
  Symbology.Code39, Symbology.Code93, Symbology.Code128,
  Symbology.Codabar, Symbology.InterleavedTwoOfFive, Symbology.IATATwoOfFive,
  Symbology.QR, Symbology.DataMatrix, Symbology.Aztec,
  Symbology.PDF417, Symbology.KIX, Symbology.RoyalMail4state,
  Symbology.USPSIntelligentMail, Symbology.DotCode, Symbology.MSIPlessey,
  Symbology.MaxiCode, Symbology.MicroQR,
];

const el = {
  license: document.getElementById("license"),
  scanditLicense: document.getElementById("scandit-license"),
  init: document.getElementById("init-btn"),
  run: document.getElementById("run-btn"),
  stop: document.getElementById("stop-btn"),
  finalize: document.getElementById("finalize-btn"),
  sdkStatus: document.getElementById("sdk-status"),
  progressBar: document.getElementById("progress-bar"),
  progressText: document.getElementById("progress-text"),
  liveStats: document.getElementById("live-stats"),
  summary: document.getElementById("summary"),
};

window.__bench = {
  phase: "idle",
  done: 0,
  total: 0,
  errors: [],
  startedAt: 0,
};

let manifest = [];
let completedKeys = new Set();
let repetitions = 1;
let cvRouter = null;
let dbrTemplate = "ReadBarcodes_Default";
let dbrFormats = "";
let activeDecoders = [];
let zxingVersion = ZXING_PINNED;
let dbrVersion = DBR_PINNED;
let scanditVersion = SCANDIT_PINNED;
let scanditContext = null;
let scanditBatch = null;
let scanditStatus = null;
let stopRequested = false;
let sharedCanvas = document.createElement("canvas");
let sharedCtx = sharedCanvas.getContext("2d", { willReadFrequently: true });

const stats = {
  [ZXING_NAME]: { images: 0, barcodes: 0, totalDecodeMs: 0 },
  [DBR_NAME]: { images: 0, barcodes: 0, totalDecodeMs: 0 },
  [SCANDIT_NAME]: { images: 0, barcodes: 0, totalDecodeMs: 0 },
};

function setStatus(text) {
  el.sdkStatus.textContent = text;
}

function progress(text, fraction) {
  el.progressText.textContent = text;
  el.progressBar.style.width = `${Math.round(fraction * 100)}%`;
}

// --- seeded PRNG -----------------------------------------------------------

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

async function shuffledDecoders(sampleId, repetition) {
  const hex = await sha256Hex(`${sampleId}:${repetition}`);
  const rng = mulberry32(parseInt(hex.slice(0, 12), 16));
  const order = activeDecoders.slice();
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }
  return order;
}

// --- SDK initialization ----------------------------------------------------

async function initSdk() {
  if (!manifest.length) await loadManifest();
  const runs = (decoder) => activeDecoders.includes(decoder);

  if (runs(ZXING_NAME)) {
    setStatus("Initializing zxing-wasm…");
    if (typeof ZXingWASM === "undefined") throw new Error("The local ZXing WASM package did not load");
    await ZXingWASM.prepareZXingModule({
      overrides: { locateFile: (file) => "/sdk/zxing-wasm@" + ZXING_PINNED + "/dist/full/" + file },
      fireImmediately: true,
    });
    zxingVersion = ZXING_PINNED;
  }

  let scanditEnvironment = null;
  if (runs(DBR_NAME)) {
    setStatus("Initializing Dynamsoft Barcode Reader…");
    const key = (window.__DYNAMSOFT_LICENSE_KEY__ || el.license.value || "").trim();
    if (!key) {
      throw new Error(
        "Dynamsoft Barcode Reader license key is required — apply for a free 30-day trial " +
        "and paste it in the Dynamsoft license field (or set DYNAMSOFT_LICENSE_KEY)"
      );
    }
    Dynamsoft.Core.CoreModule.engineResourcePaths.rootDirectory = "/sdk/";
    await Dynamsoft.License.LicenseManager.initLicense(key, true);
    await Dynamsoft.Core.CoreModule.loadWasm(["DBR"]);
    cvRouter = await Dynamsoft.CVR.CaptureVisionRouter.createInstance();
    await enableAllBarcodeFormats();
    dbrVersion = DBR_PINNED;
  }

  if (runs(SCANDIT_NAME)) {
    setStatus("Initializing Scandit Data Capture SDK…");
    const scanditKey = (window.__SCANDIT_LICENSE_KEY__ || el.scanditLicense.value).trim();
    if (!scanditKey) throw new Error("Scandit license key is required — paste it in the Scandit license field");
    scanditContext = await DataCaptureContext.forLicenseKey(scanditKey, {
      libraryLocation: "/scandit/barcode/sdc-lib/",
      moduleLoaders: [barcodeCaptureLoader()],
    });
    scanditContext.addListener({
      didChangeStatus: (_context, status) => {
        scanditStatus = status;
        if (!status.isValid) console.error(`Scandit status ${status.code}: ${status.message}`);
      },
    });
    const settings = new BarcodeBatchSettings();
    settings.enableSymbologies(SCANDIT_SYMBOLOGIES);
    settings.settingsForSymbology(Symbology.MSIPlessey).checksums = new Set([Checksum.Mod10]);
    scanditBatch = await BarcodeBatch.forContext(scanditContext, settings);
    await scanditBatch.setEnabled(false);
    scanditEnvironment = {
      scandit_core: SCANDIT_PINNED,
      scandit_barcode: SCANDIT_PINNED,
      scandit_symbologies: settings.enabledSymbologies,
      scandit_mode: "BarcodeBatch / MatrixScan, one ImageFrameSource.fromImageData frame per image",
    };
  }

  await fetch("/environment", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      userAgent: navigator.userAgent,
      hardwareConcurrency: navigator.hardwareConcurrency,
      decoders: activeDecoders,
      zxing_wasm: runs(ZXING_NAME) ? zxingVersion : "not run",
      dynamsoft_bundle: DBR_PINNED,
      dbr_engine: runs(DBR_NAME) ? dbrVersion : "not run",
      dbr_formats: runs(DBR_NAME) ? dbrFormats : "not run",
      ...(scanditEnvironment || {}),
    }),
  });

  setStatus(`${activeDecoders.join(" · ")} ready`);
  el.run.disabled = false;
  el.finalize.disabled = false;
  window.__bench.phase = "initialized";
}

// --- manifest + state ------------------------------------------------------

async function loadManifest() {
  const text = await (await fetch("/manifest")).text();
  manifest = text.split("\n").filter(Boolean).map((line) => JSON.parse(line));
  const state = await (await fetch("/state")).json();
  activeDecoders = state.decoders;
  dbrTemplate = state.dbr_template;
  completedKeys = new Set(state.completed);
  repetitions = state.repetitions;
  window.__bench.total = state.expected_records;
  progress(
    `Manifest: ${manifest.length} images · server already holds ${completedKeys.size}/${state.expected_records} records.`,
    completedKeys.size / Math.max(1, state.expected_records)
  );
}

// --- decode calls ----------------------------------------------------------

async function decodeWithZxing(canvas) {
  const begin = performance.now();
  try {
    // zxing-wasm 3.x does not accept a canvas element directly; ImageData is
    // the raw-pixel input shared with the DBR canvas path.
    const imageData = sharedCtx.getImageData(0, 0, canvas.width, canvas.height);
    const results = await ZXingWASM.readBarcodes(imageData);
    const decodeNs = Math.round((performance.now() - begin) * 1e6);
    return {
      predictions: (results || []).map((r) => ({
        format: String(r.format || ""),
        text: String(r.text || ""),
        raw_bytes_hex: "",
        confidence: null,
      })),
      decodeNs,
      error: null,
    };
  } catch (err) {
    return { predictions: [], decodeNs: Math.round((performance.now() - begin) * 1e6), error: `decoder_error: ${err.message || err}` };
  }
}

// Use the Web SDK's available barcode formats, including the postal formats.
async function enableAllBarcodeFormats() {
  const all = Dynamsoft.DBR.EnumBarcodeFormat.BF_ALL;
  const settings = await cvRouter.getSimplifiedSettings(dbrTemplate);
  settings.barcodeSettings.barcodeFormatIds = all;
  await cvRouter.updateSettings(dbrTemplate, settings);
  const effective = await cvRouter.getSimplifiedSettings(dbrTemplate);
  if (effective.barcodeSettings.barcodeFormatIds !== all) throw new Error("Dynamsoft did not enable BF_ALL");
  dbrFormats = "BF_ALL";
}

async function decodeWithDbr(canvas) {
  const begin = performance.now();
  try {
    const captured = await cvRouter.capture(canvas, dbrTemplate);
    const decodeNs = Math.round((performance.now() - begin) * 1e6);
    if (captured.errorCode) {
      return { predictions: [], decodeNs, error: "decoder_error: " + (captured.errorString || captured.errorCode) };
    }
    const items = typeof captured.getItems === "function" ? captured.getItems() : captured.items || [];
    const critBarcode = Dynamsoft.Core.EnumCapturedResultItemType.CRIT_BARCODE;
    const predictions = [];
    for (const item of items) {
      if (item.type !== undefined && item.type !== critBarcode) continue;
      predictions.push({
        format: String(item.formatString || (typeof item.getFormatString === "function" ? item.getFormatString() : "") || ""),
        text: String(item.text || ""),
        raw_bytes_hex: "",
        confidence: typeof item.confidence === "number" ? item.confidence : null,
      });
    }
    return { predictions, decodeNs, error: null };
  } catch (err) {
    return { predictions: [], decodeNs: Math.round((performance.now() - begin) * 1e6), error: `decoder_error: ${err.message || err}` };
  }
}

/**
 * Map a Scandit barcode to the canonical format names used by src/score.mjs.
 * EAN13UPCA is one Scandit symbology covering both EAN-13 and UPC-A; Scandit
 * returns UPC-A payloads as 13 digits with a leading zero, so it is split by
 * payload length. The UPC-A/EAN-13 bridge in the scorer handles the remaining
 * leading-zero cases.
 */
function scanditFormat(barcode) {
  const data = String(barcode.data || "");
  switch (barcode.symbology) {
    case Symbology.EAN13UPCA:
      if (/^\d{12}$/.test(data)) return "UPC_A";
      if (/^\d{8}$/.test(data)) return "EAN_8";
      return "EAN_13";
    case Symbology.UPCE: return "UPC_E";
    case Symbology.EAN8: return "EAN_8";
    case Symbology.Code39: return "CODE_39";
    case Symbology.Code93: return "CODE_93";
    case Symbology.Code128: return "CODE_128";
    case Symbology.Codabar: return "CODABAR";
    case Symbology.InterleavedTwoOfFive: return "ITF";
    case Symbology.IATATwoOfFive: return "IATA_2_OF_5";
    case Symbology.QR: return "QR_CODE";
    case Symbology.MicroQR: return "MICRO_QR";
    case Symbology.MaxiCode: return "MAXICODE";
    case Symbology.DotCode: return "DOTCODE";
    case Symbology.MSIPlessey: return "MSI_CODE";
    case Symbology.DataMatrix: return "DATA_MATRIX";
    case Symbology.Aztec: return "AZTEC";
    case Symbology.PDF417: return "PDF_417";
    case Symbology.KIX: return "KIX";
    case Symbology.RoyalMail4state: return "ROYAL_MAIL";
    case Symbology.USPSIntelligentMail: return "USPS_INTELLIGENT_MAIL";
    default: return new SymbologyDescription(barcode.symbology).readableName;
  }
}

async function decodeWithScandit(canvas) {
  const begin = performance.now();
  let listener = null;
  try {
    const imageData = sharedCtx.getImageData(0, 0, canvas.width, canvas.height);
    const found = [];
    let resolveDone;
    let settled = false;
    const done = new Promise((resolve) => {
      resolveDone = () => { if (!settled) { settled = true; resolve(); } };
    });
    listener = {
      didUpdateSession: (_batch, session) => {
        for (const tracked of session.addedTrackedBarcodes || []) found.push(tracked.barcode);
        resolveDone();
      },
    };
    scanditBatch.addListener(listener);
    const frameSource = await ImageFrameSource.fromImageData(imageData);
    await scanditContext.setFrameSource(frameSource);
    await scanditBatch.setEnabled(true);
    await frameSource.switchToDesiredState(FrameSourceState.On);
    // didUpdateSession fires for every processed frame, even when nothing is
    // found. A short safety timeout keeps one dropped frame from stalling the run.
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(scanditStatus && !scanditStatus.isValid
        ? `Scandit status ${scanditStatus.code}: ${scanditStatus.message}`
        : "Scandit did not acknowledge the frame")), 1200);
    });
    try {
      await Promise.race([done, timeout]);
    } finally {
      clearTimeout(timer);
    }
    const decodeNs = Math.round((performance.now() - begin) * 1e6);
    const predictions = found.map((barcode) => ({
      format: scanditFormat(barcode),
      text: String(barcode.data || ""),
      raw_bytes_hex: "",
      confidence: null,
    }));
    return { predictions, decodeNs, error: null };
  } catch (err) {
    return { predictions: [], decodeNs: Math.round((performance.now() - begin) * 1e6), error: `decoder_error: ${err.message || err}` };
  } finally {
    try {
      if (listener) scanditBatch.removeListener(listener);
      if (scanditBatch) await scanditBatch.setEnabled(false);
    } catch (_) { /* keep the decode result even if cleanup fails */ }
  }
}

// --- main loop -------------------------------------------------------------

async function loadImageCanvas(sample) {
  const begin = performance.now();
  const response = await fetch(`/images/${encodeURI(sample.relative_path)}`);
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${sample.relative_path}`);
  const blob = await response.blob();
  const bitmap = await createImageBitmap(blob);
  if (sharedCanvas.width !== bitmap.width || sharedCanvas.height !== bitmap.height) {
    sharedCanvas.width = bitmap.width;
    sharedCanvas.height = bitmap.height;
  }
  sharedCtx.drawImage(bitmap, 0, 0);
  const loadNs = Math.round((performance.now() - begin) * 1e6);
  bitmap.close();
  return loadNs;
}

async function postRecord(sample, decoder, decoderVersion, repetition, imageLoadNs, result) {
  const response = await fetch("/record", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      sample_id: sample.sample_id,
      decoder,
      decoder_version: decoderVersion,
      repetition,
      image_load_ns: imageLoadNs,
      decode_ns: result.decodeNs,
      error: result.error,
      predictions: result.predictions,
    }),
  });
  if (!response.ok) throw new Error((await response.json()).error);
}

async function runBenchmark() {
  stopRequested = false;
  el.run.disabled = true;
  el.stop.disabled = false;
  window.__bench.phase = "running";
  window.__bench.startedAt = Date.now();
  if (!manifest.length) await loadManifest();

  const totalUnits = manifest.length * repetitions;
  let doneUnits = 0;

  for (let repetition = 0; repetition < repetitions; repetition++) {
    for (const sample of manifest) {
      if (stopRequested) break;
      doneUnits++;
      const order = await shuffledDecoders(sample.sample_id, repetition);
      const pending = order.filter(
        (decoder) => !completedKeys.has(`${sample.sample_id}|${decoder}|${repetition}`)
      );
      if (!pending.length) {
        if (doneUnits % 200 === 0) {
          progress(`repetition=${repetition + 1} progress=${doneUnits}/${totalUnits} (all cached)`, doneUnits / totalUnits);
          await new Promise((r) => setTimeout(r));
        }
        continue;
      }

      let imageLoadNs = 0;
      let loadError = null;
      try {
        imageLoadNs = await loadImageCanvas(sample);
      } catch (err) {
        loadError = `input_pipeline_error: ${err.message || err}`;
      }

      for (const decoder of order) {
        const key = `${sample.sample_id}|${decoder}|${repetition}`;
        if (completedKeys.has(key)) continue;
        let result;
        if (loadError) {
          result = { predictions: [], decodeNs: 0, error: loadError };
        } else if (decoder === ZXING_NAME) {
          result = await decodeWithZxing(sharedCanvas);
        } else if (decoder === DBR_NAME) {
          result = await decodeWithDbr(sharedCanvas);
        } else {
          result = await decodeWithScandit(sharedCanvas);
        }
        await postRecord(
          sample, decoder,
          decoder === ZXING_NAME ? zxingVersion : decoder === DBR_NAME ? dbrVersion : scanditVersion,
          repetition, loadError ? 0 : imageLoadNs, result
        );
        completedKeys.add(key);
        const s = stats[decoder];
        s.images++;
        s.barcodes += result.predictions.length;
        s.totalDecodeMs += result.decodeNs / 1e6;
        window.__bench.done = completedKeys.size;
      }

      if (doneUnits % 25 === 0 || doneUnits === totalUnits) {
        const elapsed = (Date.now() - window.__bench.startedAt) / 1000;
        const rate = doneUnits / Math.max(1, elapsed);
        const eta = rate ? (totalUnits - doneUnits) / rate : 0;
        progress(
          `repetition=${repetition + 1} image ${doneUnits}/${totalUnits} · ${sample.relative_path} · ` +
          `ETA ${Math.round(eta / 60)} min`,
          doneUnits / totalUnits
        );
        renderLiveStats();
        await new Promise((r) => setTimeout(r));
      }
    }
    if (stopRequested) break;
  }

  window.__bench.phase = stopRequested ? "stopped" : "finished";
  el.run.disabled = false;
  el.stop.disabled = true;
  progress(
    stopRequested
      ? `Stopped by user. ${completedKeys.size} records stored — press Run to resume.`
      : `Finished. ${completedKeys.size} records stored. Press Finalize to build summary.json.`,
    stopRequested ? 0.5 : 1
  );
  renderLiveStats();
}

function renderLiveStats() {
  const rows = [ZXING_NAME, DBR_NAME, SCANDIT_NAME].map((name) => {
    const s = stats[name];
    const mean = s.images ? (s.totalDecodeMs / s.images).toFixed(2) : "—";
    return `<div class="stat-card"><strong>${name}</strong><span>${s.images} images · ${s.barcodes} barcodes · mean ${mean} ms (session)</span></div>`;
  });
  el.liveStats.innerHTML = rows.join("");
}

async function finalize() {
  el.finalize.disabled = true;
  progress("Finalizing summary…", 1);
  try {
    const response = await fetch("/finalize", { method: "POST" });
    const summary = await response.json();
    if (!response.ok) throw new Error(summary.error);
    renderSummary(summary);
  } finally {
    el.finalize.disabled = false;
  }
}

function renderSummary(summary) {
  const headers = ["Decoder", "Correct", "Recall", "Precision", "Misses", "False positives", "P50", "P95"];
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  for (const label of headers) {
    const cell = document.createElement("th");
    cell.textContent = label;
    head.append(cell);
  }
  const body = table.createTBody();
  const pct = (value) => value == null ? "—" : (value * 100).toFixed(2) + "%";
  for (const [name, data] of Object.entries(summary.decoders)) {
    const row = body.insertRow();
    for (const value of [name, data.correct + " / " + data.truth, pct(data.recall), pct(data.precision),
      data.misses, data.false_positives, data.timing_ms.p50.toFixed(2) + " ms", data.timing_ms.p95.toFixed(2) + " ms"]) {
      row.insertCell().textContent = value;
    }
  }
  el.summary.replaceChildren(table);
}

el.init.addEventListener("click", () =>
  initSdk().catch((err) => {
    window.__bench.errors.push(String(err.message || err));
    setStatus(`Init failed: ${err.message || err}`);
  })
);
el.run.addEventListener("click", () =>
  runBenchmark().catch((err) => {
    window.__bench.errors.push(String(err.message || err));
    window.__bench.phase = 'stopped';
    el.run.disabled = false;
    el.stop.disabled = true;
    progress(`Run failed: ${err.message || err}`, 0);
  })
);
el.stop.addEventListener("click", () => {
  stopRequested = true;
});
el.finalize.addEventListener("click", () =>
  finalize().catch((err) => progress(`Finalize failed: ${err.message || err}`, 1))
);

loadManifest().catch((err) => progress(`Manifest load failed: ${err.message || err}`, 0));
