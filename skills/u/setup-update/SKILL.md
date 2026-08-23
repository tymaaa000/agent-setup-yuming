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

## Step 0: Pre-Check — Clean Working Tree

**CRITICAL: Stop if working tree is dirty.** Merge can silently overwrite local changes.

```bash
cd "{PI_SETUP}"
if [ -n "$(git status --porcelain)" ]; then
  echo "❌ pi-setup 工作区不干净，请先提交或暂存本地修改:" >&2
  git status --short
  exit 1
fi

cd "{AGENT_SETUP}"
if [ -n "$(git status --porcelain)" ]; then
  echo "❌ agent-setup 工作区不干净，请先提交或暂存本地修改:" >&2
  git status --short
  exit 1
fi

echo "✅ 工作区干净"

# Record pre-merge HEAD for rollback
PI_SETUP_PRE_HEAD=$(cd "{PI_SETUP}" && git rev-parse HEAD)
AGENT_SETUP_PRE_HEAD=$(cd "{AGENT_SETUP}" && git rev-parse HEAD)
echo "PI_SETUP_PRE_HEAD=$PI_SETUP_PRE_HEAD"
echo "AGENT_SETUP_PRE_HEAD=$AGENT_SETUP_PRE_HEAD"
```

---

## Step 1: Pull Origin + Fetch Upstream

**Record pre-pull HEAD to detect what `git pull` actually brought in:**

```bash
cd "{PI_SETUP}"
PI_SETUP_PRE_PULL=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD) && git pull origin $BRANCH || echo "⚠ pi-setup pull 失败"
# Check for merge conflicts — abort if any
if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then
  echo "❌ pi-setup 存在合并冲突，请手动解决后重试:" >&2
  git diff --name-only --diff-filter=U
  exit 1
fi
PI_SETUP_POST_PULL=$(git rev-parse HEAD)

cd "{AGENT_SETUP}"
AGENT_SETUP_PRE_PULL=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD) && git pull origin $BRANCH || echo "⚠ agent-setup pull 失败"
if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then
  echo "❌ agent-setup 存在合并冲突，请手动解决后重试:" >&2
  git diff --name-only --diff-filter=U
  exit 1
fi
AGENT_SETUP_POST_PULL=$(git rev-parse HEAD)
```

```bash
cd "{PI_SETUP}" && git fetch upstream 2>/dev/null || echo "⚠ pi-setup upstream 不可达"
cd "{AGENT_SETUP}" && git fetch upstream 2>/dev/null || echo "⚠ agent-setup upstream 不可达"
```

---

## Step 2: Show Upstream Changes by Module

**GOAL: Report EVERY upstream change that has not yet been incorporated into origin — no false "已是最新" when upstream has moved ahead.**

### How not to miss changes

Use **merge-base** (not origin HEAD) as the baseline for the diff. This is the only way to
guarantee zero false-negatives, because:

- `origin/main..upstream/main` shows commits that upstream has but origin doesn't — correct when
  origin is strictly behind upstream.
- But if origin already merged some upstream commits AND has its own on top, this still works:
  the ".." operator excludes commits reachable from origin.
- The **real danger** is `git pull` fast-forwarding origin silently before we can diff. The
  pre-pull / post-pull recording in Step 1 guards against this. If pull changed HEAD, report
  those commits explicitly.

**Two comparisons needed:**

1. `origin/main..upstream/main` — upstream commits NOT yet in origin (the ones we need to merge)
2. `PI_SETUP_PRE_PULL..PI_SETUP_POST_PULL` — commits that `git pull` just brought in (to avoid
   missing them if pull fast-forwarded)

### pi-setup

