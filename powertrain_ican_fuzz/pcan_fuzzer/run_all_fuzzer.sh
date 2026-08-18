#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="$PROJECT_ROOT/powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh"

CHANNEL="can0"
ROUNDS=10
INTERVAL_MS=17
PROGRESS_EVERY=50
MANIFEST_DIR="tx_logs"
LIVE=0

usage() {
    cat <<'EOF'
Usage: ./powertrain_ican_fuzz/pcan_fuzzer/run_all_fuzzer.sh [options]

Runs Motor_18 extended, Motor_07, and Motor_26 sequentially.
Default mode is dry-run. Add --live for actual CAN transmission.

Options:
  --channel NAME          SocketCAN channel (default: can0)
  --rounds N              Rounds per message (default: 10)
  --interval-ms MS        Live inter-frame interval (default: 17)
  --progress-every N      Progress output interval (default: 50)
  --manifest-dir PATH     Manifest directory (default: tx_logs)
  --live                  Actually transmit
  -h, --help              Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --channel) CHANNEL="$2"; shift 2 ;;
        --rounds) ROUNDS="$2"; shift 2 ;;
        --interval-ms) INTERVAL_MS="$2"; shift 2 ;;
        --progress-every) PROGRESS_EVERY="$2"; shift 2 ;;
        --manifest-dir) MANIFEST_DIR="$2"; shift 2 ;;
        --live) LIVE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

STAMP="$(date +%Y%m%d_%H%M%S_%N)"
mkdir -p "$MANIFEST_DIR"

if [[ "$LIVE" -eq 1 ]]; then
    MODE_ARGS=(--live)
    EFFECTIVE_INTERVAL="$INTERVAL_MS"
    echo "[pcan-suite] LIVE: 3 messages, rounds=$ROUNDS, interval=${INTERVAL_MS}ms"
else
    MODE_ARGS=()
    EFFECTIVE_INTERVAL=0
    echo "[pcan-suite] DRY-RUN: no CAN frame will be sent"
fi

run_message() {
    local message="$1"
    shift
    "$RUNNER" \
        --channel "$CHANNEL" \
        --message "$message" \
        --rounds "$ROUNDS" \
        --interval-ms "$EFFECTIVE_INTERVAL" \
        --progress-every "$PROGRESS_EVERY" \
        --manifest "$MANIFEST_DIR/${message}_tx_${STAMP}.jsonl" \
        "$@" \
        "${MODE_ARGS[@]}"
}

run_message motor18 --profile extended
run_message motor07
run_message motor26

echo "[pcan-suite] completed: manifests=$MANIFEST_DIR/*_tx_${STAMP}.jsonl"
