#!/usr/bin/env bash
# 周期自检：基线距今是否超过阈值天数
# 用法: periodic-check.sh [天数,默认3]
# 输出: stale:N天  (超过阈值)  或  fresh:N天 / fresh:no-baseline
THRESH="${1:-3}"
BASELINE=$(python3 - << 'PY'
import os
c=[os.path.expanduser("~/.pi/agent/metrics-baseline.json")]
if os.environ.get("PI_CODING_AGENT_DIR"): c.append(os.path.join(os.environ["PI_CODING_AGENT_DIR"],"metrics-baseline.json"))
c.append("/mnt/d/Program Files/piagent/.pi/agent/metrics-baseline.json")
for x in c:
    if x and os.path.isfile(x): print(x); break
PY
)
if [ -z "$BASELINE" ]; then echo "fresh:no-baseline"; exit 0; fi
now=$(date +%s); mtime=$(stat -c %Y "$BASELINE")
age_days=$(( (now - mtime) / 86400 ))
if [ "$age_days" -ge "$THRESH" ]; then
  echo "stale:${age_days}days"; exit 1
else
  echo "fresh:${age_days}days"; exit 0
fi