```bash
cd "{PI_SETUP}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
MERGE_BASE=$(git merge-base origin/$BRANCH upstream/$BRANCH 2>/dev/null || echo "")

echo "=== pi-setup ==="
echo "本地 HEAD:    $(git rev-parse --short HEAD)"
echo "origin HEAD:  $(git rev-parse --short origin/$BRANCH)"
echo "upstream HEAD: $(git rev-parse --short upstream/$BRANCH 2>/dev/null || echo N/A)"
if [ -n "$MERGE_BASE" ]; then
  echo "merge-base:    $(git rev-parse --short $MERGE_BASE)"
fi
echo ""

# Report what pull just brought in (Step 1 recorded pre/post)
if [ "$PI_SETUP_PRE_PULL" != "$PI_SETUP_POST_PULL" ]; then
  echo "--- git pull 拉取的提交 ---"
  git log --oneline $PI_SETUP_PRE_PULL..$PI_SETUP_POST_PULL
  echo ""
fi

# Show what upstream has that origin doesn't
UPSTREAM_COMMITS=$(git log --oneline origin/$BRANCH..upstream/$BRANCH 2>/dev/null)
if [ -z "$UPSTREAM_COMMITS" ]; then
  echo "✅ pi-setup: origin 包含所有上游提交（无新提交）"

  # EVEN when origin..upstream has no commits, origin and upstream may differ
  # at file level if origin has its own commits on top and missed merges
  # (e.g. D-status deletions). Always run a bidirectional diff to catch this.
  FILE_DIFF=$(git diff --name-status origin/$BRANCH upstream/$BRANCH 2>/dev/null)
  if [ -n "$FILE_DIFF" ]; then
    echo ""
    echo "--- ⚠️ origin 与 upstream 文件级差异（origin 有自己提交在上游之上） ---"
    echo "$FILE_DIFF"
    echo ""
    echo "   解读：以下文件在 origin 和 upstream 之间不同。"
    echo "   D = upstream 已删除但你本地保留 | M = 双方都有但内容不同 | A = 你本地有但上游没有"
  else
    echo "   （文件内容也完全一致）"
  fi
else
  echo "--- 📋 上游新提交（未合并到 origin） ---"
  echo "$UPSTREAM_COMMITS"
  echo ""
  echo "--- 📁 文件级变更（upstream 相对于 origin 的提交差异） ---"
  git diff --name-status origin/$BRANCH..upstream/$BRANCH 2>/dev/null | while read status file; do
    echo "$status  $file"
  done
fi
```

### agent-setup

```bash
cd "{AGENT_SETUP}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
MERGE_BASE=$(git merge-base origin/$BRANCH upstream/$BRANCH 2>/dev/null || echo "")

echo ""
echo "=== agent-setup ==="
echo "本地 HEAD:    $(git rev-parse --short HEAD)"
echo "origin HEAD:  $(git rev-parse --short origin/$BRANCH)"
echo "upstream HEAD: $(git rev-parse --short upstream/$BRANCH 2>/dev/null || echo N/A)"
if [ -n "$MERGE_BASE" ]; then
  echo "merge-base:    $(git rev-parse --short $MERGE_BASE)"
fi
echo ""

# Report what pull just brought in
if [ "$AGENT_SETUP_PRE_PULL" != "$AGENT_SETUP_POST_PULL" ]; then
  echo "--- git pull 拉取的提交 ---"
  git log --oneline $AGENT_SETUP_PRE_PULL..$AGENT_SETUP_POST_PULL
  echo ""
fi

UPSTREAM_COMMITS=$(git log --oneline origin/$BRANCH..upstream/$BRANCH 2>/dev/null)
if [ -z "$UPSTREAM_COMMITS" ]; then
  echo "✅ agent-setup: origin 包含所有上游提交（无新提交）"

  # Same fallback as pi-setup: catch file-level drift when origin has its own commits.
  FILE_DIFF=$(git diff --name-status origin/$BRANCH upstream/$BRANCH 2>/dev/null)
  if [ -n "$FILE_DIFF" ]; then
    echo ""
    echo "--- ⚠️ origin 与 upstream 文件级差异（origin 有自己提交在上游之上） ---"
    echo "$FILE_DIFF"
    echo ""
    echo "   解读：以下文件在 origin 和 upstream 之间不同。"
    echo "   D = upstream 已删除但你本地保留 | M = 双方都有但内容不同 | A = 你本地有但上游没有"
  else
    echo "   （文件内容也完全一致）"
  fi
else
  echo "--- 📋 上游新提交（未合并到 origin） ---"
  echo "$UPSTREAM_COMMITS"
  echo ""
  echo "--- 📁 文件级变更（upstream 相对于 origin 的提交差异） ---"
  git diff --name-status origin/$BRANCH..upstream/$BRANCH 2>/dev/null | while read status file; do
    echo "$status  $file"
  done
fi
```

