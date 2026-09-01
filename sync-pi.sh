#!/bin/bash

PI="pi@pi.local"
DEST="/home/pi/wmata-led-env"

echo "Watching WMATA files..."

fswatch -o \
  chain_order.json \
  topology.json \
  train_poller.py \
  led_display.py |
while read; do
    echo "Syncing to Pi..."
    rsync -av \
      chain_order.json \
      topology.json \
      led_display.py \
      led_display.py \
      "$PI:$DEST"
done
