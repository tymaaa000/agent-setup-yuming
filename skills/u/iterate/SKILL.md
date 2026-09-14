---
name: iterate
description: Self-iteration loop — run the usage metrics, compare against the baseline (delta), state what you and pi should change next, and store this run as the new baseline. Use when the user wants to improve, make pi more efficient, or ask "was this round good, and how do we make it better".
---

# Self-iteration loop (iterate)

Each round, compare "last round vs this round" and end with concrete improvement actions for both you and pi.

## Run (three-step loop)

```bash
D=skills/u/metrics/scripts/metrics.py   # relative to this skill directory

# 1) Current report + delta (vs baseline) + recommendations
python3 "$D"

# 2) Store this round as the new baseline (for the next comparison)
python3 "$D" --save-baseline
```

## The five steps of every /iterate

1. **Measure**: `metrics.py` prints numbers for models, work patterns, tools, and daily trends.
2. **Baseline**: read `metrics-baseline.json` → compute the delta (up/down). The first run becomes the baseline, so the delta is `=`.
3. **Diagnose**: read the recommendations; each one is tagged `[you]` or `[pi]`.
4. **Adjust**:
   - `[you]` → which model to switch to, when to lower thinking, how to trim prompts, how to rebalance work.
   - `[pi]` → keep output tight, preserve context reuse, adjust the thinking level.
   - **Safe to persist**: add one clear best practice to the "Usage Self-Optimization" section of `AGENTS.md` (ask the user first; never edit it automatically).
5. **Verify**: next `/iterate`, check whether the delta moved in a good direction (avg tokens/turn down, reasoning share down, cache-read share up or stable).

## Communicating with the user

- State the delta direction clearly (better or worse).
- Present `[you]` actions as **executable suggestions** and ask whether to adopt them (for example: "should I lower the review agent's thinking from high to medium?").
- `[pi]` actions are reminders for pi itself (tighter replies next session).

## Notes
- **Read-only over sessions**; no session or configuration is modified. The only optional write is `--save-baseline` (numbers only).
- `metrics-baseline.json` is runtime data (not in git) used for cross-round comparison.
- Difference from `/metrics`: `/metrics` shows the current state; `/iterate` shows the current state plus the delta and the next actions.