### Integrity check (per repo)

After both diffs, the LLM should interpret the Step 2 output to determine integrity.
Do NOT run a separate bash script — use the values already printed by the Step 2 scripts.

**How to interpret Step 2 output:**

| Step 2 output | Meaning | Action |
|---------------|---------|--------|
| "📋 上游新提交" block has entries | upstream has commits not in origin | Normal — proceed to Step 3 |
| "✅ 已是最新" for BOTH repos, no file diff | origin contains all upstream commits AND files are identical | ✅ STOP — truly nothing to merge |
| "✅ 已是最新" but file-level diff reported | origin has all upstream commits but files differ (e.g. D-status deletions from prior incomplete merge) | ⚠️ Report the file diff to user — these need to be merged (deletions, modifications) |
| "✅ 已是最新" but merge-base != upstream HEAD | Inconsistency — possible force-push or stale fetch | ⚠️ Alert user: "merge-base != upstream HEAD 但 diff 为空，upstream 可能被 force-push" |
| "git pull 拉取的提交" has entries but no upstream diff | origin had its own new commits (not from upstream) | Report to user — these are just origin's own changes, nothing to merge |
| upstream HEAD shows as "N/A" | fetch failed or upstream remote unreachable | ⚠️ Alert user: "upstream 不可达，请检查网络和 SSH 密钥" |
| merge-base cannot be computed | upstream branch ref missing | ⚠️ Alert user: "无法计算 merge-base，upstream 分支可能不存在" |

---

## Step 3: Group, Classify, and Report — STOP HERE

**CRITICAL: Do NOT proceed without user confirmation.**

### 3a: Classify all changed files

Parse the `git diff --name-status` output. Classify each file into two categories:

| 类别 | 包含 | 处理方式 |
|------|------|----------|
| **模块文件** | extensions/, agents/, prompts/, skills/, APPEND_SYSTEM.md, searxng.sh, other non-config | Step 4: `git checkout upstream` |
| **配置文件** | settings.json, pi-websearch.json, auth.json, trust.json, models-store.json, models.json, pi-lsp.json, subagent-model.json, pi-chrome-devtools.json | Step 4.5: 字段级合并 |

**Path prefix note:** pi-setup diff paths include `agent/` prefix (e.g. `agent/extensions/foo.ts`).
When grouping, use the full diff path as the `{selected_path}` for Step 4 checkout — do NOT strip the `agent/` prefix.

Group module files by top-level directory for individual selection.

### 3b: Config file field-level analysis

For each config file in the diff, run a field-level comparison:

**settings.json — extract and compare key fields:**

```bash
cd "{PI_SETUP}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

UPSTREAM_SETTINGS=$(git show upstream/$BRANCH:agent/settings.json 2>/dev/null)
LOCAL_SETTINGS=$(git show origin/$BRANCH:agent/settings.json 2>/dev/null)

echo "=== settings.json 字段级对比 ==="

python3 -c "
import json, sys
up = json.loads(sys.argv[1])
lo = json.loads(sys.argv[2])

# packages
up_pkgs = set(up.get('packages', []))
lo_pkgs = set(lo.get('packages', []))
new_pkgs = up_pkgs - lo_pkgs
removed_pkgs = lo_pkgs - up_pkgs
if new_pkgs: print('🔔 上游新增 packages:'); [print(f'    {p}') for p in sorted(new_pkgs)]
if removed_pkgs: print('💡 本地独有 packages:'); [print(f'    {p}') for p in sorted(removed_pkgs)]
if not new_pkgs and not removed_pkgs: print('✅ packages 一致')

# key fields
for f in ['defaultProvider','defaultModel','defaultThinkingLevel','theme','lastChangelogVersion']:
    uv, lv = up.get(f,'(无)'), lo.get(f,'(无)')
    if uv != lv: print(f'⚠️  {f}: 本地={lv} → 上游={uv}')

# enabledModels
um = up.get('enabledModels',[])
lm = lo.get('enabledModels',[])
if um != lm:
    print(f'⚠️  enabledModels: 内容不同（本地 {len(lm)} 个，上游 {len(um)} 个）')
    print(f'    上游: {", ".join(um)}')
    print(f'    本地: {", ".join(lm)}')
" "$UPSTREAM_SETTINGS" "$LOCAL_SETTINGS" 2>/dev/null
```

