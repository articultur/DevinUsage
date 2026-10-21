# Devin Quota & Usage Plugin (`devin-usage`)

符合官方规范的 **Devin 原生插件 (`.devin-plugin`)**，适用于 **Devin Desktop** 与 **Devin CLI**。无需修改任何应用内部文件，即可实时查看账号周/日配额剩余百分比、重置倒计时、当前会话上下文窗口大小以及今日各模型 Token 消耗明细。

## 核心功能

1. **实时配额查询 (`SeatManagementService/GetUserStatus`)**
   - 直接请求实时接口获取 **周额度 (Weekly Quota)** 与 **日额度 (Daily Quota)** 剩余百分比、可视化进度条、重置倒计时、ACU / Extra Usage 余额，并在离线时自动回退至本地缓存。
2. **当前会话与今日全量 Token 统计 (`sessions.db`)**
   - 实时统计当前活跃会话的 Context Window Token 占用、模型名称、最近生成速度 (`tok/s`)。
   - 按模型汇总今日所有活跃会话的请求轮数、新输入 Tokens、输出 Tokens 与缓存命中 Tokens。
3. **三大原生扩展组件**
   - **MCP Server (`devin-usage`)**：提供 `get_quota_usage` 工具，遵循 JSON-RPC 2.0 / MCP 协议，毫秒级返回 Markdown 面板或结构化 JSON。
   - **Skill (`/devin-usage:quota`)**：通过斜杠命令一键输出完整配额与 Token 消耗表格。
   - **Lifecycle Hooks (`SessionStart` / `UserPromptSubmit`)**：
     - 新会话启动时自动向 Agent 注入当前剩余配额概要；
     - 当用户在对话中询问“查看额度 / 还剩多少额度”时自动注入实时面板；
     - 当周额度剩余 `≤ 20%` 时自动发出低额度预警。

## 前置要求

- **`devin` CLI**：本说明按版本 `3000.11.92` 验证。
- **`python3`**：已在 Python 3.9.6 与 3.15 上验证；无任何第三方 pip 依赖。
- **已登录的 Devin 账号**：先运行 `devin auth status` 检查；若显示未登录，请先 `devin auth login`；若已登录，无需登出或重新认证。
- 插件安装完成后，需**开启一个新会话**才会加载插件的 Skill / Hooks / MCP Server。

## 安装方式

### 1. 从本地目录安装（推荐，本次验收路径）

在本仓库根目录执行：

```bash
devin plugins install --local . -y
devin plugins info devin-usage     # 应列出 skill / 2 个 hooks / devin-usage MCP
devin mcp get devin-usage          # Source 应为 "plugin <本仓库路径>"
```

随后**开启新会话**，输入 `/devin-usage:quota` 即可查看配额面板。

> `--local` 表示仅安装到当前机器；它是链接式安装，本仓库的后续编辑无需 `devin plugins update`，新会话即可生效。

### 2. 从 GitHub 安装（发布源选项）

```bash
devin plugins install --local articultur/DevinUsage -y
```

> 本次端到端验收使用本地检出；GitHub 直接安装命令未在该次验收中执行。省略 `--local` 会按官方默认行为把插件记录到个人云端清单并在各设备同步，如只需本机使用请保留 `--local`。

### 3. 可选：注册全局短命令 `/quota`

如果希望在任何会话中直接输入 `/quota`（无需输入插件前缀 `/devin-usage:quota`）：

```bash
mkdir -p ~/.config/devin/skills/quota
cp skills/quota/SKILL.md ~/.config/devin/skills/quota/SKILL.md
```

> 复制前请先检查 `~/.config/devin/skills/quota/SKILL.md` 是否已存在及内容是否相关，**不要直接覆盖可能属于其他用途的同名文件**；确认无误再执行拷贝。

## 使用示例

- **在对话中使用斜杠命令**：输入 `/devin-usage:quota`（或全局短命令 `/quota`）
- **在对话中直接提问**：输入 `查看额度` 或 `还剩多少额度`
- **在终端直接运行脚本**：
  ```bash
  python3 scripts/usage_query.py --format markdown
  python3 scripts/usage_query.py --format brief
  python3 scripts/usage_query.py --format json
  ```

