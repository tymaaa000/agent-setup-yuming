---
name: iterate
description: 自我迭代闭环——跑用量度量、对比基线(delta)、给出"你 + pi 各自下一步该改什么"，并把本轮存为新基线。当用户想自我改进、让 pi 更高效、或"这轮做得好不好/怎么变更好"时使用。
---

# 自我迭代闭环（iterate）

让「你」和「pi」每次跑一轮，都能对比"上一轮 vs 这一轮"，并得到明确的改进动作。

## 运行（三步闭环）

```bash
D=skills/u/metrics/scripts/metrics.py   # 相对本技能目录

# 1) 当前报告 + delta(对比基线) + 推荐
python3 "$D"

# 2) 把本轮数字存为新基线（下次就能对比")
python3 "$D" --save-baseline
```

## 闭环五步（每个 /iterate 都走一遍）

1. **度量**：`metrics.py` 给出 模型/工作模式/工具/每日趋势 的数字。
2. **基线**：读 `metrics-baseline.json` → 算 delta（↑↓）。首轮基线=当前，delta 为 `=`。
3. **诊断**：读「推荐下一步」，每个推荐标了 `[你]` 或 `[pi]`。
4. **调整**：
   - `[你]` → 告诉你该换什么模型 / 降 thinking / 精简 prompt / 平衡工作。
   - `[pi]` → 告诉你该精简输出 / 保持上下文复用 / 调 thinking 档位。
   - **可安全固化**：把一个明确的最佳实践补进 `AGENTS.md` 的「Usage Self-Optimization」段（先给用户确认，不自动改）。
5. **验证**：下次 `/iterate` 看 delta 是否朝好的方向变（avg/轮↓、推理占比↓、缓存占比↑/稳定）。

## 与用户沟通

- 把 delta 方向讲清楚（变好/变坏）。
- 把 `[你]` 的动作作为**可执行建议**，问用户是否采纳（如"要不要我把 review agent 的 thinking 从 high 降为 medium"）。
- `[pi]` 的动作提示 pi 自己改进（下次会话、回复更精简）。

## 说明
- **只读 session**，不修改任何会话/配置；唯一可选写操作是 `--save-baseline`（存数字）。
- `metrics-baseline.json` 是运行时数据（不进 git），用于跨轮对比。
- 与 `/metrics` 区别：`/metrics` 看"现状"，`/iterate` 看"现状 + 与上次对比 + 下一步动作"。
