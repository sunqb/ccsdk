# Agent 插件架构规格说明

## 1. 背景

当前 CC Agent SDK 服务以 FastAPI + Claude Agent SDK 为核心，RAG 能力已较完整（上传、解析、索引、问答、Skills 编排）。但启动与挂载逻辑长期散落在 `main.py` 中：

```
main.py lifespan
  ├── init_rag_db / set_mysql_store_for_ingestion
  ├── embedding_health_check
  ├── close_rag_db（shutdown）
  └── app.include_router(rag_router)  # 条件挂载
```

问题：

- **启动职责混杂**：核心应用与 RAG 初始化耦合在同一文件，新增能力（如计费、外部知识库）会继续膨胀 `main.py`。
- **路由挂载分散**：`rag_enabled` 判断、router import 与核心路由并列，缺少统一扩展点。
- **清理任务无归属**：`cleanup_expired_file_sets` 等后台任务没有插件级注册机制。
- **工具消费路径分裂**：Claude Agent SDK MCP 循环与裸 `tool_use` 循环并存，但缺少协议中立的工具声明层。

本规格说明引入 **Agent Plugin** 机制：用最小契约把「启停、路由、工具、清理」收口到插件，同时 **不改动** `RagAgentRunner` 现有 SSE / MCP 问答链路。

## 2. 目标与非目标

### 2.1 目标

| 目标 | 说明 |
|------|------|
| 最小 `AgentPlugin` 契约 | 所有钩子默认空实现；最小插件只需提供 `name` |
| 协议中立 `ToolSpec` | 插件声明一次工具，MCP 与 `tool_use` 两条路径均可消费 |
| `RagPlugin` 薄适配 | 把现有 RAG 启停、路由、清理迁入插件，**不修改** `app/services/rag` 内部 |
| `PluginRegistry` 统一编排 | 核心代码只感知 registry，不直接 import 各业务能力 |
| `main.py` 单文件可读 | 保留「打开 main.py 即见全貌」；**不拆** `bootstrap.py` |
| 钩子失败可降级 | registry 层 `try/except` + 日志，单个插件失败不拖垮服务 |

### 2.2 非目标

| 非目标 | 说明 |
|--------|------|
| 重构 `RagAgentRunner` SSE | `/agent-sdk/rag/stream` 仍走 `stream_claude_sdk` + `create_rag_mcp_server` |
| RAG 走 `get_tools` | **最终决策**：RAG 保持现有 MCP 路径，`RagPlugin` **不实现** `get_tools` |
| 改动 `app/services/rag/mcp.py` | RAG MCP 工具定义与 request-scoped 上下文逻辑保持原样 |
| 拆分 `bootstrap.py` | 启动流程留在 `main.py`，通过 `plugin_registry` 委托 |
| 通用 Agent 端点立即接入插件工具 | Phase 1 仅落地契约与 RAG 适配；通用消费在 Phase 2 |
| 插件热加载 / 动态发现 | 编译期 `register()`，不做运行时扫描 |

## 3. 总体架构

