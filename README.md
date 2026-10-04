# Agent Skills — skillctl

一个配置文件，一个命令。使用 `uv` 管理项目，通过 Git 获取完整 skill，并在每次同步时重新应用本地 frontmatter 设置。

## 使用

需要 Python 3.11+、Git 和 uv；支持 Linux/macOS。

```bash
cd ~/.agents
uv sync --locked
uv run skillctl sync
```

可选：安装到用户命令目录，在任意工作目录使用：

```bash
uv tool install --editable ~/.agents
skillctl sync
```

根目录默认 `~/.agents`，不依赖当前工作目录；可通过 `SKILLCTL_HOME` 指定独立目录。

## config.toml 是唯一配置入口

```toml
[[skills]]
name = "pdf"
repo = "https://github.com/acme/skills.git"
path = "skills/pdf"  # 省略时是仓库根目录
ref = "main"        # 可省略，默认远端 HEAD；也支持 tag / commit
frontmatter = { disable-model-invocation = true, category = "documents", priority = 2 }
```

编辑配置，然后运行 `skillctl sync`：

| 配置变化 | 同步结果 |
|---|---|
| 新增条目 | 下载并安装 |
| 保留条目 | 重新获取上游并应用配置，下载与更新是同一个操作 |
| 修改字段设置 | 即使上游 commit 未变，也重新应用 |
| 删除条目 | 删除该工具此前管理的对应 skill 及安装记录 |

每个 `[[skills]]` 条目必须有唯一的 `name`，并与对应 `SKILL.md` 的 `name` 相同，例如 `math-modeling`。重复名称、缺失名称或旧的 `[skills.<name>]` 格式会报错，不执行同步。来源支持 HTTPS、SSH URL、SCP 风格 SSH 地址和绝对本地 Git 仓库路径。

`frontmatter` 支持任意 TOML 键和值（字符串、数字、布尔值、数组、嵌套表及日期/时间）。配置中的键会整体替换 `SKILL.md` 对应的 YAML 字段（嵌套表不作深度合并），未配置的键保留上游值。例如 `disable-model-invocation = true` 禁止自动选择，`false` 显式允许；删除覆盖键则继承上游值。TOML 的纯时间值在 YAML 中写为 ISO 格式字符串；日期和日期时间保留为 YAML 日期/时间戳。覆盖不能改变 skill 的 `name`，合并后的 `name` 和 `description` 仍须有效。

字段设置仅通过配置文件修改，不直接编辑远程 skill 的安装副本。同步后在 Pi 执行 `/reload`。`disable-model-invocation` 不是文件访问权限控制。

## 自建 skill

自建内容直接保存在 `skills/<name>/`，也必须在配置中声明：

```toml
[[skills]]
name = "comfyui-imagegen"
repo = "local"
```

`repo = "local"` 不访问 Git，不接受 `path`（默认 `.` 除外）或 `ref`。同步检查本地目录和名称，保留自己编辑的脚本、资源和正文，并应用可选的 `frontmatter` 设置；目录不存在时报告错误，不创建空 skill。

自建 skill 没有独立的上游副本，删除字段覆盖后保留文件中的当前值；若要改为 `false`，显式设置即可。删除整个配置项会删除此前纳入管理的本地 skill；若它在上次同步后又被编辑，则拒绝删除并保留记录。

## 同步与删除边界

- **配置缺失或损坏时直接报错，不安装、不删除。**
- 空列表 `skills = []` 表示移除全部已管理 skill。有效空文件也具有同样含义。
- 只删除 `.state/installed.json` 记录的受管理目录；未管理的目录和无关文件不受影响。
- 远程安装内容有本地修改时拒绝覆盖；删除任何 skill 时都检查是否有上次同步后的修改。拒绝符号链接。失败项目保留记录，先备份并处理修改后再同步。
- `repo = "local"` 是显式纳管声明，允许接管对应的现有目录，正常同步接受本地创作修改。
- 每项独立提交；某项失败后继续其他项目，包括配置明确删除的项目，最后返回非零退出码。
- 配置只读，绝不由同步操作重写。安装记录保留原有格式，无需迁移。

终端会显示旋转指示器、当前 skill、处理阶段及 `已处理/总数` 进度条；总数包含下载/更新和删除，计数包括失败项目。Git 获取期间不虚构下载百分比。进度写入 stderr；管道或重定向环境自动改为普通逐行日志。

## 目录

```text
~/.agents/
├── skills/                  # Pi 直接读取的安装内容
│   └── comfyui-imagegen/    # repo="local"，随 Git 保存
├── src/skillctl/            # 实现与公开接口契约
├── tests/                  # 按契约独立设计的黑盒测试
├── config.toml             # 来源与本地字段设置
├── pyproject.toml
├── uv.lock
└── .state/                 # 本机安装记录、锁、暂存内容，不提交
```

远程 skill 不入库。自建 skill 直接放在 `skills/`，通过 `repo = "local"` 写入配置即可。每次 `sync` 会自动维护 `.gitignore` 的专用区块，为所有本地条目生成取消忽略规则，无需手动添加例外：

```gitignore
# BEGIN skillctl managed skills
!/skills/
/skills/*
!/skills/comfyui-imagegen/
# END skillctl managed skills
```

本地配置删除或改为 Git 来源后，对应自动例外会移除；区块外的手写规则保持不变，缓存目录仍按原规则忽略。规则来自当前配置，即使之后某个 skill 同步失败也不会回滚。配置或安装记录无效、`.gitignore` 为符号链接或专用标记损坏时，先报错，不修改 skill。

取消忽略不等于执行 `git add`；提交哪些文件仍由你决定。已经被 Git 跟踪的文件不受 `.gitignore` 影响。

新设备：

```bash
git clone git@github.com:aqua2k1/agent-setup.git ~/.agents
cd ~/.agents
uv sync --locked
uv run skillctl sync
```

## 安全与验证

不执行仓库脚本、依赖安装、hooks 或 checkout filters，直接读取 Git 对象。拒绝路径越界、符号链接、submodule；限制文件数、文件大小和目录深度。跨进程操作串行化，普通写入错误回滚当前项；第一版不承诺断电时的多文件事务一致性。

```bash
uv run pytest
uv build
```

测试仅根据 `src/skillctl/contracts.py` 的公开签名与行为约定设计，不读取函数实现。使用临时目录和本地 Git 仓库，不操作真实安装内容。

仓库为公开仓库，提交前检查配置地址和自建 skill 是否含敏感信息。
