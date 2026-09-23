#!/usr/bin/env bash
# periodic-check.sh — report how old the metrics baseline is.
# Usage: periodic-check.sh [days]   (default 3)
# Prints "fresh:Ndays", "stale:Ndays", or "no-baseline".
set -euo pipefail

DAYS="${1:-3}"
AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/pi/agent}"
BASELINE="$AGENT_DIR/metrics-baseline.json"

# Keep the vector index tidy: pi-memory re-chunks changed files after every write and orphans
# the previous chunks, so an untouched index makes verify-pi.sh report "orphaned embedding
# chunks". Fire and forget so this check stays fast and its output contract unchanged.
if command -v qmd >/dev/null 2>&1; then
  ( qmd cleanup >/dev/null 2>&1 & ) || true
fi

if [[ ! -f "$BASELINE" ]]; then
  echo "no-baseline"
  exit 0
fi

python3 - "$BASELINE" "$DAYS" <<'PY'
import datetime
import json
import sys

path, days = sys.argv[1], int(sys.argv[2])
try:
    data = json.load(open(path, encoding="utf-8"))
    stamp = data.get("capturedAt")
    captured = datetime.datetime.fromisoformat(stamp)
except (OSError, ValueError, TypeError, KeyError):
    print("no-baseline")
    raise SystemExit(0)

now = datetime.datetime.now(captured.tzinfo)
age = (now - captured).total_seconds() / 86400
if age >= days:
    print(f"stale:{age:.1f}days")
else:
    print(f"fresh:{age:.1f}days")
PY
