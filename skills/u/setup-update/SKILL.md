---
name: setup-update
description: "Manage pi setup repos — review upstream changes by module, merge selectively, test locally, then push to origin. Use when user says setup-update, 检查更新, 推送更新, sync setup."
---

# Setup Update

Review upstream changes → select modules → merge → test → push to origin.

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

Remotes: `origin` = user's personal repo, `upstream` = aqua2k1 original.

---

## Step 1: Pull Origin + Fetch Upstream

```bash
cd {PI_SETUP}
BRANCH=$(git rev-parse --abbrev-ref HEAD) && git pull origin $BRANCH || echo "⚠ pi-setup pull 失败"

cd {AGENT_SETUP}
BRANCH=$(git rev-parse --abbrev-ref HEAD) && git pull origin $BRANCH || echo "⚠ agent-setup pull 失败"
```

```bash
cd {PI_SETUP} && git fetch upstream 2>/dev/null || echo "⚠ pi-setup upstream 不可达"
cd {AGENT_SETUP} && git fetch upstream 2>/dev/null || echo "⚠ agent-setup upstream 不可达"
```

---

## Step 2: Show Upstream Changes by Module

For each repo, show what upstream has that origin doesn't, grouped by module.

```bash
cd {PI_SETUP}
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "=== pi-setup ==="
echo "本地: $(git rev-parse --short HEAD)  origin: $(git rev-parse --short origin/$BRANCH)  upstream: $(git rev-parse --short upstream/$BRANCH)"
echo ""
UPSTREAM_COMMITS=$(git log --oneline origin/$BRANCH..upstream/$BRANCH 2>/dev/null)
if [ -z "$UPSTREAM_COMMITS" ]; then
  echo "✅ 已是最新，无上游更新"
else
  echo "--- 上游新提交 ---"
  echo "$UPSTREAM_COMMITS"
  echo ""
  echo "--- 按模块分组变更 ---"
  git diff --name-status origin/$BRANCH..upstream/$BRANCH | while read status file; do
    echo "$status  $file"
  done
fi
```

```bash
cd {AGENT_SETUP}
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo ""
echo "=== agent-setup ==="
echo "本地: $(git rev-parse --short HEAD)  origin: $(git rev-parse --short origin/$BRANCH)  upstream: $(git rev-parse --short upstream/$BRANCH)"
echo ""
UPSTREAM_COMMITS=$(git log --oneline origin/$BRANCH..upstream/$BRANCH 2>/dev/null)
if [ -z "$UPSTREAM_COMMITS" ]; then
  echo "✅ 已是最新，无上游更新"
else
  echo "--- 上游新提交 ---"
  echo "$UPSTREAM_COMMITS"
  echo ""
  echo "--- 按模块分组变更 ---"
  git diff --name-status origin/$BRANCH..upstream/$BRANCH | while read status file; do
    echo "$status  $file"
  done
fi
```

---

## Step 3: Group and Report — STOP HERE

**CRITICAL: Do NOT proceed without user confirmation.**

Parse the `git diff --name-status` output into module groups. Group by top-level directory or logical unit.

**Path prefix note:** pi-setup diff paths include `agent/` prefix (e.g. `agent/extensions/foo.ts`).
When grouping, use the full diff path as the `{selected_path}` for Step 4 checkout — do NOT strip the `agent/` prefix.

| Diff path pattern | Module label |
|-------------------|-------------|
| `agent/skills/` or `skills/` | Skills — group by individual skill dir |
| `agent/extensions/` or `extensions/` | Extensions — group by individual extension dir |
| `agent/agents/` or `agents/` | Agents — group by individual agent file |
| `settings.json`, `pi-websearch.json`, `auth.json`, `trust.json`, etc. | ⚠️ 配置文件（需手动合并，不可直接覆盖） |
| Other | Other — list individually |

For each module, show:
- Whether it's new (`A`), modified (`M`), or deleted (`D`)
- Brief description (for SKILL.md, extract `description` from frontmatter)

**Multiple-choice options:**

```
A) 全部合并 (不含配置文件)
B) agent/extensions/foo/ — <description>
C) skills/bar/ — <description>
... (one option per module, using full diff path)
⚠️  配置文件单独处理 — 每项手动确认是否合并
```

> 💡 多选用逗号分隔，如 `B,D`。选 `A` 则忽略其他。

If neither repo has upstream changes → "已是最新" and STOP.

---

## Step 4: Merge Selected Modules

