#!/bin/bash

PI="pi@pi.local"
DEST="/home/pi/wmata-led"

echo "Watching WMATA files..."

fswatch -o \
  chain_order.json \
  topology.json \
  train_poller.py \
  verify_layout.py \
  led_display.py |
while read; do
    echo "Syncing to Pi..."
    rsync -av \
      chain_order.json \
      topology.json \
      train_poller.py \
      led_display.py \
      verify_layout.py \
      "$PI:$DEST"
done
