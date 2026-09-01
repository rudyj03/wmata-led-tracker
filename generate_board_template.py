#!/usr/bin/env python3
"""
generate_board_template.py

Generate a station-only, print-at-actual-size drilling template for a
Raspberry Pi / addressable-LED WMATA Metrorail map.

The default layout is derived from the official WMATA system-map station
geometry rather than raw latitude/longitude. A small anchored declutter pass
makes the official schematic practical for 12 mm physical LED drill holes.

Outputs:
  1. board_template.svg   -- physical-size drilling/layout template
  2. chain_order.json     -- LED index -> physical station mapping
  3. station_legend.txt   -- human-readable index -> station lookup

This generator is intentionally station-only: one LED per physical station.
The live display code can still represent trains between stations by snapping
them to the nearer station.

Typical use:
    python3 generate_board_template.py \
        --topology topology.json \
        --width-mm 609.6 --height-mm 457.2 \
        --led-diameter-mm 12 --max-wire-span-mm 101.6 --label-mode index

For comparison with raw geography, use:
    --layout geographic
"""

import argparse
import json
import math
from collections import defaultdict


LINE_COLORS = {
    "RD": "#e51636",
    "OR": "#ed8b00",
    "YL": "#ffd100",
    "GR": "#00b140",
    "BL": "#009cde",
    "SV": "#a1a3a6",
}


# ---------------------------------------------------------------------------
# Official WMATA map geometry
# ---------------------------------------------------------------------------
# Station-center coordinates extracted from the official WMATA system map
# supplied with this project. Coordinates are source-image pixels and are
# uniformly scaled to the requested board size.
#
# Because 12 mm physical LED holes are much larger (relative to the map) than
# the printed station symbols, official_positions() applies a small anchored
# declutter pass. This preserves the recognizable WMATA geometry while
# guaranteeing enough acrylic remains between neighboring holes.

OFFICIAL_MAP_PIXELS = {
    "A02": (813.5, 895.5),
    "A03": (792.0, 863.0),
    "A04": (765.0, 836.0),
    "A05": (738.5, 809.0),
    "A06": (716.0, 786.5),
    "A07": (682.0, 781.0),
    "A08": (656.0, 763.5),
    "A09": (619.0, 726.0),
    "A10": (582.0, 689.0),
    "A11": (545.0, 652.0),
    "A12": (507.0, 614.0),
    "A13": (469.0, 576.0),
    "A14": (432.0, 539.0),
    "A15": (394.0, 501.0),
    "B02": (1052.0, 1012.5),
    "B03": (1120.5, 983.0),
    "B04": (1120.5, 896.0),
    "B05": (1120.5, 852.0),
    "B07": (937.5, 650.5),
    "B08": (922.0, 552.5),
    "B09": (922.0, 511.0),
    "B10": (922.0, 469.0),
    "B11": (922.0, 428.0),
    "B35": (1120.5, 939.5),
    "C01": (885.5, 1012.0),
    "C02": (845.0, 944.0),
    "C03": (774.0, 944.0),
    "C04": (734.5, 944.0),
    "C05": (607.0, 1015.0),
    "C06": (693.0, 1207.0),
    "C07": (765.5, 1307.0),
    "C08": (764.5, 1373.5),
    "C09": (794.0, 1429.0),
    "C10": (848.0, 1461.0),
    "C11": (848.0, 1493.0),
    "C12": (848.0, 1523.0),
    "C13": (849.0, 1565.0),
    "C14": (849.0, 1621.0),
    "C15": (861.0, 1682.0),
    "D01": (885.5, 1064.0),
    "D02": (885.5, 1108.0),
    "D04": (1043.0, 1145.0),
    "D05": (1099.0, 1145.0),
    "D06": (1130.0, 1144.0),
    "D07": (1174.0, 1114.0),
    "D08": (1229.0, 1096.0),
    "D09": (1321.0, 1059.5),
    "D10": (1351.0, 1029.5),
    "D11": (1381.5, 999.0),
    "D12": (1412.0, 968.5),
    "D13": (1442.0, 938.5),
    "E01": (987.0, 960.0),
    "E02": (999.0, 907.0),
    "E03": (947.5, 851.0),
    "E04": (921.0, 816.0),
    "E05": (948.0, 789.0),
    "E06": (1037.0, 756.5),
    "E07": (1098.5, 699.5),
    "E08": (1130.5, 668.5),
    "E09": (1161.5, 637.5),
    "E10": (1192.0, 607.0),
    "F01": (987.0, 1012.0),
    "F02": (986.5, 1064.5),
    "F03": (987.0, 1145.0),
    "F04": (1040.5, 1281.0),
    "F05": (1080.5, 1281.0),
    "F06": (1153.5, 1308.5),
    "F07": (1178.5, 1333.5),
    "F08": (1216.0, 1355.5),
    "F09": (1266.5, 1347.5),
    "F10": (1297.5, 1378.5),
    "F11": (1328.5, 1409.5),
    "G01": (1267.0, 1108.5),
    "G02": (1360.0, 1108.5),
    "G03": (1408.0, 1108.5),
    "G04": (1476.0, 1108.5),
    "G05": (1522.5, 1108.5),
    "J02": (646.5, 1589.0),
    "J03": (571.0, 1682.0),
    "K01": (554.0, 1068.0),
    "K02": (518.0, 1068.0),
    "K03": (482.0, 1068.0),
    "K04": (446.0, 1068.0),
    "K05": (399.0, 1068.0),
    "K06": (335.5, 1056.0),
    "K07": (286.5, 1056.0),
    "K08": (237.5, 1056.0),
    "N01": (337.0, 1027.0),
    "N02": (312.0, 1002.0),
    "N03": (287.0, 977.0),
    "N04": (262.5, 952.0),
    "N06": (237.5, 927.0),
    "N07": (212.0, 901.5),
    "N08": (187.0, 877.5),
    "N09": (162.5, 852.5),
    "N10": (135.0, 824.5),
    "N11": (110.5, 800.5),
    "N12": (88.5, 778.5),
}