```text
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│  lifespan: plugin_registry.startup_all / shutdown_all            │
│  mount:    核心 routers + plugin_registry.mount_routers          │
│  /config:  plugin_registry.list_plugin_status()                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PluginRegistry                                │
│  register / startup_all / shutdown_all / mount_routers           │
│  collect_mcp_servers / collect_anthropic_tools                   │
│  collect_prompt_fragments / collect_cleanup_tasks                │
└────────────┬───────────────────────────────┬────────────────────┘
             │                               │
    ┌────────▼────────┐            ┌─────────▼─────────┐
    │   RagPlugin     │            │  未来插件（Phase 2+） │
    │  on_startup     │            │  EchoPlugin / ...   │
    │  get_routers    │            │  get_tools          │
    │  cleanup_tasks  │            │  build_mcp_server   │
    │  (无 get_tools) │            └─────────┬─────────┘
    └────────┬────────┘                      │
             │                               │
             ▼                               ▼
┌────────────────────────┐      ┌───────────────────────────────┐
│ app/services/rag/*     │      │ tooling.py                     │
│ routers/rag.py         │      │ as_sdk_mcp_server              │
│ RagAgentRunner (不变)  │      │ as_anthropic_tools             │
│ mcp.py (不变)          │      │ ToolDispatcher                 │
└────────────────────────┘      └───────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────────┐
│ 问答路径 A（RAG，不变）                                          │
│ POST /agent-sdk/rag/stream                                      │
│   → RagAgentRunner.stream_claude_sdk                            │
│   → mcp_servers={"rag": create_rag_mcp_server(ctx)}             │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ 问答路径 B（通用插件工具，Phase 2+）                              │
│ POST /agent-sdk/stream（扩展）                                   │
│   → plugin_registry.collect_mcp_servers(ctx)                    │
│   或 collect_anthropic_tools(ctx) → ToolDispatcher              │
└────────────────────────────────────────────────────────────────┘
```

模块布局：

```text
app/
├── main.py                 # 单文件启动入口
├── plugins/
│   ├── __init__.py         # 注册内置插件（RagPlugin）
│   ├── base.py             # AgentPlugin 契约
│   ├── tooling.py          # ToolSpec 桥接
│   ├── registry.py         # PluginRegistry
│   └── rag_plugin.py       # RAG 薄适配
├── routers/                # 核心路由 + rag router（由插件挂载）
└── services/
    ├── agent.py            # Claude Agent SDK 封装
    └── rag/                # RAG 内部实现（本规格不改动）
```

## 4. 插件契约

定义于 `app/plugins/base.py`。

### 4.1 PluginContext

请求级上下文，由核心在调用插件钩子前统一构建：

```python
@dataclass
class PluginContext:
    request_id: str
    conversation_id: str | None = None
    space_id: str | None = None
    tenant_id: str | None = None
    owner_id: str | None = None
    api_key_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
```

说明：

- `request_id`：链路追踪主键，必填。
- `tenant_id` / `owner_id` / `api_key_id`：为多租户、审计预留，Phase 1 可为空。
- `extras`：插件私有扩展字段，避免频繁改契约。

### 4.2 CleanupTask

插件注册的清理任务，由 `/admin/cleanup` 或外部 cron 统一触发：

```python
@dataclass
class CleanupTask:
    name: str
    run: Callable[[], Awaitable[int]]  # 返回清理条数
```

### 4.3 ToolSpec

协议中立的工具声明：

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]   # JSON Schema
    handler: Callable[[dict[str, Any]], Awaitable[Any]]
```

插件通过 `get_tools(ctx)` 返回 `list[ToolSpec]`；registry 负责桥接到 MCP 或 Anthropic `tool_use` 形态。**RagPlugin 不使用此路径**（见第 7 节）。

### 4.4 AgentPlugin

```python
class AgentPlugin:
    name: str = "unnamed"

    def is_enabled(self) -> bool: ...
    async def on_startup(self, app: FastAPI) -> None: ...
    async def on_shutdown(self) -> None: ...
    def get_routers(self) -> list[APIRouter]: ...
    def get_tools(self, ctx: PluginContext) -> list[ToolSpec]: ...
    def build_mcp_server(self, ctx: PluginContext) -> Any | None: ...
    def system_prompt_fragment(self, ctx: PluginContext) -> str | None: ...
    def cleanup_tasks(self) -> list[CleanupTask]: ...
