---
name: cleanup
description: 清理 pi runtime 的临时/旧数据——删除超过 N 天的旧会话、截断崩溃日志，默认 dry-run 需确认后才执行。当用户觉得 pi 目录臃肿、想清 session/日志、或定期维护时使用。
---

# pi runtime 清理（cleanup）

清理 pi 运行时目录里的**可再生物**：旧会话（session）、崩溃日志。**默认 dry-run（只列出不删）**，确认后才真正删除。

## 运行

```bash
# 1) 先看有什么（dry-run，默认 30 天）
bash "$(dirname "$0")/scripts/cleanup.sh" --age 30

# 2) 调整年龄阈值看更多
bash scripts/cleanup.sh --age 7

# 3) 确认无误后真正清理（删旧会话 + 截断崩溃日志）
bash scripts/cleanup.sh --age 30 --apply
```

## 安全原则（重要）

1. **默认 dry-run**：不 `--apply` 绝不删除。
2. **不删最近会话**：脚本会跳过最新一个 `.jsonl`（保护当前活动会话）。
3. **只删旧会话 + 截断日志**：不碰 extensions/skills/settings 等配置。
4. **路径守卫**：脚本只操作 sessions 目录和 pi-crash.log，且做了路径检测。

## 与 metrics 配合

- 先用 `/metrics` 看数据 → 再用 `/cleanup` 清掉不再需要的旧会话。
- 建议定期（如每月）跑一次 dry-run，空间紧张时再 `--apply`。

## 说明
- 此技能只清**旧 session 和日志**。大的 `git/`、`npm/` 历史膨胀需另处理（见 repo README 的浅克隆建议）。
