import json
import time
from rpi_ws281x import PixelStrip, Color

LED_PIN = 18
LED_BRIGHTNESS = 128

with open("chain_order.json") as f:
    layout = json.load(f)

chain = layout["chain_order"]
LED_COUNT = len(chain)

strip = PixelStrip(LED_COUNT, LED_PIN, brightness=LED_BRIGHTNESS)
strip.begin()


def all_off():
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()


try:
    all_off()

    for i, station in enumerate(chain):
        # White avoids our R/G color-order issue.
        strip.setPixelColor(i, Color(255, 255, 255))
        strip.show()

        print(f"LED {i:02d} -> {station}", flush=True)

        input("Press ENTER for next station...")

        strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()

finally:
    all_off()