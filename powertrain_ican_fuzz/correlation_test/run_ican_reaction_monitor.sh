#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${ICAN_MONITOR_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"

cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" -m powertrain_ican_fuzz.correlation_test.monitor "$@"