**pi-websearch.json — compare key fields:**

```bash
cd "{PI_SETUP}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
UPSTREAM_WS=$(git show upstream/$BRANCH:agent/pi-websearch.json 2>/dev/null)
LOCAL_WS=$(git show origin/$BRANCH:agent/pi-websearch.json 2>/dev/null)

python3 -c "
import json, sys
def get_nested(d, path):
    for k in path.split('.'): d = d.get(k,{}) if isinstance(d,dict) else {}; return d
up, lo = json.loads(sys.argv[1]), json.loads(sys.argv[2])
for f in ['provider','timeoutMs','searxng.url','searxng.script','defaults.numResults']:
    uv, lv = get_nested(up,f), get_nested(lo,f)
    if uv != lv: print(f'⚠️  {f}: 本地={lv} → 上游={uv}')
" "$UPSTREAM_WS" "$LOCAL_WS" 2>/dev/null
```

### 3c: Generate selection report

For each **module file**, show:
- Whether it's new (`A`), modified (`M`), or deleted (`D`)
- Brief description
- **Each D-status item gets its own line** (not bundled)

For **config files**, show:
- Summary of field-level differences from Step 3b
- Recommended merge strategy

**Report format:**

```
=== 模块文件 ===
1) agent/extensions/foo/ (M) — <description>
2) skills/bar/ (A) — <description>
3) skills/u/setup-update/ (D) — ⚠️ 删除此技能自身

=== 配置文件 ===
C1) settings.json:
     ✅ 合并 packages（新增: npm:xxx）
     ✅ 合并 lastChangelogVersion
     ⏭️ 保留本地: defaultProvider, defaultModel, enabledModels 等
C2) pi-websearch.json: ⏭️ 全部保留本地

=== 选项 ===
A) 全部模块合并（不含配置文件）
1,2) 选择特定模块
C) 合并推荐的配置字段（packages, lastChangelogVersion）
跳过C) 不合并配置文件
```



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

If neither repo has upstream changes AND no file-level diff → "已是最新" and STOP.

**⚠️ Self-deletion warning:** If `D skills/u/setup-update/` appears in the diff, merging it will delete this skill itself. Flag this prominently in the report: "⚠️ 此操作将删除 setup-update 技能自身，确定要继续吗？"

---

## Step 3.5: Install Recommended npm Packages

If user selected the "安装上游推荐的 npm 包" option (from settings.json `packages` diff),
install each new package:

```bash
# For each new package in NEW_PKGS:
pi install {package_name}
```

After installation, verify:

```bash
pi list
```

Report which packages were installed and note: "⚠️ npm 包已安装到 RUNTIME 的 npm/ 目录，不受 git 管理。如需跨机器同步，建议将新包也添加到本地 pi-setup 的 settings.json 中。"

---

## Step 4: Merge Selected Module Files

Only merge **module files** in this step. Config files are handled in Step 4.5.

**Record pre-merge HEAD for precise rollback (only undo the merge, not the pull):**

```bash
PI_SETUP_PRE_MERGE=$(cd "{PI_SETUP}" && git rev-parse HEAD)
AGENT_SETUP_PRE_MERGE=$(cd "{AGENT_SETUP}" && git rev-parse HEAD)
```

**CRITICAL: Handle by diff status, NOT uniform `git checkout`:**

| Status | Meaning | Command |
|--------|---------|---------|
| `A` | New in upstream | `git checkout upstream/$BRANCH -- {path}` |
| `M` | Modified in upstream | `git checkout upstream/$BRANCH -- {path}` |
| `D` | Deleted in upstream | `git rm -- {path}` (file) or `git rm -r -- {path}` (dir) |

