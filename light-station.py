import json
import time
from rpi_ws281x import PixelStrip, Color

LED_PIN = 18
BRIGHTNESS = 128

with open("chain_order.json") as f:
    chain = json.load(f)

targets = [
    "Franconia-Springfield",
    "Van Dorn Street",
]

strip = PixelStrip(len(chain["chain_order"]), LED_PIN, brightness=BRIGHTNESS)
strip.begin()

# Everything off
for i in range(len(chain["chain_order"])):
    strip.setPixelColor(i, Color(0, 0, 0))

# Find and light both stations BLUE
for entry in chain["chain_order"]:
    for target in targets:
        if target.lower() in entry["name"].lower():
            idx = entry["index"]
            print(f"{target} -> LED {idx}")

            # Confirmed R/G swap on our hardware.
            # RGB Blue = (0, 156, 222)
            strip.setPixelColor(idx, Color(156, 0, 222))

strip.show()

print("Franconia + Van Dorn should now be BLUE. Ctrl+C to turn off.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    for i in range(len(chain["chain_order"])):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()
    print("\nOff.")