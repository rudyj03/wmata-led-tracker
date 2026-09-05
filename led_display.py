#!/usr/bin/env python3
"""
led_display.py

Drives your physical board's LEDs from live train state. Reuses
topology.json + chain_order.json (from generate_board_template.py) and
CircuitIndex/get_live_trains/build_state (from train_poller.py).

Two renderers:
  - SimulateRenderer: prints a colored terminal swatch per LED. No
    hardware required -- use this to test the mapping/blending logic
    before your level shifter arrives.
  - HardwareRenderer: drives a real WS2812 chain via rpi_ws281x. Only
    works on the Pi, with the level shifter wired up.

Design notes baked into this script:
  - chain_order.json entries are either "station" (one LED per physical
    station) or "midpoint" (one LED roughly halfway along a track
    segment between two adjacent stations, deduped across lines that
    share trunk track). A train reported "between" two stations lights
    the midpoint LED for that segment if its fraction falls in the
    middle band (MID_BAND_LOW..MID_BAND_HIGH); otherwise it snaps to
    whichever endpoint station it's closer to, same as before midpoints
    existed. If chain_order.json has no midpoint entries (built with
    --no-midpoints), every "between" position just snaps to the nearer
    station -- this script doesn't require midpoints to be present.
  - Idle nodes render dim in their line's color(s) so the map shape is
    always visible. A node with an active train renders bright. Nodes
    serving more than one active line CYCLE through each line's color
    in turn (rather than blending) -- clearer than a muddy averaged
    color, at the cost of needing a render tick that's faster than the
    WMATA poll interval (see --cycle-interval).

Usage:
    # test the mapping logic with no hardware at all:
    python3 led_display.py --topology topology.json --chain-order chain_order.json --simulate

    # once the level shifter is wired up, on the Pi:
    sudo python3 led_display.py --topology topology.json --chain-order chain_order.json
"""

import argparse
import json
import os
import sys
import time

from train_poller import CircuitIndex, get_live_trains, build_state

LINE_COLORS_RGB = {
    "RD": (255, 0, 0),
    "GR": (0, 255, 0),
    "BL": (0, 0, 255),
    "OR": (255, 70, 0),
    "YL": (255, 255, 0),
    "SV": (180, 195, 215),
}

IDLE_LINE_COLORS_RGB = {
    "RD": (255, 0, 0),
    "OR": (255, 140, 0),
    "YL": (255, 255, 0),
    "GR": (0, 200, 70),
    "BL": (0, 180, 255),
    "SV": (210, 225, 255),
}

IDLE_BRIGHTNESS = 0.00   # idle nodes render at 18% of their line color
ACTIVE_BRIGHTNESS = 0.50
MID_BAND_LOW = 0.3       # fraction range along a segment that counts as
MID_BAND_HIGH = 0.7      # "at the midpoint" rather than "near an endpoint"


def scale(rgb, factor):
    return tuple(min(255, int(c * factor)) for c in rgb)


