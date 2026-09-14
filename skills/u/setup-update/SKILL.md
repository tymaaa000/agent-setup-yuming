---
name: setup-update
description: "Manage the pi setup repos — review upstream changes by module, merge selectively, test locally, then push to origin. Use when the user says setup-update, 检查更新, 推送更新, or sync setup."
---

# Setup Update

Review upstream changes → select modules → merge → test → push to origin.

## Layout and paths

This machine runs a Linux-native pi installation:

| Variable | Value |
|----------|-------|
| `ROOT` | `${PI_ROOT:-$HOME/pi}` — installation root |
| `RUNTIME` | `$ROOT/agent` — the runtime agent directory (`PI_CODING_AGENT_DIR`) |
| `PI_SETUP` | `$ROOT/repos/pi-setup` — engine configuration repository |
| `AGENT_SETUP` | `$ROOT/repos/agent-setup` — skills repository |
| `SYNC` | `$ROOT/bin/sync-pi.sh` — repository → runtime sync (rsync --delete) |

Remotes: `origin` = the user's personal repo, `upstream` = the aqua2k1 original.

**Shell preamble.** Every `bash` call runs in a fresh process, so variables do not persist.
Prepend this line to any block you execute (or export it once and run the block in the same
shell):

```bash
ROOT="${PI_ROOT:-$HOME/pi}"; RUNTIME="${PI_CODING_AGENT_DIR:-$ROOT/agent}"; PI_SETUP="$ROOT/repos/pi-setup"; AGENT_SETUP="$ROOT/repos/agent-setup"; SYNC="$ROOT/bin/sync-pi.sh"
```

The scripts themselves already honour `PI_ROOT` / `PI_CODING_AGENT_DIR`, so passing those
two variables is enough to run a non-default installation.

**⚠️ Before any destructive operation (rm, cp -r), verify each path starts with the expected
prefix (for example `/home/<user>/pi/`) to prevent catastrophic misconfiguration.**

---

## Step 0: Pre-check — clean working tree

**CRITICAL: stop if the working tree is dirty.** A merge can silently overwrite local changes.

```bash
for repo in "$PI_SETUP" "$AGENT_SETUP"; do
  cd "$repo"
  if [ -n "$(git status --porcelain)" ]; then
    echo "❌ $repo has uncommitted changes — commit or stash them first:" >&2
    git status --short
    exit 1
  fi
done

echo "✅ Working trees are clean"

# Record pre-merge HEAD for rollback
PI_SETUP_PRE_HEAD=$(cd "$PI_SETUP" && git rev-parse HEAD)
AGENT_SETUP_PRE_HEAD=$(cd "$AGENT_SETUP" && git rev-parse HEAD)
echo "PI_SETUP_PRE_HEAD=$PI_SETUP_PRE_HEAD"
echo "AGENT_SETUP_PRE_HEAD=$AGENT_SETUP_PRE_HEAD"
```

---

## Step 1: Pull origin + fetch upstream

**Record the pre-pull HEAD to detect what `git pull` actually brought in:**

```bash
cd "$PI_SETUP"
PI_SETUP_PRE_PULL=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD) && git pull origin "$BRANCH" || echo "⚠ pi-setup pull failed"
if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then
  echo "❌ pi-setup has merge conflicts — resolve them manually and retry:" >&2
  git diff --name-only --diff-filter=U
  exit 1
fi
PI_SETUP_POST_PULL=$(git rev-parse HEAD)

cd "$AGENT_SETUP"
AGENT_SETUP_PRE_PULL=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD) && git pull origin "$BRANCH" || echo "⚠ agent-setup pull failed"
if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then
  echo "❌ agent-setup has merge conflicts — resolve them manually and retry:" >&2
  git diff --name-only --diff-filter=U
  exit 1
fi
AGENT_SETUP_POST_PULL=$(git rev-parse HEAD)
```

```bash
cd "$PI_SETUP" && git fetch upstream 2>/dev/null || echo "⚠ pi-setup upstream unreachable"
cd "$AGENT_SETUP" && git fetch upstream 2>/dev/null || echo "⚠ agent-setup upstream unreachable"
```

