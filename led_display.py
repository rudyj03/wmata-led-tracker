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
  - chain_order.json has one LED per physical station. --mode picks how
    trains map onto them:
      stations  (default) -- only a station with a train at the platform
                lights up; trains between stations aren't shown.
      blink     -- a train on the last stretch before a station (past
                --blink-threshold of the way there) flashes its line color
                on/off at full brightness on that station. The dark phase
                is what sets it apart from a multi-line station, which
                swaps colors but never goes dark.
  - Idle nodes render dim in their line's color(s) so the map shape is
    always visible. A node with an active train renders bright. Nodes
    serving more than one active line CYCLE through each line's color
    in turn (rather than blending) -- clearer than a muddy averaged
    color, at the cost of needing a render tick that's faster than the
    WMATA poll interval (see --cycle-interval). In blink mode an
    approaching train takes its own turn in that cycle, flashing for its
    whole turn (see --blink-interval).

Usage:
    # test the mapping logic with no hardware at all:
    python3 led_display.py --topology topology.json --chain-order chain_order.json --simulate

    # once the level shifter is wired up, on the Pi:
    sudo python3 led_display.py --topology topology.json --chain-order chain_order.json

    # flash the next station as trains approach it:
    python3 led_display.py --simulate --mode blink
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


def scale(rgb, factor):
    return tuple(min(255, int(c * factor)) for c in rgb)


def blend(colors):
    """Average a list of RGB tuples."""
    n = len(colors)
    return tuple(sum(c[i] for c in colors) // n for i in range(3))


class LayoutIndex:
    """Maps physical stations to their chain index,
    built entirely from chain_order.json (the single source of truth for
    wiring order) plus topology.json for line-color lookups."""

    def __init__(self, topology: dict, chain_order: dict):
        self.station_to_index = {}
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

            colors = [IDLE_LINE_COLORS_RGB[ln] for ln in lines if ln in LINE_COLORS_RGB]
            self.idle_color[idx] = scale(blend(colors) if colors else (255, 255, 255), IDLE_BRIGHTNESS)


def compute_frame(state: list, layout: LayoutIndex, cycle_tick: int = 0, mode: str = "stations",
                  blink_on: bool = True, blink_threshold: float = 0.7) -> list:
    """Returns a list of (r,g,b) tuples, one per LED index, 0..num_leds-1.

    cycle_tick selects which line's color to show at a node currently
    serving more than one active line -- advance it on the --cycle-interval
    clock (not once per WMATA poll) to get a visible cycling animation
    rather than blended colors.

    mode is "stations" (only at-platform trains light up) or "blink"
    (trains past blink_threshold of the way to the next station also
    flash that station). blink_on is the current phase of that flash --
    toggle it on the --blink-interval clock."""
    frame = [(0, 0, 0)] * layout.num_leds

    active_by_index: dict = {}    # led index -> list of line colors currently present
    steady_by_index: dict = {}    # led index -> {line colors at the platform}
    blinking_by_index: dict = {}  # led index -> {line colors approaching (blink mode)}
    for t in state:
        p = t["position"]
        color = LINE_COLORS_RGB.get(t["line"])
        if color is None:
            continue

        if p["status"] == "at":
            station, blinking = p["station"], False
        elif p["status"] == "between" and mode == "blink" and p["fraction"] >= blink_threshold:
            station, blinking = p["to"], True
        else:
            continue

        idx = layout.station_to_index.get(station)
        if idx is None:
            continue
        active_by_index.setdefault(idx, []).append(color)
        if blinking:
            blinking_by_index.setdefault(idx, set()).add(color)
        else:
            steady_by_index.setdefault(idx, set()).add(color)

    for idx, colors in active_by_index.items():
        # dedupe consecutive-identical colors (e.g. two Red Line trains at
        # the same node) so the cycle doesn't pointlessly "blink" on the
        # same color -- only distinct line colors get cycled through
        distinct = list(dict.fromkeys(colors))
        chosen = distinct[cycle_tick % len(distinct)]
        # a line that's both at the platform and approaching shows steady
        flashing = chosen in blinking_by_index.get(idx, set()) - steady_by_index.get(idx, set())
        if flashing and not blink_on:
            continue
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
            #My bullet LED channels for some reason are g,r,b so this is intentional here
            self.strip.setPixelColor(idx, self.Color(g, r, b))
        self.strip.show()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", default="topology.json")
    parser.add_argument("--chain-order", default="chain_order.json")
    parser.add_argument("--interval", type=float, default=12.0, help="Seconds between WMATA polls")
    parser.add_argument("--cycle-interval", type=float, default=1.5,
                         help="Seconds each line's color is shown at nodes serving "
                              "multiple active lines")
    parser.add_argument("--blink-interval", type=float, default=0.3,
                         help="blink mode: seconds on, then seconds off, for approaching trains")
    parser.add_argument("--blink-threshold", type=float, default=0.7,
                         help="blink mode: fraction of the way to the next station after which "
                              "a train starts blinking (0 = whole trip, 0.7 = last 30%%)")
    parser.add_argument("--tick", type=float, default=0.1,
                         help="Seconds between frame updates -- keep below --blink-interval")
    parser.add_argument("--mode", choices=["stations", "blink"], default="stations",
                         help="stations: light only stations with a train at them. "
                              "blink: also flash the station a train is about to arrive at")
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
    state: list = []
    last_poll = 0.0
    last_frame = None

    print(f"Driving {layout.num_leds} LEDs ({len(layout.station_to_index)} stations, "
          f"{args.mode} mode). Polling WMATA every {args.interval}s, "
          f"cycling colors every {args.cycle_interval}s. Ctrl+C to stop.", file=sys.stderr)
    try:
        while True:
            now = time.time()
            if now - last_poll >= args.interval:
                try:
                    trains = get_live_trains(args.api_key)
                    state = build_state(trains, index)
                    last_poll = now
                except Exception as e:
                    print(f"WMATA poll failed: {e}", file=sys.stderr)
                    last_poll = now

            # color cycling and blinking run on their own clocks, so the
            # loop can tick fast enough for the blink without speeding up
            # the color cycle
            cycle_tick = int(now / args.cycle_interval)
            blink_on = int(now / args.blink_interval) % 2 == 0
            frame = compute_frame(state, layout, cycle_tick, mode=args.mode, blink_on=blink_on,
                                  blink_threshold=args.blink_threshold)
            if frame != last_frame:  # skip redundant redraws at the fast tick
                renderer.render(frame)
                last_frame = frame
            time.sleep(args.tick)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