```

| 钩子 | 默认行为 | 用途 |
|------|----------|------|
| `is_enabled()` | `True` | 按配置开关插件（如 `settings.rag_enabled`） |
| `on_startup(app)` | no-op | DB 初始化、健康检查、预热 |
| `on_shutdown()` | no-op | 连接池释放、资源清理 |
| `get_routers()` | `[]` | 返回需挂载的 FastAPI `APIRouter` 列表 |
| `get_tools(ctx)` | `[]` | 声明协议中立工具（**RagPlugin 不覆写**） |
| `build_mcp_server(ctx)` | `None` | **逃生舱**：插件自建 SDK MCP server，跳过 `get_tools` 自动包装 |
| `system_prompt_fragment(ctx)` | `None` | 返回 system prompt 片段，由 registry 拼接 |
| `cleanup_tasks()` | `[]` | 注册后台清理任务 |

设计原则：

- 所有钩子均有默认空实现，**最小插件只需 `name`**。
- 钩子失败由 registry 捕获并降级，不阻断其他插件。

### 4.5 build_mcp_server 逃生舱

当插件 MCP 工具无法简单映射为 `ToolSpec`（如需 request-scoped 状态、复杂装饰器）时，插件直接实现 `build_mcp_server` 并返回 SDK MCP server 实例。registry 在 `collect_mcp_servers` 时：

```
build_mcp_server(ctx) 非 None → 直接使用
否则 get_tools(ctx) 非空     → as_sdk_mcp_server(plugin.name, specs)
否则                         → 跳过
```

RAG 问答不走此收集逻辑，而是在 `RagAgentRunner` 内直接 `create_rag_mcp_server`；逃生舱主要服务 Phase 2 以后的通用插件。

## 5. tooling.py — ToolSpec 桥接

定义于 `app/plugins/tooling.py`。一份 `ToolSpec` 声明，两种消费形态。

### 5.1 as_sdk_mcp_server

```python
def as_sdk_mcp_server(server_name: str, specs: list[ToolSpec]) -> Any
```

行为：

1. 对每个 `ToolSpec`，用 `claude_agent_sdk.tool` 装饰包装 `handler`。
2. handler 返回值经 `json.dumps` 写入 MCP text content（与 RAG MCP 响应形态一致）。
3. 调用 `create_sdk_mcp_server(name=server_name, tools=...)` 返回 in-process MCP server。

用于 **路径 A：Claude Agent SDK MCP 循环**（`agent_service.query_stream(..., mcp_servers=...)`）。

### 5.2 as_anthropic_tools

```python
def as_anthropic_tools(specs: list[ToolSpec]) -> tuple[list[dict], ToolDispatcher]
```

行为：

1. 将 `ToolSpec` 列表转为 Anthropic Messages API 的 `tools` schema（`name` / `description` / `input_schema`）。
2. 返回 `(tools_schema, ToolDispatcher)`。

用于 **路径 B：裸 tool_use 循环**（直接调 Anthropic-compatible Messages API）。

### 5.3 ToolDispatcher

```python
class ToolDispatcher:
    async def execute(self, name: str, tool_input: dict[str, Any]) -> Any
```

- 按 `name` 路由到对应 `ToolSpec.handler`。
- 未知工具抛 `ValueError("unknown tool: ...")`。
- 由调用方（如 `stream_direct` 风格循环）在收到 `stop_reason=tool_use` 后调用 `execute`，将结果作为 `tool_result` 写回 messages。

## 6. registry.py — PluginRegistry

定义于 `app/plugins/registry.py`。核心代码**唯一**感知插件的位置。

### 6.1 注册与状态

```python
class PluginRegistry:
    def register(self, plugin: AgentPlugin) -> None
    @property
    def plugins(self) -> list[AgentPlugin]
    @property
    def enabled_plugins(self) -> list[AgentPlugin]
    def list_plugin_status(self) -> list[dict[str, Any]]