---

## Step 2: Show upstream changes by module

**GOAL: report EVERY upstream change not yet incorporated into origin — never claim "up to date"
when upstream has moved ahead.**

### How not to miss changes

Use **merge-base** (not origin HEAD) as the diff baseline. This is the only way to guarantee
zero false negatives:

- `origin/main..upstream/main` shows commits upstream has but origin does not — correct when
  origin is strictly behind.
- When origin already merged some upstream commits and added its own on top, the `..` operator
  still excludes everything reachable from origin.
- The **real danger** is `git pull` fast-forwarding origin silently before we can diff. The
  pre-pull / post-pull recording in Step 1 guards against that: if pull moved HEAD, report those
  commits explicitly.

**Two comparisons are needed:**

1. `origin/main..upstream/main` — upstream commits not yet in origin (the ones to merge)
2. `PI_SETUP_PRE_PULL..PI_SETUP_POST_PULL` — commits `git pull` just brought in

### pi-setup

```bash
cd "$PI_SETUP"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
MERGE_BASE=$(git merge-base origin/$BRANCH upstream/$BRANCH 2>/dev/null || echo "")

echo "=== pi-setup ==="
echo "local HEAD:    $(git rev-parse --short HEAD)"
echo "origin HEAD:   $(git rev-parse --short origin/$BRANCH)"
echo "upstream HEAD: $(git rev-parse --short upstream/$BRANCH 2>/dev/null || echo N/A)"
if [ -n "$MERGE_BASE" ]; then
  echo "merge-base:    $(git rev-parse --short $MERGE_BASE)"
fi
echo ""

# Report what the pull just brought in (recorded in Step 1)
if [ "$PI_SETUP_PRE_PULL" != "$PI_SETUP_POST_PULL" ]; then
  echo "--- commits fetched by git pull ---"
  git log --oneline $PI_SETUP_PRE_PULL..$PI_SETUP_POST_PULL
  echo ""
fi

# Show what upstream has that origin does not
UPSTREAM_COMMITS=$(git log --oneline origin/$BRANCH..upstream/$BRANCH 2>/dev/null)
if [ -z "$UPSTREAM_COMMITS" ]; then
  echo "✅ pi-setup: origin contains all upstream commits (nothing new)"

  # EVEN when origin..upstream is empty, origin and upstream may differ at file level
  # when origin has its own commits on top and missed merges (e.g. D-status deletions).
  FILE_DIFF=$(git diff --name-status origin/$BRANCH upstream/$BRANCH 2>/dev/null)
  if [ -n "$FILE_DIFF" ]; then
    echo ""
    echo "--- ⚠️ file-level differences between origin and upstream ---"
    echo "$FILE_DIFF"
    echo ""
    echo "   Legend: D = upstream deleted, you kept | M = both sides differ | A = you have it, upstream does not"
  else
    echo "   (file contents are identical too)"
  fi
else
  echo "--- 📋 upstream commits not yet merged into origin ---"
  echo "$UPSTREAM_COMMITS"
  echo ""
  echo "--- 📁 file-level changes (upstream vs origin) ---"
  git diff --name-status origin/$BRANCH..upstream/$BRANCH 2>/dev/null | while read -r status file; do
    echo "$status  $file"
  done
fi
```

### agent-setup