def blend(colors):
    """Average a list of RGB tuples."""
    n = len(colors)
    return tuple(sum(c[i] for c in colors) // n for i in range(3))


class LayoutIndex:
    """Maps physical stations AND midpoint segments to their chain index,
    built entirely from chain_order.json (the single source of truth for
    wiring order) plus topology.json for line-color lookups."""

    def __init__(self, topology: dict, chain_order: dict):
        self.station_to_index = {}
        self.segment_to_index = {}   # frozenset({a,b}) -> index
        self.idle_color = {}
        self.label_by_index = {}
        self.num_leds = len(chain_order["chain_order"])

        for entry in chain_order["chain_order"]:
            idx = entry["index"]
            self.label_by_index[idx] = entry["name"]

            if entry["type"] == "station":
                code = entry["physical_station"]
                self.station_to_index[code] = idx
                lines = topology["physical_stations"][code]["lines"]
            else:  # midpoint
                key = frozenset(entry["segment"])
                self.segment_to_index[key] = idx
                lines = entry["lines"]

            colors = [IDLE_LINE_COLORS_RGB[ln] for ln in lines if ln in LINE_COLORS_RGB]
            self.idle_color[idx] = scale(blend(colors) if colors else (255, 255, 255), IDLE_BRIGHTNESS)


def compute_frame(state: list, layout: LayoutIndex, cycle_tick: int = 0) -> list:
    """Returns a list of (r,g,b) tuples, one per LED index, 0..num_leds-1.

    cycle_tick selects which line's color to show at a node currently
    serving more than one active line -- advance it once per render tick
    (not once per WMATA poll) to get a visible cycling animation rather
    than blended colors."""
    frame = [layout.idle_color.get(i, (0, 0, 0)) for i in range(layout.num_leds)]

    active_by_index: dict = {}  # led index -> list of line colors currently present
    for t in state:
        p = t["position"]
        color = LINE_COLORS_RGB.get(t["line"])
        if color is None:
            continue

        idx = None
        if p["status"] == "at":
            idx = layout.station_to_index.get(p["station"])
        elif p["status"] == "between":
            continue
        # status == "unknown" (never held) -> nothing to show yet

        if idx is None:
            continue
        active_by_index.setdefault(idx, []).append(color)

    for idx, colors in active_by_index.items():
        # dedupe consecutive-identical colors (e.g. two Red Line trains at
        # the same node) so the cycle doesn't pointlessly "blink" on the
        # same color -- only distinct line colors get cycled through
        distinct = list(dict.fromkeys(colors))
        chosen = distinct[cycle_tick % len(distinct)]
        frame[idx] = scale(chosen, ACTIVE_BRIGHTNESS)

    return frame


class SimulateRenderer:
    def __init__(self, layout: LayoutIndex):
        self.layout = layout

    def render(self, frame: list):
        os.system("clear" if os.name == "posix" else "cls")
        print(f"{len(frame)} LEDs (simulate mode -- no hardware)\n")
        for idx, (r, g, b) in enumerate(frame):
            swatch = f"\033[48;2;{r};{g};{b}m  \033[0m"
            name = self.layout.label_by_index.get(idx, "?")
            print(f"{idx:3} {swatch} {name}")


class HardwareRenderer:
    def __init__(self, num_leds: int, gpio_pin: int = 18, brightness: int = 128):
        from rpi_ws281x import PixelStrip, Color  # imported lazily -- only needed on the Pi
        self.Color = Color
        self.strip = PixelStrip(num_leds, gpio_pin, brightness=brightness)
        self.strip.begin()

    def render(self, frame: list):
        for idx, (r, g, b) in enumerate(frame):
            self.strip.setPixelColor(idx, self.Color(g, r, b))
        self.strip.show()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", default="topology.json")
    parser.add_argument("--chain-order", default="chain_order.json")
    parser.add_argument("--interval", type=float, default=12.0, help="Seconds between WMATA polls")
    parser.add_argument("--cycle-interval", type=float, default=1.5,
                         help="Seconds between render ticks -- controls how fast nodes serving "
                              "multiple active lines cycle between colors")
    parser.add_argument("--simulate", action="store_true", help="Print to terminal instead of driving real hardware")
    parser.add_argument("--gpio-pin", type=int, default=18)
    parser.add_argument("--brightness", type=int, default=128, help="0-255, hardware mode only")
    parser.add_argument("--api-key", default=os.environ.get("WMATA_API_KEY"))
    args = parser.parse_args()

    if not args.simulate and not args.api_key:
        sys.exit("Set WMATA_API_KEY or pass --api-key (not needed with --simulate + canned data, "
                  "but this script always polls live, so it's required either way).")

    topology = json.load(open(args.topology))
    chain_order = json.load(open(args.chain_order))
    layout = LayoutIndex(topology, chain_order)

    if args.simulate:
        renderer = SimulateRenderer(layout)
    else:
        try:
            renderer = HardwareRenderer(layout.num_leds, args.gpio_pin, args.brightness)
        except ImportError:
            sys.exit("rpi_ws281x not installed / not on a Pi. Use --simulate to test without hardware.")

    index = CircuitIndex(topology)
    last_known: dict = {}
    state: list = []
    last_poll = 0.0
    cycle_tick = 0

    print(f"Driving {layout.num_leds} LEDs ({len(layout.station_to_index)} stations + "
          f"{len(layout.segment_to_index)} midpoints). Polling WMATA every {args.interval}s, "
          f"rendering every {args.cycle_interval}s. Ctrl+C to stop.", file=sys.stderr)
    try:
        while True:
            now = time.time()
            if now - last_poll >= args.interval:
                trains = get_live_trains(args.api_key)
                state = build_state(trains, index, last_known)
                last_poll = now

            frame = compute_frame(state, layout, cycle_tick)
            renderer.render(frame)
            cycle_tick += 1
            time.sleep(args.cycle_interval)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()