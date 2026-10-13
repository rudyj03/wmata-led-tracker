#!/usr/bin/env python3
"""
train_poller.py

Polls WMATA's live TrainPositions feed and maps each train onto the
topology built by topology_builder.py, producing a clean state list:

    [
      {"train_id": "081", "line": "RD", "direction": 1,
       "destination": "Shady Gr",
       "position": {"status": "at", "station": "A15"}},
      {"train_id": "093", "line": "RD", "direction": 2,
       "destination": "Glenmont",
       "position": {"status": "between", "from": "A14", "to": "A15",
                     "fraction": 0.4}},
      ...
    ]

`position.station` / `.from` / `.to` are physical_station keys from
topology.json (i.e. already collapsed across interchange codes).

If a train's circuit can't be resolved (pocket track, crossover near a
terminus), the train is left out of the state list.

This script only prints state to the terminal for now (render_terminal).
Swap `render_terminal` for an LED-driving function later -- everything
upstream of render() stays the same.

Usage:
    export WMATA_API_KEY=your_key_here
    python3 train_poller.py --topology topology.json [--interval 12]
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse

TRAIN_POSITIONS_BASE_URL = "https://api.wmata.com/TrainPositions"


def fetch(base_url: str, endpoint: str, api_key: str, params: dict | None = None) -> dict:
    all_params = {"contentType": "json"}
    if params:
        all_params.update(params)
    url = f"{base_url}/{endpoint}?" + urllib.parse.urlencode(all_params)
    req = urllib.request.Request(url, headers={"api_key": api_key})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


class CircuitIndex:
    """Flat circuit_id -> location lookup, built once from topology.json."""

    def __init__(self, topology: dict):
        # Keyed by (line, circuit_id): trunk circuits shared by several lines
        # (e.g. OR/SV/BL) appear in each line's sequence, so circuit_id alone
        # would let one line's entry overwrite another's.
        self.circuit_info = {}          # (line, circuit_id) -> dict(track, seq, station)
        self.lines_for_circuit = {}     # circuit_id -> [line, ...]
        self.sequences = {}             # (line, track) -> ordered list of station-or-None

        for line, tracks in topology["circuits"].items():
            for track, circuits in tracks.items():
                stations = []
                for seq, c in enumerate(circuits):
                    cid = c["circuit_id"]
                    physical = topology["code_to_physical"].get(c["station_code"]) if c["station_code"] else None
                    self.circuit_info[(line, cid)] = {"track": track, "seq": seq, "station": physical}
                    self.lines_for_circuit.setdefault(cid, []).append(line)
                    stations.append(physical)
                self.sequences[(line, track)] = stations

    def locate(self, line: str, circuit_id: int):
        """Returns an "at" or "between" position, or None if the circuit is
        unknown or off the end of the line (pocket/yard tracks)."""
        info = self.circuit_info.get((line, circuit_id))
        if info is None:
            # Train's line doesn't include this circuit -- borrow any line that does.
            other_lines = self.lines_for_circuit.get(circuit_id)
            if not other_lines:
                return None
            line = other_lines[0]
            info = self.circuit_info[(line, circuit_id)]

        if info["station"] is not None:
            return {"status": "at", "station": info["station"]}

        # Walk outward along the same (line, track) sequence to find the
        # nearest station-tagged circuits on either side.
        stations = self.sequences[(line, info["track"])]
        idx = info["seq"]

        prev_seq = next((i for i in range(idx - 1, -1, -1) if stations[i] is not None), None)
        next_seq = next((i for i in range(idx + 1, len(stations)) if stations[i] is not None), None)
        if prev_seq is None or next_seq is None:
            return None

        # Circuit count is a stand-in for distance -- circuits aren't uniform
        # length, but it's the finest per-train position the API offers.
        fraction = (idx - prev_seq) / (next_seq - prev_seq)
        frm, to = stations[prev_seq], stations[next_seq]

        # Orient from/to/fraction in the direction of travel. Track1 trains
        # move up the circuit sequence and Track2 trains move down it
        # (checked against live polls) -- the track is more reliable than
        # the feed's DirectionNum, which occasionally disagrees.
        if info["track"] == "Track2":
            frm, to, fraction = to, frm, 1.0 - fraction

        return {"status": "between", "from": frm, "to": to, "fraction": round(fraction, 3)}


def get_live_trains(api_key: str) -> list[dict]:
    data = fetch(TRAIN_POSITIONS_BASE_URL, "TrainPositions", api_key)
    return data["TrainPositions"]


def build_state(trains: list[dict], index: CircuitIndex) -> list[dict]:
    """
    Build train state strictly from the current WMATA API response.

    Trains on circuits that resolve to neither a station nor a span
    between two stations are left out.
    No last-known-position persistence is used.
    """
    state = []

    for t in trains:
        if not t.get("LineCode"):
            continue

        position = index.locate(t["LineCode"], t["CircuitId"])

        if position is None:
            continue

        state.append({
            "train_id": t["TrainId"],
            "line": t["LineCode"],
            "direction": t.get("DirectionNum"),
            "position": position,
        })

    return state


def render_terminal(state: list[dict], topology: dict):
    name_of = {code: info["name"] for code, info in topology["physical_stations"].items()}
    os.system("clear" if os.name == "posix" else "cls")
    print(f"{'Line':4} {'Train':6} {'Dest':16} Position")
    print("-" * 60)
    for t in sorted(state, key=lambda x: x["line"]):
        p = t["position"]
        held_suffix = " [holding]" if p.get("held") else ""
        if p["status"] == "at":
            pos_str = name_of.get(p["station"], p["station"]) + held_suffix
        elif p["status"] == "between":
            frm = name_of.get(p["from"], p["from"])
            to = name_of.get(p["to"], p["to"])
            pos_str = f"{frm} -> {to} ({p['fraction']*100:.0f}%)" + held_suffix
        else:
            pos_str = f"unknown (circuit {p['circuit_id']})"
        print(f"{t['line']:4} {t['train_id']:6} {str(t.get('destination', ''))[:16]:16} {pos_str}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", default="topology.json")
    parser.add_argument("--interval", type=float, default=12.0, help="Seconds between polls")
    parser.add_argument("--api-key", default=os.environ.get("WMATA_API_KEY"))
    args = parser.parse_args()

    if not args.api_key:
        sys.exit("Set WMATA_API_KEY or pass --api-key.")

    with open(args.topology) as f:
        topology = json.load(f)

    index = CircuitIndex(topology)

    print(f"Polling every {args.interval}s. Ctrl+C to stop.", file=sys.stderr)
    try:
        while True:
            trains = get_live_trains(args.api_key)
            state = build_state(trains, index)
            render_terminal(state, topology)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