```

`list_plugin_status()` 返回 `[{"name": "...", "enabled": true/false}, ...]`，暴露于 `GET /config`。

### 6.2 生命周期

```python
async def startup_all(self, app: FastAPI) -> None
async def shutdown_all(self) -> None
def mount_routers(self, app: FastAPI) -> None
```

- `startup_all`：顺序调用各 enabled 插件的 `on_startup`；单个失败记日志并继续。
- `shutdown_all`：顺序调用 `on_shutdown`。
- `mount_routers`：遍历 `get_routers()` 并 `app.include_router`。

### 6.3 工具与 Prompt 收集

```python
def collect_mcp_servers(self, ctx: PluginContext) -> dict[str, Any]
def collect_anthropic_tools(self, ctx: PluginContext) -> tuple[list[dict], ToolDispatcher]
def collect_prompt_fragments(self, ctx: PluginContext) -> list[str]
def collect_cleanup_tasks(self) -> list[CleanupTask]
```

`collect_mcp_servers` 合并逻辑（每个 enabled 插件）：

```
try:
    server = plugin.build_mcp_server(ctx)
    if server is None:
        specs = plugin.get_tools(ctx)
        if specs:
            server = as_sdk_mcp_server(plugin.name, specs)
    if server is not None:
        servers[plugin.name] = server
except:
    log + continue
```

`collect_anthropic_tools`：扁平合并所有插件的 `get_tools(ctx)`，再 `as_anthropic_tools`。

### 6.4 全局单例

```python
plugin_registry = PluginRegistry()
```

在 `app/plugins/__init__.py` 中注册内置插件：

```python
plugin_registry.register(RagPlugin())
```

## 7. RagPlugin — 薄适配

定义于 `app/plugins/rag_plugin.py`。**包装现有 RAG 模块，不改动其内部实现。**

### 7.1 覆写钩子

| 钩子 | 实现 |
|------|------|
| `name` | `"rag"` |
| `is_enabled()` | `settings.rag_enabled` |
| `on_startup(app)` | `init_rag_db` + `set_mysql_store_for_ingestion`；`embedding_health_check` |
| `on_shutdown()` | `close_rag_db` |
| `get_routers()` | 返回 `routers.rag.router` |
| `cleanup_tasks()` | `rag_expired_file_sets` → `rag_ingestion_service.cleanup_expired_file_sets` |

### 7.2 刻意不实现

| 钩子 | 原因 |
|------|------|
| `get_tools` | RAG 工具经 `app/services/rag/mcp.py` 的 `create_rag_mcp_server` 注入，需 `RagRequestContext` 等 request-scoped 状态 |
| `build_mcp_server` | 同上；问答入口在 `RagAgentRunner`，不经 registry 收集 |
| `system_prompt_fragment` | RAG system prompt 由 `agent_runner` / router 层构建 |

### 7.3 与现有问答链路的关系

```
POST /agent-sdk/rag/stream
  → routers/rag.py
  → RagAgentRunner.stream_claude_sdk
  → create_rag_mcp_server(context, tool_service=...)   # 不变
  → agent_service.query_stream(mcp_servers={"rag": ...})
```

`RagPlugin` 仅负责 **应用级** 启停与路由挂载；**请求级** MCP 构建仍在 `RagAgentRunner` 内完成。

## 8. main.py 形态

保持单文件、自上而下可读，**不引入** `bootstrap.py`：

```python
# 1. 导入
from .plugins import plugin_registry

# 2. lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    await plugin_registry.startup_all(app)
    skills_manager.load_skills()
    # 鉴权状态打印 ...
    yield
    await plugin_registry.shutdown_all()

# 3. 创建 app + 中间件

# 4. 核心路由
app.include_router(agent_sdk_router)
app.include_router(agent_router)
app.include_router(skills_router)

# 5. 插件路由
plugin_registry.mount_routers(app)

