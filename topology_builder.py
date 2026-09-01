#!/usr/bin/env python3
"""
topology_builder.py

Builds a static topology map of the WMATA Metrorail system and caches it
to topology.json. This only needs to be re-run when WMATA changes the
system (new station, new line segment) — not on every poll.

Two layers are built:

1. Station-level topology (for LED board layout):
   line_code -> ordered list of station codes from one terminus to the other.

2. Circuit-level topology (for mapping live train positions to segments):
   line_code -> track -> ordered list of {circuit_id, station_code | None}
   Station codes appear only at the circuits that coincide with a platform;
   everything between two station-tagged circuits is "between A and B".

Interchange stations (e.g. Metro Center, Gallery Place, L'Enfant Plaza,
Fort Totten) get grouped into a single "physical station" via
StationTogether1 / StationTogether2, since your LED board almost certainly
wants one LED per physical station, not one per line-specific code.

Usage:
    export WMATA_API_KEY=your_key_here
    python3 topology_builder.py [--out topology.json]
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse

# Rail.svc hosts the static station/line endpoints (jStationInfo, jStations...).
RAIL_BASE_URL = "https://api.wmata.com/Rail.svc/json"
# StandardRoutes and TrackCircuits live under a separate API family,
# NOT under Rail.svc -- this is the part that 404s if you group them together.
TRAIN_POSITIONS_BASE_URL = "https://api.wmata.com/TrainPositions"
LINE_CODES = ["RD", "BL", "YL", "OR", "GR", "SV"]


def fetch(base_url: str, endpoint: str, api_key: str, params: dict | None = None) -> dict:
    url = f"{base_url}/{endpoint}"
    all_params = {"contentType": "json"}
    if params:
        all_params.update(params)
    url += "?" + urllib.parse.urlencode(all_params)
    req = urllib.request.Request(url, headers={"api_key": api_key})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_all_stations(api_key: str) -> dict:
    """Fetch jStationInfo and group into physical stations."""
    data = fetch(RAIL_BASE_URL, "jStations", api_key)["Stations"]

    stations = {}
    for s in data:
        stations[s["Code"]] = {
            "name": s["Name"],
            "lat": s["Lat"],
            "lon": s["Lon"],
            "lines": [s[k] for k in ("LineCode1", "LineCode2", "LineCode3", "LineCode4") if s.get(k)],
            "together": [c for c in (s.get("StationTogether1"), s.get("StationTogether2")) if c],
        }

    # Union-find style grouping of codes that are "together" into one
    # physical station, so interchange stations collapse to a single node.
    parent = {code: code for code in stations}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for code, info in stations.items():
        for other in info["together"]:
            if other in stations:
                union(code, other)

    groups: dict[str, list[str]] = {}
    for code in stations:
        root = find(code)
        groups.setdefault(root, []).append(code)

    physical_stations = {}
    for root, codes in groups.items():
        codes = sorted(codes)
        primary = stations[root]
        physical_stations[root] = {
            "name": primary["name"],
            "codes": codes,
            "lines": sorted({ln for c in codes for ln in stations[c]["lines"]}),
            "lat": primary["lat"],
            "lon": primary["lon"],
        }

    code_to_physical = {code: find(code) for code in stations}
    return stations, physical_stations, code_to_physical


def get_line_station_order(api_key: str, line_code: str) -> list[str]:
    """Ordered list of station codes for a line, terminus to terminus."""
    data = fetch(RAIL_BASE_URL, "jStations", api_key, {"LineCode": line_code})
    return [s["Code"] for s in data["Stations"]]


def get_standard_routes(api_key: str) -> dict:
    """
    StandardRoutes (under the TrainPositions API, NOT Rail.svc) gives,
    per line/track, the ordered sequence of track circuits with station
    codes attached where a circuit coincides with a platform. This is
    what lets you turn a live CircuitId into "between station A and B" --
    and, as it turns out, it's also the authoritative source for true
    end-to-end physical station order (see build_physical_order_from_circuits).
    """
    data = fetch(TRAIN_POSITIONS_BASE_URL, "StandardRoutes", api_key)["StandardRoutes"]

    routes: dict[str, dict[str, list[dict]]] = {}
    for route in data:
        line = route["LineCode"]
        track = f"Track{route['TrackNum']}"
        circuits = [
            {"circuit_id": c["CircuitId"], "station_code": c.get("StationCode") or None}
            for c in sorted(route["TrackCircuits"], key=lambda c: c["SeqNum"])
        ]
        routes.setdefault(line, {})[track] = circuits
    return routes


def build_physical_order_from_circuits(line_code: str, circuits_by_line: dict, code_to_physical: dict) -> list[str]:
    """
    jStations returns stations sorted by station code, which is NOT the
    same as true end-to-end travel order for lines whose code numbering
    fans out from a downtown hub (e.g. Red Line: A01..A15 outbound one
    way, B01..B11 outbound the other way, concatenated -- not a single
    continuous traversal). Track circuits, on the other hand, are laid
    out in genuine physical sequence ("west to east, south to north"
    per WMATA's own docs), so we derive station order from there instead.

    Prefers Track1, falls back to Track2; skips Track0 (crossovers) and
    Track3 (pocket tracks), which aren't part of the main revenue path.
    Collapses consecutive duplicate physical stations (interchange
    stations sometimes have two adjacent station-tagged circuits).
    """
    tracks = circuits_by_line.get(line_code, {})
    for track_name in ("Track1", "Track2"):
        circuits = tracks.get(track_name)
        if not circuits:
            continue
        order = []
        for c in circuits:
            if not c["station_code"]:
                continue
            physical = code_to_physical.get(c["station_code"], c["station_code"])
            if not order or order[-1] != physical:
                order.append(physical)
        if order:
            return order
    return []


def build_topology(api_key: str) -> dict:
    print("Fetching station info...", file=sys.stderr)
    stations, physical_stations, code_to_physical = get_all_stations(api_key)

    print("Fetching per-line station order (jStations, for reference)...", file=sys.stderr)
    raw_line_codes = {}
    for line_code in LINE_CODES:
        try:
            order = get_line_station_order(api_key, line_code)
        except Exception as e:
            print(f"  skipping {line_code}: {e}", file=sys.stderr)
            continue
        raw_line_codes[line_code] = order
        time.sleep(0.2)  # be polite to the API

    print("Fetching standard routes (track circuits)...", file=sys.stderr)
    circuits_by_line = get_standard_routes(api_key)

    print("Deriving true physical station order from track circuits...", file=sys.stderr)
    lines = {}
    for line_code, station_codes in raw_line_codes.items():
        physical_order = build_physical_order_from_circuits(line_code, circuits_by_line, code_to_physical)
        if not physical_order:
            # Fallback: no circuit data for this line, use jStations order
            # (deduped) rather than leaving it empty.
            physical_order = []
            for c in station_codes:
                p = code_to_physical.get(c, c)
                if not physical_order or physical_order[-1] != p:
                    physical_order.append(p)
            print(f"  {line_code}: no circuit data, fell back to jStations order", file=sys.stderr)
        lines[line_code] = {
            "station_codes": station_codes,
            "physical_station_order": physical_order,
        }

    return {
        "generated_from": "WMATA Rail.svc + TrainPositions API",
        "stations": stations,
        "physical_stations": physical_stations,
        "code_to_physical": code_to_physical,
        "lines": lines,
        "circuits": circuits_by_line,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="topology.json", help="Output path")
    parser.add_argument("--api-key", default=os.environ.get("WMATA_API_KEY"))
    args = parser.parse_args()

    if not args.api_key:
        sys.exit("Set WMATA_API_KEY or pass --api-key. Get one free at developer.wmata.com")

    topology = build_topology(args.api_key)

    with open(args.out, "w") as f:
        json.dump(topology, f, indent=2)

    n_stations = len(topology["physical_stations"])
    n_lines = len(topology["lines"])
    print(f"Wrote {args.out}: {n_stations} physical stations across {n_lines} lines.", file=sys.stderr)


if __name__ == "__main__":
    main()