```bash
cd "$AGENT_SETUP"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
MERGE_BASE=$(git merge-base origin/$BRANCH upstream/$BRANCH 2>/dev/null || echo "")

echo ""
echo "=== agent-setup ==="
echo "local HEAD:    $(git rev-parse --short HEAD)"
echo "origin HEAD:   $(git rev-parse --short origin/$BRANCH)"
echo "upstream HEAD: $(git rev-parse --short upstream/$BRANCH 2>/dev/null || echo N/A)"
if [ -n "$MERGE_BASE" ]; then
  echo "merge-base:    $(git rev-parse --short $MERGE_BASE)"
fi
echo ""

# Report what the pull just brought in
if [ "$AGENT_SETUP_PRE_PULL" != "$AGENT_SETUP_POST_PULL" ]; then
  echo "--- commits fetched by git pull ---"
  git log --oneline $AGENT_SETUP_PRE_PULL..$AGENT_SETUP_POST_PULL
  echo ""
fi

UPSTREAM_COMMITS=$(git log --oneline origin/$BRANCH..upstream/$BRANCH 2>/dev/null)
if [ -z "$UPSTREAM_COMMITS" ]; then
  echo "✅ agent-setup: origin contains all upstream commits (nothing new)"

  # Same fallback as pi-setup: catch file-level drift when origin has its own commits.
  FILE_DIFF=$(git diff --name-status origin/$BRANCH upstream/$BRANCH 2>/dev/null)
  if [ -n "$FILE_DIFF" ]; then
    echo ""
    echo "--- ⚠️ file-level differences between origin and upstream ---"
    echo "$FILE_DIFF"
    echo ""
    echo "   Legend: D = upstream deleted, you kept | M = both sides differ | A = you have it, upstream does not"
  else
    echo "   (file contents are identical too)"
  fi
else
  echo "--- 📋 upstream commits not yet merged into origin ---"
  echo "$UPSTREAM_COMMITS"
  echo ""
  echo "--- 📁 file-level changes (upstream vs origin) ---"
  git diff --name-status origin/$BRANCH..upstream/$BRANCH 2>/dev/null | while read -r status file; do
    echo "$status  $file"
  done
fi
```

### Integrity check (per repo)

After both diffs, interpret the Step 2 output to judge integrity. Do NOT run a separate script —
use the values already printed above.

| Step 2 output | Meaning | Action |
|---------------|---------|--------|
| "📋 upstream commits" has entries | upstream has commits origin lacks | Normal — continue to Step 3 |
| "✅ up to date" for BOTH repos, no file diff | origin has all upstream commits and files match | ✅ STOP — nothing to merge |
| "✅ up to date" but a file-level diff appears | origin has the commits but files differ (e.g. D-status deletions from an earlier partial merge) | ⚠️ Report the file diff to the user — these still need merging |
| "✅ up to date" but merge-base != upstream HEAD | Inconsistency — possible force-push or stale fetch | ⚠️ Warn the user: "merge-base != upstream HEAD with an empty diff; upstream may have been force-pushed" |
| "commits fetched by git pull" has entries but no upstream diff | origin gained its own commits (not from upstream) | Report them — nothing to merge from upstream |
| upstream HEAD shows "N/A" | fetch failed or upstream unreachable | ⚠️ Warn the user: "upstream unreachable; check network and SSH keys" |
| merge-base cannot be computed | upstream branch ref missing | ⚠️ Warn the user: "cannot compute merge-base; the upstream branch may not exist" |

---

## Step 3: Group, classify, and report — STOP HERE

**CRITICAL: do NOT proceed without user confirmation.**

### 3a: Classify every changed file

Parse the `git diff --name-status` output and classify each file:

| Category | Includes | Handling |
|----------|----------|----------|
| **Module files** | extensions/, agents/, prompts/, skills/, APPEND_SYSTEM.md, searxng.sh, other non-config | Step 4: `git checkout upstream` |
| **Config files** | settings.json, pi-websearch.json, pi-lsp.json, models.json, models-store.json, trust.json, subagent-model.json, pi-fff.json, pi-auto-compact.json | Step 4.5: field-level merge |

**Path prefix note:** pi-setup diff paths include the `agent/` prefix (for example
`agent/extensions/foo.ts`). Use the full diff path as `{selected_path}` for the Step 4 checkout —
do NOT strip `agent/`.

Group module files by top-level directory for individual selection.

### 3b: Config file field-level analysis

For each config file in the diff, compare fields:

**settings.json — extract and compare key fields:**

