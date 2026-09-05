#!/usr/bin/env bash
# pi runtime 清理 — 默认 dry-run；加 --apply 才真正删除旧会话 + 截断崩溃日志。
# 用法: cleanup.sh [--age N] [--apply]
set -euo pipefail

AGE=30
APPLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --age) AGE="$2"; shift 2;;
    --apply) APPLY=1; shift;;
    *) echo "未知参数: $1"; exit 1;;
  esac
done

# 解析 sessions 目录（与 metrics 相同的候选逻辑）
SESSION_DIR=$(python3 - << 'PY'
import os
c=[os.environ.get("PI_SESSIONS"), os.path.expanduser("~/.pi/agent/sessions")]
if os.environ.get("PI_CODING_AGENT_DIR"): c.append(os.path.join(os.environ["PI_CODING_AGENT_DIR"],"sessions"))
c+=["/mnt/d/Program Files/piagent/.pi/agent/sessions"]
for x in c:
    if x and os.path.isdir(x):
        print(x); break
else:
    print(os.path.expanduser("~/.pi/agent/sessions"))
PY
)

echo "sessions 目录: $SESSION_DIR"
echo "年龄阈值: ${AGE} 天"
echo "模式: $([ $APPLY -eq 1 ] && echo 'APPLY(删) ' || echo 'dry-run(只列出)')"
echo

OLD_FILES=$(find "$SESSION_DIR" -name '*.jsonl' -type f -mtime +"$AGE" 2>/dev/null)
TOTAL_SIZE=0
if [ -z "$OLD_FILES" ]; then
  echo "✅ 没有超过 ${AGE} 天的会话文件"
else
  echo "--- 将处理以下会话（按大小）---"
  while IFS= read -r f; do
    sz=$(du -k "$f" | cut -f1)
    TOTAL_SIZE=$((TOTAL_SIZE+sz))
    printf "  %8.1f MB  %s\n" "$(echo "scale=1;$sz/1024"|bc)" "$f"
  done <<< "$OLD_FILES"
  echo "--- 共 ${TOTAL_SIZE} KB ---"
fi

# 崩溃日志
CRASH_LOG=$(python3 - << 'PY'
import os
c=[os.path.expanduser("~/.pi/agent/pi-crash.log")]
if os.environ.get("PI_CODING_AGENT_DIR"): c.append(os.path.join(os.environ["PI_CODING_AGENT_DIR"],"pi-crash.log"))
c+=["/mnt/d/Program Files/piagent/.pi/agent/pi-crash.log"]
for x in c:
    if x and os.path.isfile(x): print(x); break
PY
)
if [ -n "$CRASH_LOG" ]; then
  echo "崩溃日志: $CRASH_LOG ($(du -h "$CRASH_LOG"|cut -f1))"
fi

if [ $APPLY -eq 1 ]; then
  echo
  echo "⚠️  执行删除..."
  if [ -n "$OLD_FILES" ]; then
    # 保底：不删最近一个会话（保护当前活动会话）
    NEWEST=$(ls -t "$SESSION_DIR"/*/*.jsonl 2>/dev/null | head -1)
    while IFS= read -r f; do
      [ "$f" = "$NEWEST" ] && { echo "⏭️ 跳过最新会话: $f"; continue; }
      rm -f "$f" && echo "  🗑️ 删除: $f"
    done <<< "$OLD_FILES"
  fi
  if [ -n "$CRASH_LOG" ]; then : > "$CRASH_LOG" && echo "  🗑️ 已截断崩溃日志"; fi
  echo "✅ 清理完成"
else
  echo
  echo "（dry-run）确认无误后运行: cleanup.sh --age $AGE --apply"
fi