For each selected module in each repo, merge from upstream.

**CRITICAL: Handle by diff status, NOT uniform `git checkout`:**

| Status | Meaning | Command |
|--------|---------|---------|
| `A` | New in upstream | `git checkout upstream/$BRANCH -- {path}` |
| `M` | Modified in upstream | `git checkout upstream/$BRANCH -- {path}` |
| `D` | Deleted in upstream | `git rm -- {path}` |

```bash
cd {repo}
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# For {status, path} pairs:
case "{status}" in
  D)
    git rm -- "{path}" && echo "✅ merged (deleted): {path}" || { echo "❌ merge failed: {path}" >&2; exit 1; }
    ;;
  *)
    git checkout upstream/$BRANCH -- "{path}" && echo "✅ merged: {path}" || { echo "❌ merge failed: {path}" >&2; exit 1; }
    ;;
esac
```

After all checkouts, verify:

```bash
cd {repo}
git status --short
echo "---"
echo "以上为本次合并引入的变更，确认无误后继续。"
```

**Protected config files** — if user approved a config file merge:
- Show diff first: `git diff upstream/$BRANCH -- settings.json`
- Ask again to confirm before overwriting
- After checkout, note: "⚠️ 请手动检查并合并你的本地配置"

---

## Step 5: Sync to Runtime

After all selected modules are merged, sync to runtime.

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
PROTECTED="settings.json pi-websearch.json auth.json trust.json models-store.json sessions bin git npm skills searxng-instances"

shopt -s nullglob

for item in "$SRC"/*; do
  name=$(basename "$item")

  if [ -z "$name" ] || [ "$name" = "*" ]; then
    echo "⚠ 跳过异常条目: $item" >&2
    continue
  fi

  if echo " $PROTECTED " | grep -q " $name "; then
    echo "⏭️ 跳过受保护: $name"
  else
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
set -euo pipefail
SRC="{AGENT_SETUP}/skills"
DST="{RUNTIME}/skills"

if [ ! -d "$SRC" ]; then
  echo "❌ 源目录不存在: $SRC — 终止同步" >&2
  exit 1
fi

rm -rf "$DST"
cp -r "$SRC" "$DST" && echo "✅ 同步 skills"
```

---

## Step 6: Test — STOP HERE

**CRITICAL: Do NOT commit or push yet.**

Tell user:

```
✅ 已合并并同步到运行时。请手动测试以下模块是否正常工作：
  - <list merged modules>

测试通过后回复 "OK" 或 "没问题"，我将生成提交信息并推送到 origin。
测试不通过回复 "回滚"，我将撤销所有改动。
```

Wait for user confirmation.

---

## Step 7: Commit and Push

After user confirms tests pass, auto-generate commit message and push.

**Generate commit message:**

Format: `merge: upstream updates ({module_list})`

Where `{module_list}` is a comma-separated summary of merged modules, e.g.:
- `merge: upstream updates (skills: setup-update, grill-me)`
- `merge: upstream updates (extensions: my-extension, agents: my-agent)`
- `merge: upstream updates (skills: foo, extensions: bar)`

```bash
cd {repo}
git add {selected_paths}
git commit -m "{generated_message}" || { echo "❌ 提交失败"; exit 1; }
```

```bash
cd {repo}
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin $BRANCH || { echo "❌ 推送失败，检查网络或权限"; exit 1; }
```

---

## Step 8: Verify and Report

```bash
cd {PI_SETUP} && echo "pi-setup: $(git rev-parse --short HEAD) (origin: $(git ls-remote origin $(git rev-parse --abbrev-ref HEAD) | cut -c1-7))"
cd {AGENT_SETUP} && echo "agent-setup: $(git rev-parse --short HEAD) (origin: $(git ls-remote origin $(git rev-parse --abbrev-ref HEAD) | cut -c1-7))"
```

**Summary:**

| Item | Action |
|------|--------|
| Modules merged | list |
| Pushed to origin | commit hash |
| Protected (skipped) | list |

Tell user to restart pi if runtime was synced.

---

## Rollback

If user says "回滚" at any point before pushing:

```bash
cd {repo}
git reset --hard HEAD
git clean -fd
echo "✅ 已回滚到: $(git rev-parse --short HEAD)"
```

**After rollback, re-sync runtime from repos** (reverse Step 5) to undo the runtime sync:

- Re-run Step 5 (Sync to Runtime) to restore runtime to match the rolled-back repos.
