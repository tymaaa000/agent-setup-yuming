---
name: setup-update
description: "Manage pi setup repos — pull upstream updates or push local changes to forks. Use when user says setup-update, 检查更新, 推送更新, sync setup. Two modes — local (pull upstream to sync runtime) and origin (push local to fork)."
---

# Setup Update

Two modes:
- `local` — pull upstream updates, sync to runtime
- `origin` — push local changes to GitHub forks

**If user does not specify mode, ask: "选模式: local 还是 origin？" and wait for answer.**

## Path Resolution

> Note: `{VAR}` below are substitution placeholders — replace with actual paths before running.

This skill file is at `{PI_HOME}/.pi/agent/skills/u/setup-update/SKILL.md`.
Derive `PI_HOME` by going up 5 levels from this file's directory:
`skills/u/setup-update/` → `skills/u/` → `skills/` → `.pi/agent/` → `.pi/` → `PI_HOME`

**⚠️ Before any destructive operation (rm, cp -r), verify each path starts with the expected prefix (e.g. `D:\Program Files\piagent\.pi\agent`) to prevent catastrophic misconfiguration.**

| Variable | Value |
|----------|-------|
| `PI_HOME` | derived from skill location (5 levels up from SKILL.md) |
| `PI_SETUP` | `{PI_HOME}/pi-setup` |
| `AGENT_SETUP` | `{PI_HOME}/agent-setup` |
| `RUNTIME` | `{PI_HOME}/.pi/agent` |

Remotes per repo: `origin` = user's fork, `upstream` = aqua2k1 original.

---

## MODE: local

Pull upstream updates → sync to runtime.

### Step L1: Pull Fork First

For each repo, detect branch and pull:

```bash
cd {PI_SETUP}
BRANCH=$(git rev-parse --abbrev-ref HEAD) && git pull origin $BRANCH || echo "⚠ pi-setup pull 失败"

cd {AGENT_SETUP}
BRANCH=$(git rev-parse --abbrev-ref HEAD) && git pull origin $BRANCH || echo "⚠ agent-setup pull 失败"
```

### Step L2: Fetch and Compare

```bash
cd {PI_SETUP} && git fetch upstream 2>/dev/null || echo "⚠ pi-setup upstream 不可达"
cd {AGENT_SETUP} && git fetch upstream 2>/dev/null || echo "⚠ agent-setup upstream 不可达"
```

For each repo, run separately (BRANCH may differ):

```bash
cd {PI_SETUP}
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "pi-setup: 本地=$(git rev-parse --short HEAD) fork=$(git rev-parse --short origin/$BRANCH) 上游=$(git rev-parse --short upstream/$BRANCH 2>/dev/null || echo N/A)"
echo "新提交:" && git log --oneline origin/$BRANCH..upstream/$BRANCH 2>/dev/null || echo "(无)"

cd {AGENT_SETUP}
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "agent-setup: 本地=$(git rev-parse --short HEAD) fork=$(git rev-parse --short origin/$BRANCH) 上游=$(git rev-parse --short upstream/$BRANCH 2>/dev/null || echo N/A)"
echo "新提交:" && git log --oneline origin/$BRANCH..upstream/$BRANCH 2>/dev/null || echo "(无)"
```

### Step L3: Report — STOP HERE

**CRITICAL: Do NOT proceed without user confirmation.**

Show which repos have upstream updates, every new commit, and changed files (+/-).

**Q1: 是否合并上游更新？**

Dynamic:
- Both → `A) 全部合并  B) 仅 pi-setup  C) 仅 agent-setup  D) 都不合并`
- One repo → `A) 合并  B) 不合并`
- Neither → "已是最新" and STOP

**Q2: 合并后是否同步到运行时？**

```
2. 合并后是否同步到运行时？
   A) 是
   B) 否
```

> 💡 空格分隔回答，如 `A A`。跳过用 `-`。

Parse: split by spaces, map by position. If more/less answers than questions, ask to retry.

### Step L4: Merge Upstream

For each approved repo:

```bash
cd {repo_path}
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge upstream/$BRANCH || { echo "❌ 合并冲突，请手动解决后重新运行"; exit 1; }
```

### Step L5: Sync to Runtime

Sync files from repos to `{RUNTIME}`.

**pi-setup sync — copy all except protected:**

```bash
set -euo pipefail
SRC="{PI_SETUP}/agent"
DST="{RUNTIME}"

# Guard: SRC must exist
if [ ! -d "$SRC" ]; then
  echo "❌ 源目录不存在: $SRC — 终止同步" >&2
  exit 1
fi

# Protected items — NEVER overwrite or delete in DST.
# - Files: user configs that must not be overwritten by upstream
# - Dirs: runtime data that would be LOST if overwritten or deleted
#   (git/ and npm/ exist in BOTH SRC and DST, but SRC has only .gitignore;
#    DST has cloned repos and installed packages — overwriting = destruction)
PROTECTED="settings.json pi-websearch.json auth.json trust.json models-store.json sessions bin git npm searxng-instances"

shopt -s nullglob  # prevent "$SRC/*" from becoming literal "*" if SRC is empty

for item in "$SRC"/*; do
  name=$(basename "$item")

  # Safety: reject empty or glob-literal names (must never happen with nullglob, but guard anyway)
  if [ -z "$name" ] || [ "$name" = "*" ]; then
    echo "⚠ 跳过异常条目: $item" >&2
    continue
  fi

  # Exact match against space-delimited PROTECTED list (NOT grep -w — that would falsely match "searxng" inside "searxng-instances")
  if echo " $PROTECTED " | grep -q " $name "; then
    echo "⏭️ 跳过受保护: $name"
  else
    # Safety: reject names that could escape DST
    case "$name" in .|..|*/*) echo "⚠ 拒绝危险路径: $name" >&2; continue ;; esac
    rm -rf "$DST/$name" 2>/dev/null
    cp -r "$item" "$DST/$name" && echo "✅ 同步: $name"
  fi
done

# ⛔ NEVER add a "cleanup" loop here (remove DST items not in SRC).
# RUNTIME contains auto-generated dirs (sessions/, bin/, git/, npm/, searxng-instances/)
# that DO NOT exist in pi-setup/agent/. Deleting them CORRUPTS the running pi session.
```

