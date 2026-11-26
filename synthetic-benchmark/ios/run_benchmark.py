"""Drive the iOS benchmark app over HTTP and record one pass over a dataset.

The app (ios/BarcodeBenchmark) exposes POST /api/benchmark, which decodes one
uploaded image with Dynamsoft Barcode Reader, Google ML Kit, Apple Vision and
ZXing-C++ and returns every prediction plus the per-SDK wall clock. This runner
walks the dataset manifest, uploads each JPEG to the phone over Wi-Fi or the USB
link, and appends the raw response to results.jsonl so an interrupted pass can
resume.

    python ios/run_benchmark.py --dataset dataset-by-format \\
        --host 169.254.35.41 --output .runs/ios-next/results.jsonl

The phone shows its address on the home screen once the built-in server is up.
"""

import argparse
import http.client
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DECODERS = "dbr,mlkit,vision,zxing"


def multipart(path, field="file", file_type="image", decoders=DECODERS):
    boundary = "----benchmark" + uuid.uuid4().hex
    filename = os.path.basename(path)
    parts = [
        ("--" + boundary + "\r\n").encode(),
        b'Content-Disposition: form-data; name="fileType"\r\n\r\n' + file_type.encode() + b"\r\n",
        ("--" + boundary + "\r\n").encode(),
        b'Content-Disposition: form-data; name="decoders"\r\n\r\n' + decoders.encode() + b"\r\n",
        ("--" + boundary + "\r\n").encode(),
        ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (field, filename)).encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        Path(path).read_bytes(),
        ("\r\n--" + boundary + "--\r\n").encode(),
    ]
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


class Client:
    def __init__(self, host, port, timeout, decoders=DECODERS):
        self.host, self.port, self.timeout = host, port, timeout
        self.decoders = decoders
        self.conn = None

    def connect(self):
        if self.conn is None:
            self.conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        return self.conn

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def status(self):
        conn = self.connect()
        try:
            conn.request("GET", "/api/status")
            response = conn.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            self.close()

    def benchmark(self, image_path):
        body, content_type = multipart(image_path, decoders=self.decoders)
        conn = self.connect()
        try:
            conn.request("POST", "/api/benchmark", body, {"Content-Type": content_type})
            response = conn.getresponse()
            payload = response.read()
        finally:
            # The app answers HTTP/1.1 and drops the socket after every response.
            # Reusing a keep-alive socket costs a stalled read before the retry,
            # and occasionally wedges until the timeout, so start fresh each time.
            self.close()
        if response.status != 200:
            raise RuntimeError("HTTP %s: %s" % (response.status, payload[:200]))
        return json.loads(payload.decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=Path("dataset-by-format"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", required=True, help="address shown by the app, e.g. 192.168.1.42")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--flush-every", type=int, default=25)
    parser.add_argument("--decoders", default=DECODERS,
                        help="comma-separated readers the app should run: dbr, mlkit, vision, zxing")
    parser.add_argument("--restart-cmd", default="",
                        help="shell command that relaunches the app when a socket wedges")
    parser.add_argument("--allow-missing-license", action="store_true",
                        help="continue when the Dynamsoft trial key is rejected")
    args = parser.parse_args()

    manifest = args.dataset / "manifest.jsonl"
    samples = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        samples = samples[: args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["sample_id"])
    pending = [s for s in samples if s["sample_id"] not in done]

    client = Client(args.host, args.port, args.timeout, args.decoders)
    status, info = client.status()
    if status != 200:
        raise SystemExit("Benchmark server not ready: %s %s" % (status, info))
    print("server:", info, flush=True)
    if info.get("dynamsoftLicense") not in (None, "valid") and not args.allow_missing_license:
        raise SystemExit("Dynamsoft license state is %r; fix the key or pass --allow-missing-license"
                         % info.get("dynamsoftLicense"))
    print("resume: %d recorded, %d pending" % (len(done), len(pending)), flush=True)

    started = time.time()
    failures = 0
    with args.output.open("a", encoding="utf-8", newline="\n") as sink:
        for index, sample in enumerate(pending, 1):
            path = args.dataset / sample["relative_path"]
            attempt = 0
            while True:
                try:
                    response = client.benchmark(path)
                    break
                except Exception as error:  # noqa: BLE001 - retry any transport failure
                    attempt += 1
                    client.close()
                    if attempt > args.retries:
                        failures += 1
                        response = {"error": "%s: %s" % (type(error).__name__, error)}
                        break
                    if args.restart_cmd and attempt > 1:
                        print("  %s stalled (%s), relaunching the app" % (sample["sample_id"], type(error).__name__),
                              flush=True)
                        os.system(args.restart_cmd)
                        time.sleep(4)
                    else:
                        time.sleep(1.5 * attempt)
            record = {
                "sample_id": sample["sample_id"],
                "file": sample["relative_path"],
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "response": response,
            }
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            if index % args.flush_every == 0:
                sink.flush()
            if index % 50 == 0 or index == len(pending):
                elapsed = time.time() - started
                rate = index / elapsed if elapsed else 0
                remaining = (len(pending) - index) / rate if rate else 0
                print("%5d/%d  %5.2f img/s  eta %4.1f min  failures %d"
                      % (index, len(pending), rate, remaining / 60, failures), flush=True)

    client.close()
    print("done: %d processed, %d transport failures, %.1f min"
          % (len(pending), failures, (time.time() - started) / 60), flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
