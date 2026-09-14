#!/usr/bin/env bash
# pi runtime cleanup — dry-run by default; pass --apply to delete old sessions
# and truncate the crash log.
# Usage: cleanup.sh [--age N] [--apply]
set -euo pipefail

AGE=30
APPLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --age) AGE="$2"; shift 2;;
    --apply) APPLY=1; shift;;
    *) echo "Unknown argument: $1"; exit 1;;
  esac
done

# Resolve the sessions directory (same candidate order as metrics)
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

echo "sessions dir: $SESSION_DIR"
echo "age threshold: ${AGE} days"
echo "mode: $([ $APPLY -eq 1 ] && echo 'APPLY (delete)' || echo 'dry-run (list only)')"
echo

OLD_FILES=$(find "$SESSION_DIR" -name '*.jsonl' -type f -mtime +"$AGE" 2>/dev/null)
TOTAL_SIZE=0
if [ -z "$OLD_FILES" ]; then
  echo "✅ No session files older than ${AGE} days"
else
  echo "--- Sessions to process (by size) ---"
  while IFS= read -r f; do
    sz=$(du -k "$f" | cut -f1)
    TOTAL_SIZE=$((TOTAL_SIZE+sz))
    printf "  %8.1f MB  %s\n" "$(echo "scale=1;$sz/1024"|bc)" "$f"
  done <<< "$OLD_FILES"
  echo "--- Total ${TOTAL_SIZE} KB ---"
fi

# Crash log
CRASH_LOG=$(python3 - << 'PY'
import os
c=[os.path.expanduser("~/pi/agent/pi-crash.log")]
if os.environ.get("PI_CODING_AGENT_DIR"): c.append(os.path.join(os.environ["PI_CODING_AGENT_DIR"],"pi-crash.log"))
c.append(os.path.expanduser("~/.pi/agent/pi-crash.log"))
for x in c:
    if x and os.path.isfile(x): print(x); break
PY
)
if [ -n "$CRASH_LOG" ]; then
  echo "crash log: $CRASH_LOG ($(du -h "$CRASH_LOG"|cut -f1))"
fi

if [ $APPLY -eq 1 ]; then
  echo
  echo "⚠️  Deleting..."
  if [ -n "$OLD_FILES" ]; then
    # Safety: never delete the newest session (protects the active one)
    NEWEST=$(ls -t "$SESSION_DIR"/*/*.jsonl 2>/dev/null | head -1)
    while IFS= read -r f; do
      [ "$f" = "$NEWEST" ] && { echo "⏭️ Skipping newest session: $f"; continue; }
      rm -f "$f" && echo "  🗑️ deleted: $f"
    done <<< "$OLD_FILES"
  fi
  if [ -n "$CRASH_LOG" ]; then : > "$CRASH_LOG" && echo "  🗑️ crash log truncated"; fi
  echo "✅ Cleanup done"
else
  echo
  echo "(dry-run) When it looks right, run: cleanup.sh --age $AGE --apply"
fi
