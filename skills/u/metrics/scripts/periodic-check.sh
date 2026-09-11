#!/usr/bin/env bash
set -euo pipefail

DAYS="${1:-3}"
AGENT_DIR="${PI_CODING_AGENT_DIR:-/mnt/d/Program Files/piagent/.pi/agent}"
BASELINE="$AGENT_DIR/metrics-baseline.json"

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
