---
name: cleanup
description: Clean temporary and old pi runtime data — delete sessions older than N days and truncate the crash log. Dry-run by default; nothing is deleted without confirmation. Use when the pi directory feels bloated, when sessions or logs need clearing, or for routine maintenance.
---

# pi runtime cleanup

Clean the **regenerable** material in the pi runtime directory: old sessions and the crash log. **Dry-run by default** — nothing is deleted until you confirm.

## Run

```bash
# 1) See what is there (dry-run, default 30 days)
bash "$(dirname "$0")/scripts/cleanup.sh" --age 30

# 2) Try a different age threshold
bash scripts/cleanup.sh --age 7

# 3) Apply the cleanup (delete old sessions + truncate the crash log)
bash scripts/cleanup.sh --age 30 --apply
```

## Safety principles (important)

1. **Dry-run by default**: without `--apply` nothing is deleted.
2. **Never delete the newest session**: the script skips the most recent `.jsonl` to protect the active session.
3. **Only old sessions and logs**: extensions, skills, and settings are never touched.
4. **Path guards**: the script only operates on the sessions directory and `pi-crash.log`.

## With metrics

- Run `/metrics` first to see the data, then `/cleanup` to remove sessions you no longer need.
- A monthly dry-run is a good habit; add `--apply` when space is tight.

## Notes
- This skill only clears **old sessions and logs**. Large `git/` or `npm/` histories need separate handling.
