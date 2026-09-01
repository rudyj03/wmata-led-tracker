#!/usr/bin/env python3
"""
server.py

Runs the train poller in a background thread and serves:
  - GET /                -> static/index.html (the visualizer)
  - GET /api/topology     -> minimal static topology (stations + lines) for drawing the map
  - GET /api/state        -> current live train state (refreshed by the background poller)

Usage:
    export WMATA_API_KEY=your_key_here
    python3 server.py --topology topology.json [--interval 12] [--port 8765]

Then open http://localhost:8765 in a browser.
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from train_poller import CircuitIndex, get_live_trains, build_state

STATE_LOCK = threading.Lock()
SHARED = {"state": [], "last_updated": None, "error": None}


def make_topology_summary(topology: dict) -> dict:
    """Trim topology.json down to just what the frontend needs to draw the map."""
    stations = {
        code: {
            "name": info["name"],
            "lat": info["lat"],
            "lon": info["lon"],
            "lines": info["lines"],
        }
        for code, info in topology["physical_stations"].items()
    }
    lines = {
        line: info["physical_station_order"]
        for line, info in topology["lines"].items()
    }
    return {"stations": stations, "lines": lines}


def poll_loop(api_key: str, index: CircuitIndex, interval: float):
    last_known: dict = {}
    while True:
        try:
            trains = get_live_trains(api_key)
            state = build_state(trains, index, last_known)
            with STATE_LOCK:
                SHARED["state"] = state
                SHARED["last_updated"] = time.time()
                SHARED["error"] = None
        except Exception as e:  # keep serving stale state rather than dying
            with STATE_LOCK:
                SHARED["error"] = str(e)
            print(f"[poll_loop] error: {e}", file=sys.stderr)
        time.sleep(interval)


def make_handler(static_dir: Path, topology_summary: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # keep the terminal quiet; state.error is what matters

        def _send_json(self, payload: dict, status: int = 200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/state":
                with STATE_LOCK:
                    self._send_json({
                        "trains": SHARED["state"],
                        "last_updated": SHARED["last_updated"],
                        "error": SHARED["error"],
                    })
                return

            if self.path == "/api/topology":
                self._send_json(topology_summary)
                return

            # Static files -- default to index.html
            req_path = self.path.lstrip("/") or "index.html"
            file_path = (static_dir / req_path).resolve()
            if static_dir.resolve() not in file_path.parents and file_path != static_dir.resolve():
                self.send_error(403)
                return
            if not file_path.is_file():
                self.send_error(404)
                return

            content_type = "text/html" if file_path.suffix == ".html" else \
                           "application/javascript" if file_path.suffix == ".js" else \
                           "text/css" if file_path.suffix == ".css" else \
                           "application/octet-stream"
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", default="topology.json")
    parser.add_argument("--interval", type=float, default=12.0)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--api-key", default=os.environ.get("WMATA_API_KEY"))
    args = parser.parse_args()

    if not args.api_key:
        sys.exit("Set WMATA_API_KEY or pass --api-key.")

    with open(args.topology) as f:
        topology = json.load(f)

    index = CircuitIndex(topology)
    topology_summary = make_topology_summary(topology)

    t = threading.Thread(target=poll_loop, args=(args.api_key, index, args.interval), daemon=True)
    t.start()

    static_dir = Path(__file__).parent / "static"
    handler = make_handler(static_dir, topology_summary)
    httpd = ThreadingHTTPServer(("localhost", args.port), handler)
    print(f"Serving on http://localhost:{args.port} (polling every {args.interval}s)", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()