#!/usr/bin/env bash
# pi runtime cleanup — dry-run by default; pass --apply to delete old sessions and
# truncate the crash log.
#
# Usage: cleanup.sh [--age N] [--apply]
#
# Age comes from the ISO timestamp inside the session file name, not from mtime:
# copying or migrating sessions resets mtime, so an mtime filter would never expire
# migrated history. Files whose names have no timestamp fall back to mtime.
set -euo pipefail

AGE=30
APPLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --age) AGE="${2:-}"; shift 2;;
    --apply) APPLY=1; shift;;
    -h|--help) sed -n '2,7p' "${BASH_SOURCE[0]}"; exit 0;;
    *) echo "Unknown argument: $1" >&2; exit 2;;
  esac
done

if ! [[ "$AGE" =~ ^[0-9]+$ ]]; then
  echo "❌ --age needs a whole number of days (got: $AGE)" >&2
  exit 2
fi

# Resolve the sessions directory (same candidate order as metrics).
SESSION_DIR=$(python3 - << 'PY'
import os
c=[os.environ.get("PI_SESSIONS"),
   os.path.join(os.environ["PI_CODING_AGENT_DIR"], "sessions") if os.environ.get("PI_CODING_AGENT_DIR") else None,
   os.path.expanduser("~/pi/agent/sessions"),
   os.path.expanduser("~/.pi/agent/sessions")]
for x in c:
    if x and os.path.isdir(x):
        print(x); break
else:
    print(os.path.expanduser("~/pi/agent/sessions"))
PY
)

# Crash log: the active agent directory wins, matching the sessions order above.
CRASH_LOG=$(python3 - << 'PY'
import os
c=[]
if os.environ.get("PI_CODING_AGENT_DIR"):
    c.append(os.path.join(os.environ["PI_CODING_AGENT_DIR"], "pi-crash.log"))
c.append(os.path.expanduser("~/pi/agent/pi-crash.log"))
c.append(os.path.expanduser("~/.pi/agent/pi-crash.log"))
for x in c:
    if x and os.path.isfile(x):
        print(x); break
PY
)

echo "sessions dir: $SESSION_DIR"
echo "age threshold: ${AGE} days (by file-name timestamp)"
echo "mode: $([ "$APPLY" -eq 1 ] && echo 'APPLY (delete)' || echo 'dry-run (list only)')"
[ -n "$CRASH_LOG" ] && echo "crash log: $CRASH_LOG"

# Selection runs in Python: name-based timestamps, full-depth scan, and an explicit
# newest-file guard that covers `<project>/<session>/tasks/*.jsonl` too.
PLAN=$(python3 - "$SESSION_DIR" "$AGE" << 'PY'
import datetime, pathlib, re, sys

root, age_days = pathlib.Path(sys.argv[1]), float(sys.argv[2])
now = datetime.datetime.now(datetime.timezone.utc)
stamp = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})")

def captured_at(path):
    m = stamp.match(path.name)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S").replace(
                tzinfo=datetime.timezone.utc
            )
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)

entries = []
for path in root.rglob("*.jsonl"):
    try:
        entries.append((path, captured_at(path)))
    except OSError:
        continue

if not entries:
    print("NEWEST")
    raise SystemExit(0)

entries.sort(key=lambda pair: pair[1])
newest = entries[-1][0]
print(f"NEWEST\t{newest}")

for path, when in entries:
    age = (now - when).total_seconds() / 86400
    if age > age_days:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        print(f"OLD\t{size}\t{age:.1f}\t{path}")
PY
)

NEWEST=$(printf '%s\n' "$PLAN" | awk -F'\t' '$1=="NEWEST"{print $2}')

echo
if ! printf '%s\n' "$PLAN" | grep -q '^OLD'; then
  echo "✅ No session files older than ${AGE} days"
  echo
  echo "(dry-run) Nothing to delete."
  exit 0
fi

echo "--- Sessions older than ${AGE} days (largest first) ---"
printf '%s\n' "$PLAN" | awk -F'\t' '$1=="OLD"{printf "%10.1f MB  %6.1f d  %s\n", $2/1048576, $3, $4}' | sort -rn
TOTAL=$(printf '%s\n' "$PLAN" | awk -F'\t' '$1=="OLD"{t+=$2}END{printf "%.1f", t/1048576}')
COUNT=$(printf '%s\n' "$PLAN" | grep -c '^OLD')
echo "--- ${COUNT} files, ${TOTAL} MB ---"
[ -n "$NEWEST" ] && echo "protected newest session: $NEWEST"

if [ "$APPLY" -eq 1 ]; then
  echo
  echo "⚠️  Deleting..."
  while IFS=$'\t' read -r tag _size _age path; do
    [ "$tag" = "OLD" ] || continue
    if [ "$path" = "$NEWEST" ]; then
      echo "⏭️  Skipping newest session: $path"
      continue
    fi
    rm -f "$path" && echo "  🗑️  deleted: $path"
  done <<< "$PLAN"
  if [ -n "$CRASH_LOG" ]; then
    : > "$CRASH_LOG" && echo "  🗑️  crash log truncated"
  fi
  # Sessions leave empty project/session directories behind.
  find "$SESSION_DIR" -mindepth 1 -type d -empty -delete 2>/dev/null || true
  echo "✅ Cleanup done"
else
  echo
  echo "(dry-run) When it looks right, run: cleanup.sh --age $AGE --apply"
fi
