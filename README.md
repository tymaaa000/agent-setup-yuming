# agent-setup

> The **skills (SKILL.md) repository** for pi, kept separate from the engine configuration
> in [pi-setup](../pi-setup). Skills are stored as **local files** here rather than pulled
> from a remote skill lock.

## Structure

```
agent-setup/
└── skills/
    ├── u/ (11)     # user workflows — explicit invocation
    │   ├── caveman/          # ultra-compressed token-saving mode
    │   ├── cleanup/          # old sessions + crash log cleanup (dry-run first)
    │   ├── grill-me/         # pure grilling loop
    │   ├── grill-with-docs/  # grilling + domain modeling + docs
    │   ├── implement/        # read ticket → /tdd → /code-review → commit
    │   ├── iterate/          # metrics baseline + delta + next actions
    │   ├── metrics/          # usage report (tokens/cost by model, project, time)
    │   ├── setup-update/     # upstream update review / merge / push
    │   ├── teach/            # multi-session teaching
    │   ├── to-spec/          # conversation → spec.md
    │   └── to-tickets/       # spec → issues/*.md
    │
    └── m/ (7)      # methodology — model may auto-invoke
        ├── code-review/      # two-axis parallel review
        ├── codebase-design/  # deep-module design vocabulary
        ├── diagnosing-bugs/  # six-phase debugging discipline
        ├── domain-modeling/  # glossary + ADR maintenance
        ├── grilling/         # grilling-loop primitive
        ├── prototype/        # throwaway prototypes (logic / UI)
        └── tdd/              # red-green-refactor loop
```

## How the skills reach pi

This repository is the source of truth; `/home/tym/pi/agent/skills` is the runtime copy.

```bash
bash ~/pi/bin/sync-pi.sh          # repo → runtime (rsync --delete)
bash ~/pi/bin/sync-pi.sh --check  # read-only drift check
bash ~/pi/bin/capture-pi.sh       # runtime → repo when you edited the live copy
```

A new skill added only to the runtime copy is deleted by the next sync, so add it here first.

## Notes

- `u/` vs `m/`: `m/` holds general methodology the model may invoke automatically; `u/` holds
  user workflows that require an explicit call.
- Scripts under `u/metrics` and `u/cleanup` are read-only except for their documented writes
  (`--save-baseline`, `--apply`).
- The `setup-update` skill depends on the layout described in [pi-setup](../pi-setup) and
  delegates syncing to `~/pi/bin/sync-pi.sh`.

## Relationship to upstream

The aqua2k1 upstream moved to **remote skill locking** (only a `.skill-lock.json` is stored and
`npx skills` installs from the registry). This repository keeps **local skill files** so that
machine-specific skills such as `setup-update` stay versioned here.