```bash
cd "{repo}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Verify upstream is reachable before any checkout
if ! git rev-parse upstream/$BRANCH >/dev/null 2>&1; then
  echo "❌ upstream/$BRANCH 不可达，请先执行 git fetch upstream" >&2
  exit 1
fi

# For {status, path} pairs:
case "{status}" in
  D)
    if [ -d "{path}" ]; then
      git rm -r -- "{path}" && echo "✅ merged (deleted dir): {path}" || { echo "❌ merge failed: {path}" >&2; exit 1; }
    else
      git rm -- "{path}" && echo "✅ merged (deleted file): {path}" || { echo "❌ merge failed: {path}" >&2; exit 1; }
    fi
    ;;
  *)
    git checkout upstream/$BRANCH -- "{path}" && echo "✅ merged: {path}" || { echo "❌ merge failed: {path}" >&2; exit 1; }
    ;;
esac
```

After all checkouts, verify:

```bash
cd "{repo}"
git status --short
echo "---"
echo "以上为本次合并引入的变更，确认无误后继续。"
```

---

## Step 4.5: Merge Config Files (Field-Level)

**This step is separate from Step 4 because config files need field-level merge, NOT file-level overwrite.**

For each config file the user chose to merge:

### settings.json merge strategy

The goal: **keep all user-customized fields, selectively merge upstream-recommended fields.**

