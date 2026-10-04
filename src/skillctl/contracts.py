"""Public contracts. Design tests from this file, never from implementations.

Paths are pathlib.Path. Expected input/IO failures raise SkillError or a documented
subclass. Source scripts, hooks and dependencies must never be executed.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Mapping


class SkillError(Exception):
    """Expected operation failure suitable for display to the user."""


class InvalidSkill(SkillError):
    """Invalid skill metadata or unsafe contents."""


@dataclass(frozen=True)
class SkillSpec:
    repo: str
    path: str = "."
    ref: str | None = None
    frontmatter: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchedSkill:
    directory: Path
    commit: str


@dataclass(frozen=True)
class SyncResult:
    updated: tuple[str, ...]
    removed: tuple[str, ...]
    errors: Mapping[str, str]


@dataclass(frozen=True)
class ProgressEvent:
    """Read-only observation; counters count processed items, including failures."""

    operation: Literal["sync"]
    phase: Literal[
        "waiting", "checking", "fetching", "rendering", "installing",
        "removing", "done", "failed", "finished",
    ]
    skill: str | None = None
    completed: int = 0
    total: int | None = None


ProgressCallback = Callable[[ProgressEvent], None]

# config.py
# load_config(path: Path) -> dict[str, SkillSpec]
#   Missing file returns {} (sync separately requires an existing config file).
#   Parse TOML [[skills]] array entries with explicit required name and repo.
#   Reject duplicate names and old [skills.<name>] mapping format. Preserve entry
#   order in returned dict. repo is nonempty str; path defaults to '.', ref
#   defaults to None. Reserved repo='local' denotes the in-place skill directory
#   home/skills/<name>; local specs require path='.' and ref=None (no Git source).
#   Only name/repo/path/ref/frontmatter keys accepted per entry, only 'skills' at
#   document root. Empty document or skills=[] is valid as {}. Nonempty skills
#   arrays must contain mappings. Reject missing/invalid name before mutation.
#   Names: lowercase letters/digits separated by single hyphens, <=64 chars.
#   Frontmatter accepts arbitrary TOML keys/values, recursively converted to
#   plain Python values (including nested arrays/maps and date/time types).
#   Invalid TOML/types/names/relative paths raise SkillError. POSIX subpaths;
#   reject absolute paths, '..' components, backslashes and NUL.
# save_config(path: Path, specs: Mapping[str, SkillSpec]) -> None
#   Atomic write readable by load_config, using [[skills]] plus explicit name,
#   and inline frontmatter tables. Empty specs writes skills=[]. Preserve comments
#   on unrelated retained entries and their order; append new entries in input
#   order. Create parents; do not partially truncate on failure.
#   This is a library helper; sync itself never writes config.

# render.py
# render_skill(markdown: str, overrides: Mapping[str, object]) -> str
#   Require YAML frontmatter at beginning (optional BOM), a mapping with valid
#   name as above and nonblank string description <=1024 chars. Reject duplicate
#   keys/malformed YAML. Configured keys replace whole upstream fields (including
#   False, arrays and maps); absent keys inherit. Overrides cannot change the
#   declared name. Validate effective metadata after merge, preserving the body
#   exactly and unrelated fields. TOML time-of-day values become ISO strings in
#   YAML (which has no time scalar); dates/datetimes retain YAML timestamp types.
#   Applying same overrides twice is idempotent. No IO.
# skill_name(markdown: str) -> str
#   Validate as render_skill(markdown, {}), return declared name.

# source.py
# fetch_skill(spec: SkillSpec, workspace: Path) -> FetchedSkill
#   workspace is caller-owned existing empty directory. Fetch ref (branch/tag/
#   commit), or remote HEAD if absent. Accept HTTPS/SSH URLs, SCP-style SSH, and
#   absolute local repo paths. Reject other protocols, option-like URLs/refs and
#   invalid subpaths. Return resolved full commit SHA and directory in workspace
#   with ONLY selected skill subtree (scripts/assets/dotfiles), never .git.
#   Root must have valid SKILL.md. Reject symlinks/submodules in selected subtree,
#   missing paths/refs, invalid metadata. Read Git objects without checkout, so
#   filters cannot run. Caller owns cleanup on success/failure.

# store.py
# tree_hash(directory: Path) -> str
#   Deterministic fingerprint of relative paths, bytes and executable bits.
#   Exclude mtimes, reject symlinks/nonregular nodes. File add/remove/change or
#   executable-bit changes must change hash.
# install_skill(source: Path, target: Path, expected_hash: str | None = None) -> str
#   Copy complete validated skill tree; return tree_hash. No expected_hash:
#   refuse any existing target (including broken links). With expected_hash:
#   require existing target to match; refuse local edits. Reject symlinks,
#   overlapping trees, invalid skills. On caught failure preserve old target;
#   source unchanged. Staging/backup outside target.parent (skill scan).

# gitignore.py
# sync_gitignore(home: Path, local_names: Iterable[str]) -> bool
#   Maintain home/.gitignore atomically; return True iff file content changed.
#   Deduplicate/sort names, validate same skill-name rules; invalid input raises
#   SkillError without writing. Only manage exactly one marker-delimited block:
#     # BEGIN skillctl managed skills
#     !/skills/
#     /skills/*
#     !/skills/<local-name>/   (one per local name, sorted)
#     # END skillctl managed skills
#   The parent exception allows traversal if /skills/ was previously ignored.
#   Child blanket rule keeps downloaded skill dirs/root files ignored; directory
#   exceptions expose local contents but do NOT override generic cache ignores.
#   Preserve all content outside existing block exactly (including comments).
#   If no block, append it, adding a separating newline when needed; create file
#   if missing. Existing block is replaced in place, not relocated. Empty names
#   retains baseline rules but removes stale local exceptions. Repeated call is
#   byte-identical/no-write/False. Reject duplicate, unmatched or reversed marker
#   lines, symlink/nonregular .gitignore, or invalid UTF-8 before any write.
#   Preserve existing file permission bits. IO errors raise SkillError and leave
#   original content unchanged. Never access network or modify skill contents.
#
# manager.py
# default_home() -> Path
#   Expanded absolute SKILLCTL_HOME when set, else ~/.agents; independent of cwd.
# sync(home: Path, *, progress: ProgressCallback | None = None) -> SyncResult
#   The ONLY manager mutation API. No add/update/remove compatibility wrappers.
#   Require existing, regular, nonsymlink config.toml; missing/malformed config
#   or corrupt state raises SkillError before any install/delete. Empty valid
#   config explicitly means no managed skills desired. Never rewrite config.
#   Under cross-process lock, validate/snapshot config and state, then call
#   sync_gitignore(home, names whose repo == 'local') BEFORE skill mutations.
#   Gitignore generation failure is a global SkillError, no skill mutation.
#   The managed block follows desired config even if later item operations fail;
#   it is not rolled back with failed items. Invalid/missing config or invalid
#   state never changes .gitignore. Unmanaged user exceptions are not rewritten.
#   Then create work list:
#     1. all configured names in sorted order (install/update is one operation);
#     2. tracked names absent from config, sorted (removal).
#   Git entries: download fresh, validate configured name equals upstream name, apply
#   overrides EVEN when commit unchanged, install complete content, record state.
#   Local entries (repo='local'): require existing regular directory at
#   home/skills/<name> with valid SKILL.md whose name matches configured name. Do NOT
#   fetch Git or run scripts. Explicit local config may adopt an untracked skill
#   and accepts authored edits since last sync. Preserve all files except applied
#   frontmatter overrides; stage a copy, then replace only if target still matches
#   its just-read hash. Validate tree (no links/special files) before reading.
#   Record local state as {'kind': 'local', 'hash': str} (no invented commit).
#   Missing local directories are errors, not created/downloaded. Local overrides
#   are applied to current file; deleting override leaves current local value
#   unchanged (there is no separate upstream). Successful local entries are also
#   in updated. Local validation/apply failure preserves original local content.
#   For Git: removing override inherits fetched upstream value. Missing tracked
#   target is reinstalled. Existing targets must be tracked and match recorded hash.
#   For removals: delete only previously tracked, unchanged directories; absent
#   target still removes state record. Refuse symlinks/local edits; retain record
#   on refusal so retry is possible. This includes local skills: removal refuses
#   changes made since their last sync. Untracked content is NEVER pruned; only
#   explicit repo='local' permits adoption. No reading target paths
#   from untrusted state; derive home/skills/<name> using validated names.
#   Each item independently commits or rolls back target and state on caught
#   failure. Continue with remaining work (including explicit removals) after
#   item failure. updated/removed contain successful names in work-list order;
#   errors maps failed names to nonempty messages. Successful records survive
#   later failures. Empty work returns empty tuples/map. Existing state schema
#   stays version=1. Git records remain {'commit': str, 'hash': str}; local records
#   are {'kind': 'local', 'hash': str}. Reject other record shapes/kinds. Existing
#   Git records work without migration.
#   No manager stdout/stderr without callback. Crash consistency across multiple
#   files is not promised. Never roll back config: it is read-only input.
#
# Progress events from sync:
#   operation='sync'; first waiting before lock. Total = number of configured
#   entries + tracked removals. For each entry checking then fetching/rendering/
#   installing OR removing as reached. Local entries skip fetching, but emit
#   rendering/installing. done only after commit; failed after a
#   caught item error. done/failed increments completed exactly once and includes
#   new value. Other phases use count of previously finished items. Final finished
#   has completed=total (0/0 allowed). 0 <= completed <= total when known. A global
#   error need not emit failed/finished. Ignore ordinary callback exceptions, not
#   KeyboardInterrupt/SystemExit. Display errors must not change installation.

# progress.py
# ProgressReporter(stream: TextIO | None = None)
#   Context manager/callable for ProgressEvent, default stderr. TTY: spinner,
#   processed-items bar when total known, phase/skill visible, no invented byte
#   percentage. Restore terminal/stop animation on all exits, never suppress body
#   exceptions. Non-TTY: flushed append-only plain event lines, no ANSI controls.
#   Render skill text literally (no markup/terminal controls). Include operation,
#   phase, skill if provided, known counters as N/M. Never print to stdout or
#   leave animation running after exit.

# cli.py
# main(argv: list[str] | None = None) -> int
#   ONLY `sync`, no positional skill names or mutation flags. Root default_home.
#   Reject old add/update/remove commands with argparse SystemExit(2).
#   Use ProgressReporter. stdout: Updated <name> / Removed <name> on success,
#   /reload reminder when >=1 successful item, 'Nothing to sync.' for empty work.
#   stderr: progress and errors, no traceback for SkillError. Return 0 success,
#   1 expected global/per-item failure. argparse may raise SystemExit(2) for usage.