# 6. 系统端点 /、/health、/config（含 plugins 状态）
```

对比改动前：

| 改动前 | 改动后 |
|--------|--------|
| `if settings.rag_enabled: init_rag_db(...)` 散落在 lifespan | `plugin_registry.startup_all(app)` |
| `if settings.rag_enabled: include_router(rag_router)` | `plugin_registry.mount_routers(app)` |
| shutdown 中 `close_rag_db` | `plugin_registry.shutdown_all()` |
| `/config` 无插件信息 | 返回 `plugins: plugin_registry.list_plugin_status()` |

## 9. 分阶段实施范围

### Phase 1 — 契约落地 + RAG 迁入（当前）

| 项 | 内容 |
|----|------|
| 新增 | `app/plugins/{base,tooling,registry,rag_plugin,__init__}.py` |
| 改造 | `main.py` 使用 `plugin_registry` |
| 测试 | `tests/test_plugins.py`：registry 启停、路由挂载、ToolSpec 分发、RagPlugin 开关 |
| 不变 | `RagAgentRunner`、`mcp.py`、`routers/rag.py` 问答逻辑 |
| 不变 | RAG 不实现 `get_tools` |

### Phase 2 — 通用 Agent 端点消费插件工具

| 项 | 内容 |
|----|------|
| 扩展 | `/agent-sdk/stream` 或新端点调用 `collect_mcp_servers` / `collect_anthropic_tools` |
| 扩展 | 构建 `PluginContext`（从 request 提取 tenant / api_key 等） |
| 扩展 | `collect_prompt_fragments` 拼入 system prompt |
| 示例 | Echo 类插件验证双路径工具消费 |
| 不变 | RAG 仍走 `RagAgentRunner` 专有 MCP 路径 |

### Phase 3 — 运维与生态

| 项 | 内容 |
|----|------|
| 新增 | `/admin/cleanup` 调用 `collect_cleanup_tasks` 并汇总执行结果 |
| 新增 | 更多业务插件（计费、外部 KB、审计） |
| 可选 | 插件级 metrics / health 探针 |
| 可选 | `build_mcp_server` 逃生舱用于复杂 request-scoped 插件 |

## 10. 验收标准

### 10.1 Phase 1 验收

- [ ] `main.py` 中无直接 `init_rag_db` / `include_router(rag_router)` 条件分支。
- [ ] `RAG_ENABLED=false` 时 `RagPlugin.is_enabled()` 为 `False`，RAG 路由不挂载、startup 跳过 RAG 初始化。
- [ ] `RAG_ENABLED=true` 时行为与插件化前一致：上传、索引、`/agent-sdk/rag/stream` SSE 正常。
- [ ] `GET /config` 返回 `plugins` 数组，含 `rag` 的 `enabled` 状态。
- [ ] `tests/test_plugins.py` 全部通过。
- [ ] `RagPlugin` **无** `get_tools` / `build_mcp_server` 覆写。
- [ ] `app/services/rag/` 内部文件无因插件化产生的逻辑变更。

### 10.2 Phase 2 验收

- [ ] 示例插件通过 `get_tools` 声明工具，经 `collect_mcp_servers` 可在 SDK 流式问答中调用。
- [ ] 同一组 `ToolSpec` 经 `collect_anthropic_tools` + `ToolDispatcher` 可在裸 `tool_use` 循环中调用。
- [ ] RAG 问答仍只走 `create_rag_mcp_server`，不经 registry 工具收集。

### 10.3 Phase 3 验收

- [ ] `/admin/cleanup` 触发 `rag_expired_file_sets` 等任务并返回清理计数。
- [ ] 新增插件只需 `register()` + 实现钩子，无需改 `main.py` 核心逻辑。

## 11. 两条工具消费路径

项目中存在两种 Agent 工具循环，插件 `ToolSpec` 设计为两条路径均可消费；**RAG 目前只走路径 A 的专有实现**。

### 11.1 路径 A — SDK MCP 循环（推荐）

```text
HTTP 请求
  → 构建 PluginContext（Phase 2+）或 RagRequestContext（RAG）
  → collect_mcp_servers(ctx)  或  create_rag_mcp_server(ctx)  # RAG 专有
  → agent_service.query_stream(
        mcp_servers={"plugin_name": sdk_mcp_server, ...},
        allowed_tools=[...],
    )
  → Claude Agent SDK 内部处理 tool call / tool result
  → SSE 流式返回 agent_delta
