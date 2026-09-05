# agent-setup

> pi 的**技能（SKILL.md）仓库**，与 pi 配置（pi-setup）解耦。
> 当前采用**本地文件**存储技能（非 skill-lock 远程锁定模式）。

## 结构

```
agent-setup/
└── skills/
    ├── u/ (8)      # 用户/涉及模型的技能（invocation 手动触发）
    │   ├── caveman/          # 极简 token 节省模式
    │   ├── grill-me/         # 纯盘问
    │   ├── grill-with-docs/  # 盘问 + 领域建模 + 写文档
    │   ├── implement/        # 读 ticket → /tdd → /code-review → commit
    │   ├── paper-dl/         # （运行时本地独有，未纳入 git）论文搜索下载
    │   ├── setup-update/     # 上游更新检查/合并/推送
    │   ├── teach/            # 多会话教学
    │   ├── to-spec/          # 对话 → spec.md
    │   └── to-tickets/       # spec → issues/*.md
    │
    └── m/ (7)      # 方法论/自动触发（model 可 auto-invoke）
        ├── code-review/      # 双轴并行审查
        ├── codebase-design/  # 深度模块设计词汇
        ├── diagnosing-bugs/  # 6 阶段调试纪律
        ├── domain-modeling/  # 术语表 + ADR 维护
        ├── grilling/         # 盘问循环原语
        ├── prototype/        # 一次性原型（逻辑/UI）
        └── tdd/              # 红-绿-重构循环
```

> `paper-dl` 目前是运行时本地新增、未纳入本仓库 git —— 如需跨机同步应补进 `skills/u/`。

## 说明

- `u/` 与 `m/` 的差异：`m/` 属通用方法论、可被模型自动触发；`u/` 属用户流程、需显式调用。
- 与本仓库相关的 `setup-update` 技能，使用 `npx skills` 之前是本地 `SKILL.md`，目前仍保留本地。

## 安装

```bash
git clone git@github.com:tymaaa000/agent-setup-yuming.git ~/.agent
```

## 与上游差异

ai 上游（aqua2k1）已迁移到 **skill-lock 远程锁定**（只存 `.skill-lock.json`，用 `npx skills`
从远端安装）。本仓库目前保留**本地文件存储**，以兼容自有技能（如 `setup-update`）。
