#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="$PROJECT_ROOT/powertrain_ican_fuzz/ican_monitor/run_monitor.sh"

CHANNEL="can0"
DURATION=120
OUTPUT_DIR="rx_logs"

usage() {
    cat <<'EOF'
Usage: ./powertrain_ican_fuzz/ican_monitor/run_all_monitor.sh [options]

Passively monitors Motor_18 (0x670), Motor_07 (0x640), and Motor_26 (0x3C7)
at the same time and writes one JSONL file per CAN ID.

Options:
  --channel NAME       SocketCAN channel (default: can0)
  --duration SECONDS   Capture duration (default: 120)
  --output-dir PATH    Output directory (default: rx_logs)
  -h, --help           Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --channel) CHANNEL="$2"; shift 2 ;;
        --duration) DURATION="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

STAMP="$(date +%Y%m%d_%H%M%S_%N)"
mkdir -p "$OUTPUT_DIR"
PIDS=()

cleanup() {
    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup INT TERM EXIT

for message in motor18 motor07 motor26; do
    "$RUNNER" \
        --channel "$CHANNEL" \
        --message "$message" \
        --duration "$DURATION" \
        --output "$OUTPUT_DIR/${message}_ican_${STAMP}.jsonl" &
    PIDS+=("$!")
done

STATUS=0
for pid in "${PIDS[@]}"; do
    wait "$pid" || STATUS=$?
done
trap - INT TERM EXIT

echo "[ican-suite] completed: outputs=$OUTPUT_DIR/*_ican_${STAMP}.jsonl"
exit "$STATUS"
