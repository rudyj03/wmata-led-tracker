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
terminus), its last known resolved position is reused instead of
reporting "unknown" -- that position dict will have `"held": True`.

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
        self.circuit_info = {}          # circuit_id -> dict(station)

        for tracks in topology["circuits"].values():
            for circuits in tracks.values():
                for c in circuits:
                    cid = c["circuit_id"]
                    physical = topology["code_to_physical"].get(c["station_code"]) if c["station_code"] else None
                    self.circuit_info[cid] = {"station": physical}

    def locate(self, circuit_id: int):
        """Returns an at-station position, or None for any other circuit."""
        info = self.circuit_info.get(circuit_id)
        if info is None or info["station"] is None:
            return None

        return {"status": "at", "station": info["station"]}


def get_live_trains(api_key: str) -> list[dict]:
    data = fetch(TRAIN_POSITIONS_BASE_URL, "TrainPositions", api_key)
    return data["TrainPositions"]


def build_state(trains: list[dict], index: CircuitIndex) -> list[dict]:
    """
    Build train state strictly from the current WMATA API response.

    If a train is on an unknown/unmapped circuit, do not display it.
    No last-known-position persistence is used.
    """
    state = []

    for t in trains:
        if not t.get("LineCode"):
            continue

        position = index.locate(t["CircuitId"])

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
        print(f"{t['line']:4} {t['train_id']:6} {str(t['destination'])[:16]:16} {pos_str}")


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