```bash
cd "$PI_SETUP"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

UPSTREAM_SETTINGS=$(git show upstream/$BRANCH:agent/settings.json 2>/dev/null)
LOCAL_SETTINGS=$(git show origin/$BRANCH:agent/settings.json 2>/dev/null)

echo "=== settings.json field comparison ==="

python3 -c "
import json, sys
up = json.loads(sys.argv[1])
lo = json.loads(sys.argv[2])

# packages
up_pkgs = set(up.get('packages', []))
lo_pkgs = set(lo.get('packages', []))
new_pkgs = up_pkgs - lo_pkgs
removed_pkgs = lo_pkgs - up_pkgs
if new_pkgs: print('🔔 upstream added packages:'); [print(f'    {p}') for p in sorted(new_pkgs)]
if removed_pkgs: print('💡 local-only packages:'); [print(f'    {p}') for p in sorted(removed_pkgs)]
if not new_pkgs and not removed_pkgs: print('✅ packages identical')

# key fields
for f in ['defaultProvider','defaultModel','defaultThinkingLevel','theme','lastChangelogVersion']:
    uv, lv = up.get(f,'(none)'), lo.get(f,'(none)')
    if uv != lv: print(f'⚠️  {f}: local={lv} -> upstream={uv}')

# enabledModels
um = up.get('enabledModels',[])
lm = lo.get('enabledModels',[])
if um != lm:
    print(f'⚠️  enabledModels: differs (local {len(lm)}, upstream {len(um)})')
    print(f'    upstream: {\", \".join(um)}')
    print(f'    local:    {\", \".join(lm)}')
" "$UPSTREAM_SETTINGS" "$LOCAL_SETTINGS" 2>/dev/null
```

**pi-websearch.json — compare key fields:**

```bash
cd "$PI_SETUP"
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
    if uv != lv: print(f'⚠️  {f}: local={lv} -> upstream={uv}')
" "$UPSTREAM_WS" "$LOCAL_WS" 2>/dev/null
```

### 3c: Generate the selection report

For each **module file**, show:
- Whether it is new (`A`), modified (`M`), or deleted (`D`)
- A brief description
- **Each D-status item gets its own line** (never bundled)

For **config files**, show:
- The field-level differences from Step 3b
- The recommended merge strategy

**Report format:**

```
=== Module files ===
1) agent/extensions/foo/ (M) — <description>
2) skills/bar/ (A) — <description>
3) skills/u/setup-update/ (D) — ⚠️ would delete this skill itself

=== Config files ===
C1) settings.json:
     ✅ merge packages (new: npm:xxx)
     ✅ merge lastChangelogVersion
     ⏭️ keep local: defaultProvider, defaultModel, enabledModels, ...
C2) pi-websearch.json: ⏭️ keep local entirely

=== Options ===
A) merge all modules (config files excluded)
1,2) pick specific modules
C) merge the recommended config fields (packages, lastChangelogVersion)
skip C) do not merge config files
```

**Multiple-choice options:**

```
A) merge everything (config files excluded)
B) agent/extensions/foo/ — <description>
C) skills/bar/ — <description>
... (one option per module, using the full diff path)
⚠️  config files are handled separately — confirm each one before merging
```

> 💡 Separate multiple selections with commas, e.g. `B,D`. Choosing `A` ignores the others.

If neither repo has upstream changes and there is no file-level diff → "up to date" and STOP.

**⚠️ Self-deletion warning:** if `D skills/u/setup-update/` appears in the diff, merging deletes
this skill itself. Flag it prominently: "⚠️ this would delete the setup-update skill itself —
continue?"

---

## Step 3.5: Install recommended npm packages

If the user selected the "install upstream-recommended npm packages" option (from the
settings.json `packages` diff), install each new package:

```bash
# For each new package in NEW_PKGS:
"$ROOT/bin/pi" install {package_name}
```

After installing, verify:

```bash
"$ROOT/bin/pi" list
```

Report which packages were installed and note: "⚠️ npm packages install into the RUNTIME
`npm/` directory and are not tracked by git. To reproduce them on another machine, also add
them to the local pi-setup settings.json."

---

## Step 4: Merge the selected module files

Only merge **module files** here. Config files are handled in Step 4.5.

**Record the pre-merge HEAD for precise rollback (undo the merge only, not the pull):**