## 目录结构

```text
DevinUsage/
├── .devin-plugin/
│   ├── plugin.json          # Devin 插件清单（显式声明 mcpServers，exclusive）
│   └── mcp.json             # MCP Server 声明（使用 ${CLAUDE_PLUGIN_ROOT}）
├── hooks.json               # SessionStart 与 UserPromptSubmit 生命周期钩子
├── scripts/
│   ├── usage_query.py       # 配额与本地会话 SQLite 统计核心引擎
│   ├── mcp_server.py        # 标准 stdio MCP Server 实现
│   └── hook_runner.py       # 生命周期 Hook 处理脚本
└── skills/
    └── quota/
        └── SKILL.md         # /devin-usage:quota 技能定义
```

> **为何 `mcp.json` 不在仓库根目录？** 根目录的 `.mcp.json` 会被当作“项目级 MCP 配置”自动加载，与插件级加载冲突并遮蔽它；项目级上下文不存在 `${CLAUDE_PLUGIN_ROOT}`，会被展开为空字符串，导致 MCP 尝试启动 `python3 /scripts/mcp_server.py` 而连接失败。因此 MCP 声明放在 `.devin-plugin/mcp.json`，并在 `plugin.json` 中通过 `mcpServers.paths` 显式指向它（`exclusive: true`），保证始终按“插件根目录”解释该变量。

## 故障排查

- **`devin mcp get devin-usage` 应显示 `Source: plugin <仓库路径>`**。若显示为某个 `.mcp.json` 文件路径，说明存在残留的项目级 `.mcp.json` 正在遮蔽插件定义，请删除或移出仓库根目录后重启会话。
- 在 Agent shell / 某些集成终端中，环境变量 `ACP_BACKEND` 可能已设置并影响本地 `devin` CLI 的命令路由；此时请在前面加 `env -u ACP_BACKEND`，例如：
  ```bash
  env -u ACP_BACKEND devin mcp get devin-usage
  ```
- 修改本仓库文件后无需 `devin plugins update`（本地安装为链接模式），但需**开启新会话**生效。
- 在 Devin Desktop 的 **Customize → Plugins → Refresh installed** 只会刷新插件元数据（技能/清单/MCP 声明列表）；**已经在运行的 Agent 会话仍沿用旧快照**，通常需要开启新会话才会真正启动插件 MCP Server。若不想重启当前会话，可在该工作区内放置一个**不入库的本地覆盖** `.devin/mcp_config.local.json`，并将 `/.devin/mcp_config.local.json` 加入本仓库的 `.git/info/exclude` 避免误提交，然后用绝对路径直接声明 server：
  ```json
  {"mcpServers": {"devin-usage": {"command": "python3",
      "args": ["/绝对路径/DevinUsage/scripts/mcp_server.py"]}}}
  ```
  宿主会监听 `.devin` 配置变更并自动接入；`devin mcp get devin-usage` 此时在该工作区显示 `Source: .devin/mcp_config.local.json`。此文件仅是当前机器的兼容引导，插件本身（`.devin-plugin/mcp.json` + `${CLAUDE_PLUGIN_ROOT}`）仍是跨工作区的规范安装方式，其他目录下的会话不受影响。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

其中 CLI 集成测试（`devin mcp get` 发现路径断言）需要先安装 `devin` CLI，并已将**本检出**通过 `devin plugins install --local . -y` 本地安装；其余协议与布局测试无外部依赖。

## 验收说明

本仓库当前工作树已通过一次安装到使用的端到端验收：在隔离的登录配置（独立 HOME/XDG）、**路径含空格**的插件检出与无关工作区中，真实 `devin` CLI 完成了 `plugins install --local`、插件/技能/Hooks/MCP 注册，并在新会话中原生调用了 `/devin-usage:quota`，全程未使用任何 `.devin` 覆盖或全局 MCP 绑定。详细证据见 [INSTALLATION_ACCEPTANCE.md](./INSTALLATION_ACCEPTANCE.md)。

## License

MIT
