# WMATA LED Metro Map

A physical LED board that mirrors the DC Metro system in real time. Each station (and, optionally, the track segment between adjacent stations) gets one addressable LED. LEDs light up with their line's color, dim when idle and bright when a train is present, driven by WMATA's live TrainPositions API.

Runs on a Raspberry Pi driving a WS2812B/SK6812 LED chain.

## How it fits together

```
topology_builder.py  -->  topology.json
        |                      |
        v                      v
generate_board_template.py --> chain_order.json, board_template.svg, station_legend.txt
        |
        v
train_poller.py  (polls WMATA, maps trains onto topology.json)
        |
        v
led_display.py   (renders live train state onto the physical LED chain)
```

- **[topology_builder.py](topology_builder.py)** — one-time (or occasional) build step. Calls the WMATA `Rail.svc` and `TrainPositions` APIs to fetch every station and the physical, end-to-end circuit order for each line, then writes it all to `topology.json`. Also collapses interchange stations (e.g. Metro Center, Gallery Place) into a single "physical station" so the board gets one LED per physical location, not one per line-specific code. Only needs to be re-run when WMATA changes the system (new station, new line segment).
- **[generate_board_template.py](generate_board_template.py)** — reads `topology.json` and lays out station positions based on the official WMATA system map geometry, applying a small declutter pass so 12mm LED holes don't collide on the board. Outputs `board_template.svg` (a print-at-actual-size drilling template), `chain_order.json` (LED index → physical station/midpoint mapping — the wiring order for your LED chain), and `station_legend.txt` (human-readable index lookup).
- **[train_poller.py](train_poller.py)** — polls WMATA's live `TrainPositions` feed and resolves each train's raw circuit ID into a station-relative position (`at station X` or `between X and Y, N% of the way`), using `topology.json`'s circuit-level data. If a train's circuit briefly can't be resolved (pocket track, crossover near a terminus), it holds the train's last known position instead of dropping it.
- **[led_display.py](led_display.py)** — the main entry point. Combines `chain_order.json` (LED wiring order) with live state from `train_poller.py` to compute an RGB frame per LED and render it, either to the terminal (`--simulate`) or to real hardware via `rpi_ws281x`.
- **[server.py](server.py)** — optional standalone web visualizer. Polls WMATA in a background thread and serves a small map UI (`static/`) plus `/api/state` and `/api/topology` JSON endpoints. Useful for testing/demoing without any hardware at all.

## Setup

### 1. Get a WMATA API key

Free at [developer.wmata.com](https://developer.wmata.com). Export it as an environment variable:

```bash
export WMATA_API_KEY=your_key_here
```

### 2. Install dependencies

`topology_builder.py` and `train_poller.py` use only the standard library. `led_display.py` needs `rpi_ws281x` to drive real hardware (Pi only):

```bash
pip install -r requirements.txt   # rpi_ws281x, for hardware mode
```

### 3. Build the topology (once, or whenever WMATA's system changes)

```bash
python3 topology_builder.py --out topology.json
```

### 4. Generate the board template and wiring order

```bash
python3 generate_board_template.py \
    --topology topology.json \
    --width-mm 609.6 --height-mm 457.2 \
    --led-diameter-mm 12 --max-wire-span-mm 101.6 --label-mode index
```

This produces `board_template.svg` (print at 100% scale as your drilling guide — see `parts-list.txt` for the physical build), `chain_order.json`, and `station_legend.txt`.

### 5. Wire up the hardware

See [parts-list.txt](parts-list.txt) for the full BOM: Raspberry Pi, WS2812B/SK6812 LEDs (one per physical station, ~98 total), a 74AHCT125 level shifter to step the Pi's 3.3V GPIO up to 5V, and a 5V supply sized to your LED count.

## Running it

**Test the mapping/blending logic with no hardware:**

```bash
python3 led_display.py --topology topology.json --chain-order chain_order.json --simulate
```

**On the Pi, with the level shifter wired up** (LED hardware access needs root):

```bash
sudo --preserve-env=WMATA_API_KEY ~/wmata-led-env/bin/python3 \
    led_display.py \
    --topology topology.json \
    --chain-order chain_order.json \
    --brightness 32
```

`--preserve-env=WMATA_API_KEY` is required because `sudo` normally strips your shell environment, and `led_display.py` reads the API key from `WMATA_API_KEY`.

Other useful flags: `--interval` (seconds between WMATA polls, default 12), `--cycle-interval` (seconds between render ticks, default 1.5 — controls how fast a station serving multiple active lines cycles between colors), `--gpio-pin` (default 18).

**Terminal-only train view (no LED mapping, just raw poller output):**

```bash
python3 train_poller.py --topology topology.json
```

**Web visualizer (no hardware required):**

```bash
python3 server.py --topology topology.json --port 8765
```

Then open `http://localhost:8765`.

## Syncing to the Pi

[sync-pi.sh](sync-pi.sh) watches `chain_order.json`, `topology.json`, and `led_display.py` for changes and rsyncs them to the Pi over SSH whenever they're saved (requires `fswatch`). Edit the `PI` and `DEST` variables at the top of the script to match your Pi's hostname and target directory.

```bash
./sync-pi.sh
```

## Repo layout

| File | Purpose |
|---|---|
| `topology_builder.py` | Builds `topology.json` from the WMATA API |
| `generate_board_template.py` | Builds the drilling template + `chain_order.json` |
| `train_poller.py` | Polls WMATA, resolves live train positions |
| `led_display.py` | Renders live state to the LED chain (or terminal) |
| `server.py` | Web visualizer + JSON API |
| `test_led.py` | Quick standalone LED chain sanity check (chases one LED at a time) |
| `topology.json` | Generated: full station/circuit topology |
| `chain_order.json` | Generated: LED index → station/midpoint wiring order |
| `board_template.svg` / `*_preview.png` | Generated: physical drilling template |
| `station_legend.txt` | Generated: human-readable LED index lookup |
| `parts-list.txt` | Hardware BOM |
| `sync-pi.sh` | Watch-and-rsync deploy helper for the Pi |