```bash
PI_SETUP_PRE_MERGE=$(cd "$PI_SETUP" && git rev-parse HEAD)
AGENT_SETUP_PRE_MERGE=$(cd "$AGENT_SETUP" && git rev-parse HEAD)
```

**CRITICAL: handle by diff status, NOT a uniform `git checkout`:**

| Status | Meaning | Command |
|--------|---------|---------|
| `A` | new in upstream | `git checkout upstream/$BRANCH -- {path}` |
| `M` | modified in upstream | `git checkout upstream/$BRANCH -- {path}` |
| `D` | deleted in upstream | `git rm -- {path}` (file) or `git rm -r -- {path}` (dir) |

```bash
cd "{repo}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Verify upstream is reachable before any checkout
if ! git rev-parse upstream/$BRANCH >/dev/null 2>&1; then
  echo "❌ upstream/$BRANCH unreachable; run git fetch upstream first" >&2
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
echo "Changes introduced by this merge; review before continuing."
```

---

## Step 4.5: Merge config files (field level)

**This step is separate from Step 4 because config files need field-level merging, not a
file-level overwrite.**

### settings.json merge strategy

Goal: **keep every user-customized field and selectively take upstream-recommended fields.**

**NEVER-OVERWRITE fields** (user-specific; upstream values are irrelevant):
- `defaultProvider`, `defaultModel`, `defaultThinkingLevel`
- `theme`, `externalEditor`, `enableSkillCommands`
- `enabledModels` (must match the providers actually configured in models.json)
- `terminal`, `treeFilterMode`, `hideThinkingBlock`, `skillful`

**SAFE-TO-MERGE fields** (upstream recommendations):
- `lastChangelogVersion` — always take upstream's value
- `packages` — union merge (keep local + add upstream additions)

```bash
cd "$PI_SETUP"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

UPSTREAM_SETTINGS=$(git show upstream/$BRANCH:agent/settings.json 2>/dev/null)
LOCAL_SETTINGS=$(cat "$RUNTIME/settings.json" 2>/dev/null)

# Start from LOCAL as the base
MERGED="$LOCAL_SETTINGS"

# --- Merge packages (union: keep local + add upstream additions) ---
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
  echo "✅ settings.json: merged new packages"
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
  echo "✅ settings.json: updated lastChangelogVersion -> $UPSTREAM_VER"
fi

# --- Every other field: KEEP LOCAL ---
echo "⏭️ settings.json: kept local custom fields (provider, model, theme, enabledModels, externalEditor, ...)"

# Write the merged result
echo "$MERGED" | python3 -c "import json,sys;print(json.dumps(json.loads(sys.stdin.read()),indent=2))" > "$RUNTIME/settings.json"
echo "✅ settings.json written to the runtime"

# --- Verify enabledModels matches models.json providers ---
MODELS_FILE="$RUNTIME/models.json"
if [ -f "$MODELS_FILE" ]; then
  python3 -c "
import json, sys
with open(sys.argv[1]) as f: providers = set(json.load(f).get('providers',{}).keys())
with open(sys.argv[2]) as f: enabled = json.load(f).get('enabledModels',[])
bad = [m for m in enabled if m.split('/')[0] not in providers]
if bad:
    print('⚠️  enabledModels references providers missing from models.json:')
    for m in bad: print(f'    {m}')
    print('   Check enabledModels against models.json manually')
else:
    print('✅ enabledModels matches models.json providers')
  " "$MODELS_FILE" "$RUNTIME/settings.json" 2>/dev/null
fi
```

### pi-websearch.json merge strategy

**Default: keep local.** pi-websearch.json is almost entirely user-specific (SearXNG URL and
script path). Merge only when the user explicitly requests specific fields.

### Other config files

For other config files (pi-lsp.json, pi-fff.json, pi-auto-compact.json, trust.json,
models-store.json):
- **Default: keep local** unless the user explicitly requests a merge
- If a merge is requested: show the diff and ask which fields to take from upstream
- Apply the same pattern: local base plus selective upstream fields

---

## Step 5: Sync to runtime

After the selected modules and config merges are done, sync module files to the runtime.

