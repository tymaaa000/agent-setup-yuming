---
name: metrics
description: Quantify pi usage — aggregate tokens and cost by model/project/time and report "how you use pi" plus "where pi can improve". Use when the user asks about usage, cost, model choice, or how to spend fewer tokens and work more efficiently.
---

# pi usage metrics

Run the scripts in this skill directory to generate a usage report for your pi sessions.

## Run

```bash
python3 "$(dirname "$0")/scripts/metrics.py" 2>/dev/null || python3 scripts/metrics.py
# When the pi config directory is not in the default location:
# PI_SESSIONS=/path/to/agent/sessions python3 scripts/metrics.py
```

## Reading the report (two questions)

### 1) How you use pi
- **By model**: turns and input / output / reasoning / cache-read tokens. Shows the workhorse model.
- **By project**: which directories consume the most → where your effort goes.
- **Active dates**: usage frequency → daily driver or occasional use, and which days are busiest.
- **Model switches**: frequent switching means experimentation or varied task types.

### Tools / extensions / subagents (what the work looks like)
- **Top tools**: `bash` heavy = hands-on debugging; `read/edit/write` = code and file changes; `WebSearch` = research; `subagent`/`get_subagent_result` = parallel delegation; `chrome_devtools_*` = browser/desktop automation.
- **Extensions**: extension-provided tools appear under their own names, so extension use is measurable.
- **Work patterns**: project directory plus tool mix identifies the work type. For example `Linux-Work-debug` with `bash/edit` = driver/debug; a paper project with `WebSearch/write` = writing/research.
- **Skills**: counted only when a `<skill name="X">` tag appears (sparse) — it means the skill entered the conversation.

### Work-pattern classification (where effort goes)
- The script classifies sessions by project directory name plus tool mix (paper/research, driver/debug, PPT, web automation, pi config, …).
- The report shows each work type's share of tokens, turns, and sessions.
- Use it to see where pi is actually spent and to refocus on high-value work.

### 2) Where pi can improve
- **Top consumer**: if one model dominates the tokens but you already retired it or it expired → switch models.
- **Reasoning share**: high → that scenario may be overthinking; lower the `thinking` level to save tokens.
- **Cache-read share**: high → good context reuse and lower cost (a good signal).
- **Input/output ratio**: output far larger than input → replies are verbose; ask for tighter instructions.

## Advice to give the user
- Report the top model and the top consumer so the user knows the workhorse and whether to renew or switch.
- Turn reasoning share and output ratio into **actionable advice**: which thinking level to use, whether to trim prompts.
- Let the user see where pi is used and whether it is used well; let pi know where to optimize (fewer tokens, lower thinking, tighter output).

## Notes
- Read-only over session files; nothing is modified.
- The cost field may be unset (often 0); rely on tokens then.

## Baseline and self-iteration

- `metrics.py` prints the **current** report plus `Delta` (against the last baseline) and `Recommendations`.
- `metrics.py --save-baseline` stores this run in `metrics-baseline.json` (runtime data, not git) for the next comparison.
- Pair it with the [`../iterate`](../iterate) skill: run metrics → save the baseline → get the next actions for you and for pi.