```

特点：

- 使用 `claude_agent_sdk` 的 in-process MCP。
- Skills、MCP tools、allowed_tools 由 SDK 统一编排。
- `as_sdk_mcp_server` 将 `ToolSpec` 包装为 SDK MCP tool。
- **RAG 生产路径**：`RagAgentRunner.stream_claude_sdk` + `mcp_servers={"rag": ...}`。

### 11.2 路径 B — 裸 tool_use 循环

```text
HTTP 请求
  → collect_anthropic_tools(ctx) → (tools_schema, dispatcher)
  → POST /v1/messages { tools: tools_schema, messages: [...] }
  → 解析 response.content 中 type=tool_use 的块
  → dispatcher.execute(name, input)
  → 将 tool_result 追加到 messages，继续下一轮
  → 直至 stop_reason != tool_use
  → SSE 流式返回
```

特点：

- 不经过 Claude Agent SDK，直接调 Anthropic-compatible Messages API。
- 适用于 SDK 不可用、或需精细控制多轮 tool loop 的场景。
- `as_anthropic_tools` + `ToolDispatcher` 提供与路径 A 等价的 handler 路由。
- **RAG 参考实现**：`RagAgentRunner.stream_direct`（内部自建 RAG tools，不经 `ToolSpec`）；HTTP 流式接口当前未默认接入。

### 11.3 路径对比

| | 路径 A：SDK MCP | 路径 B：裸 tool_use |
|---|---|---|
| 入口 API | Claude Agent SDK `query_stream` | Anthropic Messages API |
| 工具声明 | `ToolSpec` → `as_sdk_mcp_server` | `ToolSpec` → `as_anthropic_tools` |
| 工具执行 | SDK 内部 | `ToolDispatcher.execute` |
| Skills 支持 | ✅ 原生 | ❌ 需自行实现 |
| RAG 当前接入 | ✅ `create_rag_mcp_server` | ⚠️ `stream_direct` 内部实现，未走 `ToolSpec` |
| 插件 Phase 2 接入 | `collect_mcp_servers` | `collect_anthropic_tools` |

### 11.4 registry 收集与 RAG 专有条目

```text
collect_mcp_servers(ctx)
  ├── RagPlugin        → 跳过（无 get_tools / build_mcp_server）
  ├── EchoPlugin       → as_sdk_mcp_server("echo", specs)
  └── CustomPlugin     → build_mcp_server(ctx) 直接返回

RAG 问答（不经过 collect）
  └── RagAgentRunner → create_rag_mcp_server(rag_ctx)
```

**原则**：registry 负责「可声明式」的通用插件工具；RAG 因 request-scoped MCP 复杂度，保持在 `RagAgentRunner` + `mcp.py` 专有路径，待 Phase 3 如需统一再评估 `build_mcp_server` 迁移。

## 12. 代码改动范围（Phase 1）

| 文件 | 改动 |
|------|------|
| `app/plugins/base.py` | **新增**：契约定义 |
| `app/plugins/tooling.py` | **新增**：ToolSpec 桥接 |
| `app/plugins/registry.py` | **新增**：PluginRegistry |
| `app/plugins/rag_plugin.py` | **新增**：RAG 薄适配 |
| `app/plugins/__init__.py` | **新增**：注册 RagPlugin |
| `app/main.py` | 改造：lifespan / mount 委托 registry |
| `tests/test_plugins.py` | **新增**：插件单元测试 |
| `app/services/rag/*` | **不改** |
| `app/services/rag/mcp.py` | **不改** |
| `app/services/rag/agent_runner.py` | **不改** |

## 13. 不在本次范围

- 将 RAG MCP 工具迁移到 `RagPlugin.get_tools` 或 `build_mcp_server`。
- 拆分 `bootstrap.py` 或引入插件动态发现。
- 修改 `RagAgentRunner` SSE 事件格式或 `stream_claude_sdk` 签名。
- `/agent-sdk/rag/stream` 改为经 `collect_mcp_servers` 注入 RAG。
- 插件热插拔、版本管理、独立部署。