**pi-setup + agent-setup sync — use the repository sync tool:**

```bash
# Module files only (extensions/, agents/, prompts/, skills/); config files are never
# touched by this script, so the Step 4.5 merges stay intact.
bash "$SYNC"

# Confirm no drift remains
bash "$SYNC" --check
```

> ℹ️ `sync-pi.sh` runs `rsync --delete` on the module paths. Files that exist only in the
> runtime are removed, which is exactly what Step 4's D-status handling expects. It never
> touches `settings.json`, `bin/`, `npm/`, `git/`, or `sessions/`.

---

## Step 6: Auto-test

After the sync, run automated validation before asking the user to confirm.

**Derive test paths from the merged module list:**
- For each pi-setup path (with the `agent/` prefix), the runtime path replaces `agent/` with
  `$RUNTIME/`
  - e.g. `agent/agents/foo.md` → `$RUNTIME/agents/foo.md`
- For agent-setup skills, the runtime path is `$RUNTIME/skills/` + the path relative to
  agent-setup's `skills/` directory

### Test suite

**Test 1 — git state:**

```bash
echo "--- 1. git status ---"
cd "$PI_SETUP" && git status --short 2>/dev/null
cd "$AGENT_SETUP" && git status --short 2>/dev/null
echo "These should match the Step 4 expectations."
```

**Test 2 — deleted files are gone from the runtime:**

```bash
cd "$RUNTIME"
# LLM: replace the paths below with the actual {deleted_paths} from the merge
for file in {deleted_path_1} {deleted_path_2}; do
  if [ -e "$file" ]; then
    echo "❌ should be deleted but still exists: $file"
  else
    echo "✅ correctly deleted: $file"
  fi
done
```

**Test 3 — modified/new files integrity:**

```bash
cd "$RUNTIME"
# LLM: replace the paths below with the actual {modified_paths} from the merge
for file in {modified_path_1} {modified_path_2}; do
  if [ ! -f "$file" ]; then
    echo "❌ missing file: $file"
    continue
  fi
  case "$file" in
    *.ts)
      /home/tym/pi/node/bin/node --check "$file" >/dev/null 2>&1 && echo "✅ TS parses: $file" || echo "⚠️  TS check failed (may use TS syntax): $file"
      ;;
    *.json)
      python3 -c "import json,sys;json.load(open(sys.argv[1]));print('✅ valid JSON: '+sys.argv[1])" "$file" 2>&1
      ;;
    *)
      if [ -s "$file" ]; then
        echo "✅ exists and is non-empty: $file"
      else
        echo "⚠️  empty file: $file"
      fi
      ;;
  esac
done
```

**Test 4 — config files merged correctly:**

```bash
echo "--- 4. configuration check ---"
RT_SETTINGS="$RUNTIME/settings.json"
if [ -f "$RT_SETTINGS" ]; then
  python3 -c "import json,sys;json.load(open(sys.argv[1]));print('✅ settings.json: valid JSON')" "$RT_SETTINGS" 2>&1
  PROVIDER=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('defaultProvider',''))" "$RT_SETTINGS" 2>/dev/null)
  MODEL=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('defaultModel',''))" "$RT_SETTINGS" 2>/dev/null)
  [ -n "$PROVIDER" ] && echo "✅ settings.json: defaultProvider=$PROVIDER" || echo "⚠️  settings.json: defaultProvider missing"
  [ -n "$MODEL" ] && echo "✅ settings.json: defaultModel=$MODEL" || echo "⚠️  settings.json: defaultModel missing"
else
  echo "❌ settings.json missing"
fi

for f in "$RUNTIME/auth.json" "$RUNTIME/trust.json" "$RUNTIME/pi-websearch.json"; do
  [ -f "$f" ] && echo "✅ intact: $(basename "$f")" || echo "⚠️  missing: $f"
done
```

**Test 5 — skills count matches (when agent-setup has skills):**