# ---------------------------------------------------------------------------
# Positioning helpers
# ---------------------------------------------------------------------------
def geographic_positions(stations: dict, width_mm: float, height_mm: float, margin_mm: float):
    """Old behavior: direct linear projection of station lat/lon."""
    lats = [s["lat"] for s in stations.values()]
    lons = [s["lon"] for s in stations.values()]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    usable_w = width_mm - 2 * margin_mm
    usable_h = height_mm - 2 * margin_mm

    positions = {}
    for code, s in stations.items():
        x = margin_mm + ((s["lon"] - lon_min) / (lon_max - lon_min)) * usable_w
        y = margin_mm + ((lat_max - s["lat"]) / (lat_max - lat_min)) * usable_h
        positions[code] = (x, y)
    return positions


def scale_grid_to_board(grid: dict, width_mm: float, height_mm: float, margin_mm: float) -> dict:
    """Uniformly scale/center arbitrary grid coordinates onto the board.

    Uniform scaling preserves the schematic's angles instead of stretching it
    differently in X and Y.
    """
    xs = [p[0] for p in grid.values()]
    ys = [p[1] for p in grid.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max_x - min_x
    span_y = max_y - min_y

    usable_w = width_mm - 2 * margin_mm
    usable_h = height_mm - 2 * margin_mm
    scale = min(usable_w / span_x, usable_h / span_y)

    drawn_w = span_x * scale
    drawn_h = span_y * scale
    left = (width_mm - drawn_w) / 2
    top = (height_mm - drawn_h) / 2

    return {
        code: (left + (x - min_x) * scale, top + (y - min_y) * scale)
        for code, (x, y) in grid.items()
    }


def _anchored_declutter(positions: dict, width_mm: float, height_mm: float,
                         margin_mm: float, min_dist_mm: float,
                         iterations: int = 4000, anchor_strength: float = 0.007) -> dict:
    """Separate too-close drill centers while staying close to official geometry."""
    base = {k: [float(v[0]), float(v[1])] for k, v in positions.items()}
    pos = {k: v[:] for k, v in base.items()}
    keys = list(pos)

    for _ in range(iterations):
        disp = {k: [0.0, 0.0] for k in keys}
        worst = 0.0

        for i, a in enumerate(keys):
            ax, ay = pos[a]
            for b in keys[i + 1:]:
                bx, by = pos[b]
                dx, dy = bx - ax, by - ay
                d = math.hypot(dx, dy)
                if d >= min_dist_mm:
                    continue
                worst = max(worst, min_dist_mm - d)
                if d < 1e-9:
                    dx, dy, d = 1.0, 0.0, 1.0
                ux, uy = dx / d, dy / d
                push = (min_dist_mm - d) * 0.275
                disp[a][0] -= ux * push
                disp[a][1] -= uy * push
                disp[b][0] += ux * push
                disp[b][1] += uy * push

        for k in keys:
            disp[k][0] += (base[k][0] - pos[k][0]) * anchor_strength
            disp[k][1] += (base[k][1] - pos[k][1]) * anchor_strength

        for k in keys:
            pos[k][0] = min(width_mm - margin_mm, max(margin_mm, pos[k][0] + disp[k][0]))
            pos[k][1] = min(height_mm - margin_mm, max(margin_mm, pos[k][1] + disp[k][1]))

        if worst < 0.01:
            break

    return {k: tuple(v) for k, v in pos.items()}


def official_positions(stations: dict, width_mm: float, height_mm: float,
                       margin_mm: float, led_diameter_mm: float,
                       min_spacing_mm: float | None = None):
    """Scale official WMATA station centers to the board, then minimally declutter."""
    station_codes = set(stations)
    known_codes = set(OFFICIAL_MAP_PIXELS)
    missing = sorted(station_codes - known_codes)
    if missing:
        raise SystemExit(
            "Official-map layout is missing station code(s): " + ", ".join(missing)
        )

    source = {k: OFFICIAL_MAP_PIXELS[k] for k in stations}
    scaled = scale_grid_to_board(source, width_mm, height_mm, margin_mm)
    min_dist = min_spacing_mm if min_spacing_mm is not None else led_diameter_mm * 1.3
    return _anchored_declutter(
        scaled, width_mm, height_mm, margin_mm,
        min_dist_mm=min_dist + 1.0,  # 1mm convergence/safety allowance
    )


def find_collisions(positions: dict, min_dist: float) -> list:
    keys = list(positions)
    collisions = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            ax, ay = positions[a]
            bx, by = positions[b]
            d = math.hypot(bx - ax, by - ay)
            if d < min_dist:
                collisions.append((a, b, d))
    return sorted(collisions, key=lambda t: t[2])


# ---------------------------------------------------------------------------
# Wiring order
# ---------------------------------------------------------------------------
def path_length(order: list, positions: dict) -> float:
    total = 0.0
    for a, b in zip(order, order[1:]):
        ax, ay = positions[a]
        bx, by = positions[b]
        total += math.hypot(bx - ax, by - ay)
    return total


def greedy_chain_order(positions: dict) -> list:
    """Nearest-neighbor wiring path, starting at the westernmost station."""
    remaining = set(positions)
    start = min(remaining, key=lambda c: (positions[c][0], positions[c][1], c))
    order = [start]
    remaining.remove(start)

    while remaining:
        cx, cy = positions[order[-1]]
        nxt = min(
            remaining,
            key=lambda c: (
                (positions[c][0] - cx) ** 2 + (positions[c][1] - cy) ** 2,
                positions[c][0], positions[c][1], c,
            ),
        )
        order.append(nxt)
        remaining.remove(nxt)
    return order


def _route_score(order: list, positions: dict):
    """Lexicographic route score: minimize worst hop first, then total wire length."""
    lengths = []
    for a, b in zip(order, order[1:]):
        ax, ay = positions[a]
        bx, by = positions[b]
        lengths.append(math.hypot(bx - ax, by - ay))
    return (max(lengths) if lengths else 0.0, sum(lengths))


def improve_chain_order_2opt(order: list, positions: dict, passes: int = 12) -> list:
    """2-opt cleanup aimed at real pixel-wire constraints.

    The primary objective is to minimize the single longest hop between
    consecutive pixels.  Total backside wire length is the secondary
    objective.  This is more useful for pre-wired bullet pixels than merely
    minimizing total route length, because one over-length hop can make an
    otherwise good chain impossible to mount.
    """
    order = list(order)
    n = len(order)
    current_score = _route_score(order, positions)

    for _ in range(passes):
        best_score = current_score
        best_order = None
        for i in range(n - 1):
            for j in range(i + 1, n):
                if i == 0 and j == n - 1:
                    continue
                candidate = order[:i] + list(reversed(order[i:j + 1])) + order[j + 1:]
                candidate_score = _route_score(candidate, positions)
                if candidate_score < best_score:
                    best_score = candidate_score
                    best_order = candidate

        if best_order is None:
            break
        order = best_order
        current_score = best_score

    return order


def wiring_hops(order: list, positions: dict):
    hops = []
    for i, (a, b) in enumerate(zip(order, order[1:])):
        ax, ay = positions[a]
        bx, by = positions[b]
        hops.append((i, a, b, math.hypot(bx - ax, by - ay)))
    return sorted(hops, key=lambda h: h[3], reverse=True)


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------
def build_svg(topology: dict, positions: dict, chain_order: list,
              width_mm: float, height_mm: float, led_d_mm: float,
              label_mode: str, line_width_mm: float, show_wiring: bool) -> str:
    chain_index = {code: i for i, code in enumerate(chain_order)}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" height="{height_mm}mm" '
        f'viewBox="0 0 {width_mm} {height_mm}">',
        f'<rect width="{width_mm}" height="{height_mm}" fill="white"/>',
    ]

    # Colored route guides. Shared trunks naturally draw on top of one another;
    # use slightly reduced opacity so all route geometry remains visible on the
    # drilling/layout proof.
    for line, info in topology["lines"].items():
        pts = [positions[c] for c in info["physical_station_order"] if c in positions]
        if len(pts) < 2:
            continue
        path_d = " ".join(
            f"{'M' if i == 0 else 'L'}{x:.2f},{y:.2f}" for i, (x, y) in enumerate(pts)
        )
        parts.append(
            f'<path d="{path_d}" stroke="{LINE_COLORS.get(line, "#999")}" '
            f'stroke-width="{line_width_mm:.2f}" stroke-linecap="round" '
            f'stroke-linejoin="round" fill="none" opacity="0.68"/>'
        )

    if show_wiring:
        pts = [positions[c] for c in chain_order]
        path_d = " ".join(
            f"{'M' if i == 0 else 'L'}{x:.2f},{y:.2f}" for i, (x, y) in enumerate(pts)
        )
        parts.append(
            f'<path d="{path_d}" stroke="#222" stroke-width="0.35" '
            f'stroke-dasharray="2,2" fill="none" opacity="0.45"/>'
        )

    r = led_d_mm / 2
    # Draw by chain index so nearby overlapping annotations are deterministic.
    for code in chain_order:
        x, y = positions[code]
        idx = chain_index[code]
        name = topology["physical_stations"][code]["name"]
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" '
            f'fill="white" fill-opacity="0.82" stroke="black" stroke-width="0.28"/>'
        )
        parts.append(
            f'<line x1="{x-r-1:.2f}" y1="{y:.2f}" x2="{x+r+1:.2f}" y2="{y:.2f}" '
            f'stroke="black" stroke-width="0.10"/>'
        )
        parts.append(
            f'<line x1="{x:.2f}" y1="{y-r-1:.2f}" x2="{x:.2f}" y2="{y+r+1:.2f}" '
            f'stroke="black" stroke-width="0.10"/>'
        )
        if label_mode == "index":
            parts.append(
                f'<text x="{x:.2f}" y="{y-r-1.5:.2f}" font-size="2.5" '
                f'font-family="monospace" text-anchor="middle" font-weight="bold">{idx}</text>'
            )
        elif label_mode == "name":
            safe = (name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            parts.append(
                f'<text x="{x+r+1.5:.2f}" y="{y-1:.2f}" font-size="2.2" '
                f'font-family="sans-serif">#{idx} {safe}</text>'
            )

    parts.append("</svg>")
    return "\n".join(parts)


def write_legend(path: str, chain_entries: list):
    with open(path, "w") as f:
        f.write(f"{'#':>4}  {'CODE':6}  NAME\n")
        f.write("-" * 72 + "\n")
        for entry in chain_entries:
            f.write(f"{entry['index']:>4}  {entry['physical_station']:6}  {entry['name']}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", default="topology.json")
    parser.add_argument("--layout", choices=["official", "geographic"], default="official",
                        help="Board geometry. Default: official WMATA-derived schematic.")
    parser.add_argument("--width-mm", type=float, default=609.6, help="Board width in mm (default 24in)")
    parser.add_argument("--height-mm", type=float, default=457.2, help="Board height in mm (default 18in)")
    parser.add_argument("--margin-mm", type=float, default=20.0)
    parser.add_argument("--led-diameter-mm", type=float, default=12.0,
                        help="Diameter of the printed drill circle (default 12mm for this build)")
    parser.add_argument("--max-wire-span-mm", type=float, default=101.6,
                        help="Maximum comfortable center-to-center hop between consecutive pixels (default 101.6mm / 4in)")
    parser.add_argument("--min-spacing-mm", type=float, default=None,
                        help="Minimum acceptable station center spacing. Default: 1.3x LED diameter")
    parser.add_argument("--label-mode", choices=["index", "name", "none"], default="index")
    parser.add_argument("--line-width-mm", type=float, default=1.0,
                        help="Colored route-guide width in the SVG")
    parser.add_argument("--show-wiring", action="store_true",
                        help="Overlay the backside LED-chain route as a dashed line for inspection")
    parser.add_argument("--out-svg", default="board_template.svg")
    parser.add_argument("--out-json", default="chain_order.json")
    parser.add_argument("--out-legend", default="station_legend.txt")

    # Backward-compatible flags from the old generator. The new generator is
    # station-only by design, so --no-midpoints is accepted but no longer needed.
    parser.add_argument("--no-midpoints", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-declutter", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    with open(args.topology) as f:
        topology = json.load(f)
    stations = topology["physical_stations"]

    min_spacing = args.min_spacing_mm if args.min_spacing_mm is not None else args.led_diameter_mm * 1.3

    if args.layout == "official":
        positions = official_positions(
            stations, args.width_mm, args.height_mm, args.margin_mm,
            args.led_diameter_mm, min_spacing,
        )
    else:
        positions = geographic_positions(stations, args.width_mm, args.height_mm, args.margin_mm)
    collisions = find_collisions(positions, min_spacing)

    greedy = greedy_chain_order(positions)
    chain_order = improve_chain_order_2opt(greedy, positions)

    svg = build_svg(
        topology, positions, chain_order,
        args.width_mm, args.height_mm, args.led_diameter_mm,
        args.label_mode, args.line_width_mm, args.show_wiring,
    )
    with open(args.out_svg, "w") as f:
        f.write(svg)

    chain_entries = [
        {
            "index": i,
            "type": "station",
            "physical_station": code,
            "name": stations[code]["name"],
        }
        for i, code in enumerate(chain_order)
    ]
    chain_data = {
        "board_width_mm": args.width_mm,
        "board_height_mm": args.height_mm,
        "layout": args.layout,
        "geometry_source": "Official WMATA system-map station centers; minimally decluttered for 12mm drill holes" if args.layout == "official" else "station latitude/longitude",
        "station_count": len(chain_entries),
        "chain_order": chain_entries,
    }
    with open(args.out_json, "w") as f:
        json.dump(chain_data, f, indent=2)

    write_legend(args.out_legend, chain_entries)

    hops = wiring_hops(chain_order, positions)
    total = path_length(chain_order, positions)

    print(f"Wrote {args.out_svg}: {len(positions)} station LEDs, {args.layout} layout, "
          f"board {args.width_mm}x{args.height_mm}mm")
    print(f"Wrote {args.out_json}: station-only wiring order, indices 0..{len(chain_order)-1}")
    print(f"Wrote {args.out_legend}")
    print(f"Station spacing check: {len(collisions)} pair(s) under {min_spacing:.1f}mm")
    if collisions:
        for a, b, d in collisions[:12]:
            print(f"  {stations[a]['name']} <-> {stations[b]['name']}: {d:.1f}mm")
        if len(collisions) > 12:
            print(f"  ...and {len(collisions)-12} more")

    print(f"Backside wiring route: {total:.0f}mm total across {len(chain_order)-1} hops")
    if hops:
        print("Longest wiring hops:")
        for _, a, b, d in hops[:8]:
            print(f"  {stations[a]['name']} -> {stations[b]['name']}: {d:.1f}mm")

    print("\nPrint the SVG at 100% / actual size, never 'fit to page'.")
    if hops:
        longest = hops[0][3]
        if longest <= args.max_wire_span_mm:
            print(f"Wire-span check: PASS — longest hop {longest:.1f}mm <= {args.max_wire_span_mm:.1f}mm limit")
        else:
            print(f"Wire-span check: FAIL — longest hop {longest:.1f}mm > {args.max_wire_span_mm:.1f}mm limit")

    print("Drill-circle diameter is set by --led-diameter-mm; verify print scaling with a ruler before drilling.")


if __name__ == "__main__":
    main()