**agent-setup sync:**

```bash
rm -rf "{RUNTIME}/skills"
cp -r "{AGENT_SETUP}/skills" "{RUNTIME}/skills" && echo "✅ 同步 skills"
```

**settings.json comparison:**

Compare `{PI_SETUP}/agent/settings.json` (new) vs `{RUNTIME}/settings.json` (current).
If they differ, show the diff and ask: "上游 settings.json 有变化，是否合并？A) 合并  B) 跳过"

### Step L6: Verify

```bash
echo "=== Git 状态 ==="
cd {PI_SETUP} && echo "pi-setup: $(git rev-parse --short HEAD)"
cd {AGENT_SETUP} && echo "agent-setup: $(git rev-parse --short HEAD)"
echo "=== 运行时目录 ==="
echo "extensions: $(ls {RUNTIME}/extensions/ 2>/dev/null | wc -l) 个文件"
echo "agents:     $(ls {RUNTIME}/agents/ 2>/dev/null | wc -l) 个文件"
echo "skills/u:   $(ls {RUNTIME}/skills/u/ 2>/dev/null | wc -l) 个目录"
echo "=== 受保护项完整性检查 ==="
for f in settings.json pi-websearch.json auth.json; do
  [ -f "{RUNTIME}/$f" ] && echo "✅ $f" || echo "❌ $f 缺失"
done
for d in sessions bin git npm; do
  [ -d "{RUNTIME}/$d" ] && echo "✅ $d/" || echo "❌ $d/ 缺失(危险!)"
done
echo "=== git repos ==="
ls {RUNTIME}/git/github.com/ 2>/dev/null || echo "(无)"
```

### Step L7: Report

Summarize merged/synced/skipped. Tell user to restart pi.

---

## MODE: origin

Push local changes to GitHub forks.

### Step O1: Check Local Changes

```bash
cd {PI_SETUP}
echo "=== pi-setup ==="
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git status --short || echo "❌ git status 失败"
echo "--- 未推送提交 ---"
UNPUSHED=$(git log --oneline origin/$BRANCH..HEAD 2>/dev/null)
if [ -n "$UNPUSHED" ]; then
  echo "$UNPUSHED"
  echo "(以上提交已在本地但未推送到 fork)"
fi

cd {AGENT_SETUP}
echo "=== agent-setup ==="
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git status --short || echo "❌ git status 失败"
echo "--- 未推送提交 ---"
UNPUSHED=$(git log --oneline origin/$BRANCH..HEAD 2>/dev/null)
if [ -n "$UNPUSHED" ]; then
  echo "$UNPUSHED"
  echo "(以上提交已在本地但未推送到 fork)"
fi
```

### Step O2: Report — STOP HERE

**CRITICAL: Do NOT proceed without user confirmation.**

**Q1: 上传哪些文件？**

List EVERY changed file with function summary:
- SKILL.md → extract `description` from frontmatter
- Other files → extract first comment/header line as summary
- Format: `B) [repo] file/path — 功能描述`
- >10 files → fold into groups like `B) [repo] dir/ (3 files) — 目录说明`
- First option always `A) 全部`

Zero changes → "无改动" and STOP.

**Q2: 提交信息用什么？**

```
2. 提交信息用什么？
   A) [自动生成: feat(xxx): xxx]
   B) 自定义
```

回答即确认提交+推送。

> 💡 多选用逗号分隔（如 `B,C`），题间用空格（如 `B,C A`）。跳过用 `-`。

Parse: split by spaces. Q1 split by comma → file selection. Q2 single letter. If count ≠ 2, ask to retry.

### Step O3: Stage and Commit

```bash
cd {repo}
git add {user-selected files}
git commit -m "{message}" || { echo "❌ 提交失败"; exit 1; }
```

### Step O4: Push

```bash
cd {repo}
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin $BRANCH || { echo "❌ 推送失败，检查网络或权限"; exit 1; }
```

### Step O5: Verify

```bash
cd {repo}
BRANCH=$(git rev-parse --abbrev-ref HEAD)
LOCAL=$(git rev-parse --short HEAD)
REMOTE=$(git ls-remote origin $BRANCH | cut -c1-7)
[ "$LOCAL" = "$REMOTE" ] && echo "✅ 推送成功 $LOCAL" || echo "⚠ 本地 $LOCAL ≠ 远程 $REMOTE"
```

### Step O6: Report

Summarize what was pushed. Remind: to contribute to upstream, open a Pull Request on GitHub.