```bash
if [ -d "$AGENT_SETUP/skills" ]; then
  AG_COUNT=$(find "$AGENT_SETUP/skills" -name "SKILL.md" 2>/dev/null | wc -l)
  RT_COUNT=$(find "$RUNTIME/skills" -name "SKILL.md" 2>/dev/null | wc -l)
  if [ "$AG_COUNT" -eq "$RT_COUNT" ]; then
    echo "✅ skills count matches: $AG_COUNT"
  else
    echo "⚠️  skills count differs: agent-setup=$AG_COUNT, runtime=$RT_COUNT"
  fi
else
  echo "⏭️ agent-setup/skills missing; skipping the skills check"
fi
```

### Report results

Count pass/fail/warn and report:

```
🧪 Automated tests finished:
  ✅ N passed
  ❌ N failed
  ⚠️  N warnings

  [details of any failures]
```

If anything ❌ FAILED → report it and suggest a rollback.
If everything passes or only warns → continue:

```
🧪 Automated tests passed. Change summary:
  - <list of merged modules>

Reply "OK" to push to origin, or "rollback" to undo everything.
```

Wait for user confirmation.

---

## Step 7: Commit and push

After the user confirms the tests, generate the commit message and push.

**Commit message format:** `merge: upstream updates ({module_list})`

Where `{module_list}` is a comma-separated summary, for example:
- `merge: upstream updates (skills: setup-update, grill-me)`
- `merge: upstream updates (extensions: my-extension, agents: my-agent)`

```bash
cd "{repo}"
git add {selected_paths}
git commit -m "{generated_message}" || { echo "❌ commit failed"; exit 1; }
```

```bash
cd "{repo}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin "$BRANCH" || { echo "❌ push failed; check network or permissions"; exit 1; }
```

---

## Step 8: Verify and report

```bash
cd "$PI_SETUP" && echo "pi-setup: $(git rev-parse --short HEAD) (origin: $(git ls-remote origin $(git rev-parse --abbrev-ref HEAD) | cut -c1-7))"
cd "$AGENT_SETUP" && echo "agent-setup: $(git rev-parse --short HEAD) (origin: $(git ls-remote origin $(git rev-parse --abbrev-ref HEAD) | cut -c1-7))"
```

**Summary:**

| Item | Action |
|------|--------|
| Modules merged | list |
| Pushed to origin | commit hash |
| npm packages installed | list (from Step 3.5) |
| Protected (skipped) | list |
| Local-only packages (kept) | list |

Remind the user to run `/reload` in pi when the runtime was synced.

---

## Rollback

If the user says "rollback" at any point before the push:

- **Before Step 4 (nothing merged yet):** reset to `PRE_HEAD` (Step 0) — this also undoes the
  Step 1 pull. The pulled commits remain on origin, so a fresh `git pull` restores them.
- **After Step 4 (merged but not pushed):** reset to `PRE_MERGE_HEAD` (Step 4) — this undoes the
  merge while preserving the Step 1 pull.

```bash
cd "{repo}"
# PRE_MERGE_HEAD wins when set (merge-phase rollback); otherwise fall back to PRE_HEAD.
ROLLBACK_TARGET="${PRE_MERGE_HEAD:-$PRE_HEAD}"
git reset --hard "$ROLLBACK_TARGET"
git clean -fd
echo "✅ rolled back to: $(git rev-parse --short HEAD)"
```

- `{PRE_HEAD}` = `PI_SETUP_PRE_HEAD` for pi-setup, `AGENT_SETUP_PRE_HEAD` for agent-setup (Step 0)
- `{PRE_MERGE_HEAD}` = `PI_SETUP_PRE_MERGE` for pi-setup, `AGENT_SETUP_PRE_MERGE` for agent-setup (Step 4)

**After the rollback, re-sync the runtime from the rolled-back repositories:**

```bash
bash "$SYNC"

# Also restore the tracked config mirrors, since sync-pi.sh never touches config files.
for name in settings.json pi-lsp.json pi-fff.json pi-auto-compact.json; do
  src="$PI_SETUP/agent/$name"
  [ -f "$src" ] || continue
  cp "$src" "$RUNTIME/$name" && echo "✅ restored config: $name"
done
echo "✅ runtime restored from the rolled-back repositories"
```
