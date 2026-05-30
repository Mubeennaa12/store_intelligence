#!/usr/bin/env bash
# pipeline/run.sh
# Processes all CCTV clips and feeds events to the API.
# Usage: ./run.sh [--api_url http://localhost:8000]
set -e

CLIPS_DIR="${CLIPS_DIR:-../data/clips}"
LAYOUT="${LAYOUT:-../data/store_layout.json}"
OUTPUT_DIR="${OUTPUT_DIR:-../data/events}"
API_URL="${1:-}"

mkdir -p "$OUTPUT_DIR"

echo "=== Apex Retail Detection Pipeline ==="
echo "Clips dir : $CLIPS_DIR"
echo "Layout    : $LAYOUT"
echo "Output    : $OUTPUT_DIR"
echo "API URL   : ${API_URL:-none (JSONL only)}"
echo ""

# Expected clip naming convention: STORE_BLR_002__CAM_ENTRY_01.mp4
for clip in "$CLIPS_DIR"/*.mp4; do
  filename=$(basename "$clip" .mp4)
  store_id=$(echo "$filename" | cut -d'_' -f1-3)
  camera_id=$(echo "$filename" | cut -d'_' -f4-6)
  output="$OUTPUT_DIR/${filename}_events.jsonl"

  echo "Processing: $filename"
  echo "  Store   : $store_id"
  echo "  Camera  : $camera_id"
  echo "  Output  : $output"

  python detect.py \
    --clip "$clip" \
    --store_id "$store_id" \
    --camera_id "$camera_id" \
    --layout "$LAYOUT" \
    --output "$output" \
    ${API_URL:+--api_url "$API_URL"}

  echo "  Done ✓"
done

echo ""
echo "=== All clips processed ==="
echo "Event files in: $OUTPUT_DIR"
