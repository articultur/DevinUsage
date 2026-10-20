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

## 安装方式

### 1. 从 GitHub 直接安装（推荐）

```bash
devin plugins install articultur/DevinUsage -y
```

### 2. 从本地目录安装（开发调试）

```bash
git clone https://github.com/articultur/DevinUsage.git
cd DevinUsage
devin plugins install --local . -y
```

### 3. 可选：注册全局短命令 `/quota`

如果希望在任何会话中直接输入 `/quota`（无需输入插件前缀 `/devin-usage:quota`）：

```bash
mkdir -p ~/.config/devin/skills/quota
cp skills/quota/SKILL.md ~/.config/devin/skills/quota/SKILL.md
```

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
│   └── plugin.json          # Devin 插件清单
├── .mcp.json                # MCP Server 声明 (使用 ${CLAUDE_PLUGIN_ROOT})
├── hooks.json               # SessionStart 与 UserPromptSubmit 生命周期钩子
├── scripts/
│   ├── usage_query.py       # 配额与本地会话 SQLite 统计核心引擎
│   ├── mcp_server.py        # 标准 stdio MCP Server 实现
│   └── hook_runner.py       # 生命周期 Hook 处理脚本
└── skills/
    └── quota/
        └── SKILL.md         # /devin-usage:quota 技能定义
```

## License

MIT