**NEVER-OVERWRITE fields** (user-specific, upstream values are irrelevant):
- `defaultProvider`, `defaultModel`, `defaultThinkingLevel`
- `theme`, `externalEditor`, `enableSkillCommands`
- `enabledModels` (must match user's actual providers in models.json)
- `terminal`, `treeFilterMode`, `hideThinkingBlock`

**SAFE-TO-MERGE fields** (upstream recommendations):
- `lastChangelogVersion` — always take upstream's value
- `packages` — union merge (keep local + add upstream new)

```bash
cd "{PI_SETUP}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

UPSTREAM_SETTINGS=$(git show upstream/$BRANCH:agent/settings.json 2>/dev/null)
LOCAL_SETTINGS=$(cat "{RUNTIME}/settings.json" 2>/dev/null)

# Start with LOCAL as base
MERGED="$LOCAL_SETTINGS"

# --- Merge packages (union: keep local + add upstream new) ---
NEW_PKGS=$(python3 -c "
import json, sys
up = set(json.loads(sys.argv[1]).get('packages',[]))
lo = set(json.loads(sys.argv[2]).get('packages',[]))
for p in sorted(up - lo): print(p)
" "$UPSTREAM_SETTINGS" "$LOCAL_SETTINGS" 2>/dev/null)

if [ -n "$NEW_PKGS" ]; then
  MERGED=$(python3 -c "
import json, sys
j = json.loads(sys.argv[1])
for p in sys.argv[2].strip().split('\n'):
    p = p.strip()
    if p and p not in j.get('packages',[]): j.setdefault('packages',[]).append(p)
print(json.dumps(j))
" "$MERGED" "$NEW_PKGS" 2>/dev/null)
  echo "✅ settings.json: 已合并新增 packages"
fi

# --- Merge lastChangelogVersion (always take upstream's value) ---
UPSTREAM_VER=$(python3 -c "import json,sys;print(json.loads(sys.argv[1]).get('lastChangelogVersion',''))" "$UPSTREAM_SETTINGS" 2>/dev/null)
if [ -n "$UPSTREAM_VER" ]; then
  MERGED=$(python3 -c "
import json, sys
j = json.loads(sys.argv[1])
j['lastChangelogVersion'] = sys.argv[2]
print(json.dumps(j))
" "$MERGED" "$UPSTREAM_VER" 2>/dev/null)
  echo "✅ settings.json: 已更新 lastChangelogVersion → $UPSTREAM_VER"
fi

# --- All other fields: KEEP LOCAL ---
echo "⏭️ settings.json: 保留本地自定义字段 (provider, model, theme, enabledModels, externalEditor 等)"

# Write merged result
echo "$MERGED" | python3 -c "import json,sys;print(json.dumps(json.loads(sys.stdin.read()),indent=2))" > "{RUNTIME}/settings.json"
echo "✅ settings.json 已写入 runtime"

# --- Verify enabledModels matches models.json providers ---
MODELS_FILE="{RUNTIME}/models.json"
if [ -f "$MODELS_FILE" ]; then
  python3 -c "
import json, sys
with open(sys.argv[1]) as f: providers = set(json.load(f).get('providers',{}).keys())
with open(sys.argv[2]) as f: enabled = json.load(f).get('enabledModels',[])
bad = [m for m in enabled if m.split('/')[0] not in providers]
if bad:
    print('⚠️  enabledModels 包含 models.json 中不存在的 provider:')
    for m in bad: print(f'    {m}')
    print('   请手动检查 enabledModels 是否与 models.json 一致')
else:
    print('✅ enabledModels 与 models.json providers 一致')
  " "$MODELS_FILE" "{RUNTIME}/settings.json" 2>/dev/null
fi
```

### pi-websearch.json merge strategy

**Default: keep local.** pi-websearch.json is almost entirely user-specific (searxng URL, script path).
Only merge if user explicitly requested specific fields.

### Other config files

For other config files (auth.json, trust.json, models-store.json, pi-lsp.json):
- **Default: keep local** unless user explicitly requested merge
- If merge requested: show diff, ask user which fields to take from upstream
- Apply same pattern: local base + selective upstream fields

---

## Step 5: Sync to Runtime

After all selected modules and config merges are done, sync module files to runtime.

**pi-setup sync — module files only, config files already handled in Step 4.5:**

```bash
set -euo pipefail
SRC="{PI_SETUP}/agent"
DST="{RUNTIME}"

# Guard: SRC must exist
if [ ! -d "$SRC" ]; then
  echo "❌ 源目录不存在: $SRC — 终止同步" >&2
  exit 1
fi

# Config files — already merged in Step 4.5, DO NOT overwrite from repo.
# Protected dirs — runtime data, never sync from repo.
CONFIG_FILES="settings.json pi-websearch.json auth.json trust.json models-store.json models.json pi-lsp.json subagent-model.json pi-chrome-devtools.json"
PROTECTED_DIRS="sessions bin git npm searxng-instances skills"

shopt -s nullglob

for item in "$SRC"/*; do
  name=$(basename "$item")

  if [ -z "$name" ]; then
    echo "⚠ 跳过异常条目: $item" >&2
    continue
  fi

  # Skip config files (already handled by Step 4.5)
  if echo " $CONFIG_FILES " | grep -q " $name "; then
    echo "⏭️ 跳过配置文件（已由 Step 4.5 处理）: $name"
    continue
  fi

  # Skip protected dirs
  if echo " $PROTECTED_DIRS " | grep -q " $name "; then
    echo "⏭️ 跳过受保护目录: $name"
    continue
  fi

  # Sync module files
  case "$name" in .|..) echo "⚠ 拒绝危险路径: $name" >&2; continue ;; esac
  rm -rf "$DST/$name" 2>/dev/null
  cp -r "$item" "$DST/$name" && echo "✅ 同步: $name"
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

# Guard: SRC must exist
if [ ! -d "$SRC" ]; then
  echo "❌ 源目录不存在: $SRC — 终止同步" >&2
  exit 1
fi

# Guard: DST must be within RUNTIME (prevent catastrophic misconfiguration)
case "$DST" in
  {RUNTIME}/*) ;;
  *) echo "❌ 目标路径异常: $DST — 终止同步" >&2; exit 1 ;;
esac
# Secondary guard: reject path traversal via ..
case "$DST" in
  *..*) echo "❌ 目标路径包含 .. — 终止同步" >&2; exit 1 ;;
esac

rm -rf "$DST"
cp -r "$SRC" "$DST" && echo "✅ 同步 skills"
```

---

## Step 6: Auto-Test

After sync, run automated validation checks to verify correctness before prompting user.

**LLM must build the test paths from the merged module list:**
- For each `D` (deleted) file in pi-setup's `agent/` path, derive the runtime path by replacing `agent/` prefix with `{RUNTIME}/`
  - e.g. `agent/agents/foo.md` → `{RUNTIME}/agents/foo.md`
- For each `M` (modified) or `A` (added) file, same path derivation
- For skills from agent-setup, the runtime path is `{RUNTIME}/skills/` + the relative path within agent-setup's `skills/` dir

### Test Suite

**Test 1 — git stage verification:**

```bash
echo "--- 1. git 暂存区状态 ---"
cd "{PI_SETUP}" && git status --short 2>/dev/null
cd "{AGENT_SETUP}" && git status --short 2>/dev/null
echo "解读: 以上为合并引入的变更，应与 Step 4 的预期一致"
```

**Test 2 — deleted files removed from runtime:**

For each deleted path, verify it no longer exists.

```bash
cd "{RUNTIME}"
# LLM: replace paths below with actual {deleted_paths} from merge
for file in {deleted_path_1} {deleted_path_2}; do
  if [ -e "$file" ]; then
    echo "❌ 应删除但仍存在: $file"
  else
    echo "✅ 已正确删除: $file"
  fi
done
```

**Test 3 — modified/new files integrity check:**

For each modified or added file, check it exists and is readable. For `.ts` files, do a
TypeScript syntax check with `npx tsc --noEmit` if available; otherwise fall back to a
basic `node --check` parse. For `.json` files, validate JSON syntax.

```bash
cd "{RUNTIME}"
# LLM: replace paths below with actual {modified_paths} from merge
for file in {modified_path_1} {modified_path_2}; do
  if [ ! -f "$file" ]; then
    echo "❌ 文件缺失: $file"
    continue
  fi
  case "$file" in
    *.ts)
      python3 -c "import sys;open(sys.argv[1]).read();print('✅ 可读: '+sys.argv[1])" "$file" 2>&1
      ;;
    *.json)
      python3 -c "import json,sys;json.load(open(sys.argv[1]));print('✅ 合法JSON: '+sys.argv[1])" "$file" 2>&1
      ;;
    *)
      if [ -s "$file" ]; then
        echo "✅ 文件存在且非空: $file"
      else
        echo "⚠️  文件为空: $file"
      fi
      ;;
  esac
done
```

**Test 4 — config files merged correctly:**

```bash
echo "--- 4. 配置文件验证 ---"
# settings.json should be valid JSON AND contain user's custom fields
RT_SETTINGS="{RUNTIME}/settings.json"
if [ -f "$RT_SETTINGS" ]; then
  python3 -c "import json,sys;json.load(open(sys.argv[1]));print('✅ settings.json: 合法JSON')" "$RT_SETTINGS" 2>&1
  # Verify user fields preserved
  PROVIDER=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('defaultProvider',''))" "$RT_SETTINGS" 2>/dev/null)
  MODEL=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('defaultModel',''))" "$RT_SETTINGS" 2>/dev/null)
  if [ -n "$PROVIDER" ] && [ "$PROVIDER" != "undefined" ]; then
    echo "✅ settings.json: defaultProvider=$PROVIDER"
  else
    echo "⚠️  settings.json: defaultProvider 缺失"
  fi
  if [ -n "$MODEL" ] && [ "$MODEL" != "undefined" ]; then
    echo "✅ settings.json: defaultModel=$MODEL"
  else
    echo "⚠️  settings.json: defaultModel 缺失"
  fi
else
  echo "❌ settings.json 缺失"
fi

# Other config files still intact
for f in "{RUNTIME}/auth.json" "{RUNTIME}/trust.json" "{RUNTIME}/pi-websearch.json"; do
  if [ -f "$f" ]; then
    echo "✅ 配置文件完好: $(basename "$f")"
  else
    echo "⚠️  配置文件缺失: $f"
  fi
done
```

**Test 5 — skills sync count match (if agent-setup has skills):**

```bash
if [ -d "{AGENT_SETUP}/skills" ]; then
  AG_COUNT=$(find "{AGENT_SETUP}/skills" -name "SKILL.md" 2>/dev/null | wc -l)
  RT_COUNT=$(find "{RUNTIME}/skills" -name "SKILL.md" 2>/dev/null | wc -l)
  if [ "$AG_COUNT" -eq "$RT_COUNT" ]; then
    echo "✅ skills 数量一致: $AG_COUNT"
  else
    echo "⚠️  skills 数量不一致: agent-setup=$AG_COUNT, runtime=$RT_COUNT"
  fi
else
  echo "⏭️ agent-setup/skills 不存在，跳过 skills 验证"
fi
```

### Report results

After running all tests, count pass/fail/warn and report:

```
🧪 自动化测试完成:
  ✅ N 项通过
  ❌ N 项失败
  ⚠️  N 项警告

  [details of any failures]
```

If any ❌ FAILED → report to user and suggest rollback.
If all pass or only warnings → proceed:

```
🧪 自动化测试已通过。变更汇总:
  - <list merged modules>

回复 "OK" 推送到 origin，或 "回滚" 撤销所有改动。
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
cd "{repo}"
git add {selected_paths}
git commit -m "{generated_message}" || { echo "❌ 提交失败"; exit 1; }
```

```bash
cd "{repo}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin $BRANCH || { echo "❌ 推送失败，检查网络或权限"; exit 1; }
```

---

## Step 8: Verify and Report

```bash
cd "{PI_SETUP}" && echo "pi-setup: $(git rev-parse --short HEAD) (origin: $(git ls-remote origin $(git rev-parse --abbrev-ref HEAD) | cut -c1-7))"
cd "{AGENT_SETUP}" && echo "agent-setup: $(git rev-parse --short HEAD) (origin: $(git ls-remote origin $(git rev-parse --abbrev-ref HEAD) | cut -c1-7))"
```

**Summary:**

| Item | Action |
|------|--------|
| Modules merged | list |
| Pushed to origin | commit hash |
| npm packages installed | list (from Step 3.5) |
| Protected (skipped) | list |
| Local-only packages (保留) | list |

Tell user to restart pi if runtime was synced.

---

## Rollback

If user says "回滚" at any point before pushing:

- **Before Step 4 (no merge yet):** rollback to `PRE_HEAD` (Step 0) — this also undoes the Step 1 pull.
  The pulled commits are still on origin, so a fresh `git pull` will restore them.
- **After Step 4 (merge done but not pushed):** rollback to `PRE_MERGE_HEAD` (Step 4) — this only
  undoes the merge, preserving the Step 1 pull.

```bash
cd "{repo}"
# PRE_MERGE_HEAD takes priority if it exists (merge phase rollback),
# fall back to PRE_HEAD (pre-pull rollback)
ROLLBACK_TARGET="${PRE_MERGE_HEAD:-$PRE_HEAD}"
git reset --hard "$ROLLBACK_TARGET"
git clean -fd
echo "✅ 已回滚到: $(git rev-parse --short HEAD)"
```

- `{PRE_HEAD}` = `PI_SETUP_PRE_HEAD` for pi-setup, `AGENT_SETUP_PRE_HEAD` for agent-setup (recorded in Step 0).
- `{PRE_MERGE_HEAD}` = `PI_SETUP_PRE_MERGE` for pi-setup, `AGENT_SETUP_PRE_MERGE` for agent-setup (recorded in Step 4).

**After rollback, FULL reverse-sync runtime from repos:**

Unlike Step 5 (which skips config files because they were merged in Step 4.5), the rollback
reverse-sync must restore ALL files — including config files — from the rolled-back repos.

```bash
set -euo pipefail
SRC="{PI_SETUP}/agent"
DST="{RUNTIME}"
if [ ! -d "$SRC" ]; then echo "❌ 源目录不存在: $SRC" >&2; exit 1; fi

# Only skip protected dirs — config files MUST be synced during rollback
PROTECTED_DIRS="sessions bin git npm searxng-instances skills"

shopt -s nullglob
for item in "$SRC"/*; do
  name=$(basename "$item")
  [ -z "$name" ] && continue
  case "$name" in .|..) continue ;; esac
  if echo " $PROTECTED_DIRS " | grep -q " $name "; then
    echo "⏭️ 跳过受保护目录: $name"
  else
    rm -rf "$DST/$name" 2>/dev/null
    cp -r "$item" "$DST/$name" && echo "✅ 回滚同步: $name"
  fi
done

# Also sync skills from agent-setup
if [ -d "{AGENT_SETUP}/skills" ]; then
  rm -rf "$DST/skills"
  cp -r "{AGENT_SETUP}/skills" "$DST/skills" && echo "✅ 回滚同步: skills"
fi
echo "✅ runtime 已完整回滚"
```
