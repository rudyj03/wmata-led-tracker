from rpi_ws281x import PixelStrip, Color
import time

LED_COUNT = 50
LED_PIN = 18
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 32
LED_INVERT = False
LED_CHANNEL = 0

RED   = Color(0, 255, 0)
GREEN = Color(255, 0, 0)
BLUE  = Color(0, 0, 255)
OFF   = Color(0, 0, 0)

strip = PixelStrip(
    LED_COUNT,
    LED_PIN,
    LED_FREQ_HZ,
    LED_DMA,
    LED_INVERT,
    LED_BRIGHTNESS,
    LED_CHANNEL
)

strip.begin()

def clear():
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()

clear()

while True:
    for i in range(LED_COUNT):
        clear()

        strip.setPixelColor(i, GREEN)
        strip.show()

        print(f"LED {i + 1} of {LED_COUNT}")
        time.sleep(0.15)
