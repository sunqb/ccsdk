# AgentScope 2.0 迁移规格

> 将 CC Agent SDK 从 **Claude Agent SDK（CLI 子进程）** 迁移到 **AgentScope 2.0** 的实施计划。  
> 完整能力基线见 [project-capability-inventory.md](./project-capability-inventory.md)。

**目标**：保留对外 HTTP API 契约与 RAG 子系统，替换 Agent 运行时层。

**非目标**（第一阶段不做）：

- 重写 RAG 入库 / 检索管线
- 变更 MySQL schema
- 实现 P3/P4 产品化全部项
- 前端 SDK 破坏性变更

---

## 1. 为什么要分阶段迁移

当前架构中，**Claude Agent SDK 绑定最深**的部分：

```text
app/services/agent.py          ← CLI 子进程、resume、MCP、Skills、SSE 转换
app/services/rag/agent_runner.py ← 调用 agent_service.query_stream + in-process MCP
app/services/history.py        ← 读 Claude Code .jsonl 历史
app/services/session.py        ← conversationId → Claude session_id
```

RAG 其余模块（parser、chunker、embeddings、vector store、retriever、mysql_store）**与 Agent 框架基本解耦**，可直接保留。

---

## 2. 模块映射表

| 现有模块 | 迁移策略 | AgentScope 2.0 对应概念 | 风险 |
|----------|----------|---------------------------|------|
| `app/services/agent.py` | **替换** | `Agent` + `Model` + `Toolkit` / MCP | 高 |
| `app/services/session.py` | **保留接口，换存储** | AgentScope Memory / 自建 SessionStore | 中 |
| `app/services/history.py` | **重设计** | 自建 MessageStore（不再依赖 Claude .jsonl） | 中 |
| `app/services/skills.py` | **适配** | AgentScope Skill / System Prompt 片段 / ReAct 工具 | 高 |
| `.claude/skills/*` | **保留内容，换加载器** | 读 SKILL.md → prompt fragment 或 registered tool | 中 |
| `app/services/rag/*`（除 agent_runner） | **保留** | 作为 Python 模块被 Toolkit 调用 | 低 |
| `app/services/rag/mcp.py` | **改写为 Toolkit** | `@tool` 或 MCP Server 注册 | 中 |
| `app/services/rag/agent_runner.py` | **改写编排** | AgentScope Agent 流式 + RAG tools | 高 |
| `app/plugins/*` | **保留契约** | Plugin `get_tools` → AgentScope Toolkit | 低 |
| `app/routers/*` | **保留** | 仅换底层 service 调用 | 低 |
| FastAPI + SSE 格式 | **保留** | 适配层转换 AgentScope 消息 → SSE | 中 |

---

## 3. 概念对照

### 3.1 Claude Agent SDK → AgentScope 2.0

| Claude Agent SDK 概念 | 本项目中用法 | AgentScope 2.0 建议 |
|-----------------------|--------------|------------------------|
| Claude Code CLI 子进程 | `agent_service.query_stream` | 进程内 `Agent` + `ChatModel` |
| `resume` / session_id | `session.py` 映射 | AgentScope `Memory` / `StateModule` / 自建 JSON store |
| Skills（`.claude/skills/`） | CLI 自动加载 + `Skill` tool | System prompt 注入 + 可选 `@tool` 包装 |
| `allowedTools` / `disallowedTools` | 白名单 / 全局禁用 | Toolkit 注册时过滤 |
| `mcp_servers` in-process | RAG 四工具 | AgentScope MCP 集成或本地 `@tool` |
| `settingSources` + settings.json | 项目 / 用户配置 | 环境变量 + 项目配置模块 |
| `stream_event` / `text_delta` SSE | 对外 API 契约 | **适配层**映射 AgentScope stream → 现有 SSE 格式 |
| Claude Code history (.jsonl) | `/agent-sdk/history` | 迁移后改读自建 MessageStore |

### 3.2 RAG 编排路径

**现状**：

```text
POST /agent-sdk/rag/stream
  → RagAgentRunner.stream_claude_sdk
  → create_rag_mcp_server(ctx)
  → agent_service.query_stream(mcp_servers={...})
```

**目标**：

```text
POST /agent-sdk/rag/stream
  → RagAgentRunner.stream_agentscope   # 新方法
  → register_rag_tools(toolkit, ctx)   # 原 mcp.py 逻辑
  → agentscope_agent.stream(prompt)
  → SSE 适配层
```

`stream_direct`（Anthropic tool loop）可作为 AgentScope 原生 tool loop 的参考，但生产路径仍优先 **Agent + Toolkit**。

---

## 4. 分阶段计划

### Phase 0 — 准备（1 周）

- [ ] 锁定 AgentScope 2.0 版本与 Model 配置（OpenAI-compatible / DashScope / 自建）
- [ ] 搭建最小 POC：`Agent` + 单轮对话 + SSE 输出
- [ ] 定义 `AgentScopeService` 接口，签名对齐现有 `AgentService.query_stream`
- [ ] 编写 SSE 适配层测试：输出格式与现有 `test_chat_stream.py` 断言兼容

**验收**：`POST /agent/query/stream` 可走 AgentScope 路径（feature flag 切换）。

### Phase 1 — 基础对话（2–3 周）

替换目标：

- [ ] `POST /agent-sdk/stream`
- [ ] `POST /agent-sdk/chat/stream`（无 RAG 分支）
- [ ] `POST /agent/query`、`/agent/query/stream`

实现要点：

| 项 | 说明 |
|----|------|
| Session | 实现 `conversationId` → AgentScope memory；**不再依赖** Claude resume_id |
| History | 新 `MessageStore`（file 或 MySQL）；`/agent-sdk/history` 改读自建存储 |
| cwd | 保留 `resolve_agent_cwd` 逻辑；AgentScope 工具若需写文件，传入 workspace |
| eventMode / resultMode | 适配层支持 full / text_only |
| 鉴权 | 不变 |

**验收**：

- 现有 `test_chat_stream.py`、`test_session_cwd.py` 通过
- 前端无感切换（SSE 字段一致）

### Phase 2 — RAG 问答（2–3 周）

替换目标：

- [ ] `POST /agent-sdk/rag/stream`
- [ ] `POST /agent-sdk/chat/stream`（RAG 分支）
- [ ] `POST /rag/stream`、`/rag/agent/stream`
- [ ] `POST /rag/query`

实现要点：

| 项 | 说明 |
|----|------|
| RAG 四工具 | `mcp.py` → AgentScope Toolkit；保留 request-scoped context |
| forceRetrieval | 保留预检索 + `retrieval` SSE 事件 |
| parse-only | 保留 `PARSE_ONLY_DISALLOWED_TOOLS` 语义 |
| citations / verification | 保留 `answer_verifier` 与 result 结构 |

**不改动**：ingestion、vector store、mysql_store、admin API。

**验收**：`test_rag_mvp.py`、RAG 流式手动用例通过。

### Phase 3 — Skills 生态（3–4 周）

Skills 是当前与 Claude Code 绑定最深的业务能力。

| 策略 | 说明 | 适用 |
|------|------|------|
| A. Prompt 路由 | 读 SKILL.md frontmatter + body，注入 system prompt；Agent 自行遵循 | 纯文本类 Skills（content-generate、translate 等） |
| B. Tool 包装 | 每个 Skill 注册为 `@tool`，入口函数读 SKILL.md 执行流程 | 需要明确触发的 Skill |
| C. 子 Agent | 复杂 Skill（poetry-video-creator）拆为 AgentScope 多 Agent 工作流 | 视频 / 多步流水线 |

建议顺序：

1. 先迁移 **纯文本 Skills**（A 策略）
2. 再迁移 **带外部 API 的 Skills**（seedream、seedance、minimax-tts）
3. 最后迁移 **poetry-video-creator**（C 策略 + cwd 文件输出）

**验收**：Topic_Planning、content-generate、poetry-video-creator 端到端手动验证。

### Phase 4 — 平台补齐（并行 / 后续）

- [ ] `db` Session 后端（多 Worker）
- [ ] Plugin Phase 2：通用 stream 接入 `plugin_registry.collect_tools`
- [ ] 移除 Claude Agent SDK 依赖与 CLI 安装要求
- [ ] 更新 Dockerfile（去掉 Node/CLI 依赖，如有）

---

## 5. 建议的新增代码结构

```text
app/
├── services/
│   ├── agent.py                 # 保留接口；内部委托 agentscope_service
│   ├── agentscope/              # 新增
│   │   ├── __init__.py
│   │   ├── service.py           # AgentScopeService（对齐 query_stream 签名）
│   │   ├── sse_adapter.py       # AgentScope 消息 → AgentEvent → SSE
│   │   ├── memory_store.py      # conversationId 级 memory
│   │   ├── message_store.py     # history API 数据源
│   │   ├── toolkit_rag.py       # RAG 四工具注册
│   │   └── skills_loader.py     # SKILL.md → prompt / tools
│   └── rag/
│       └── agent_runner.py      # 新增 stream_agentscope
```

Feature flag 建议：

```env
AGENT_RUNTIME=claude_sdk   # 默认，迁移期间
AGENT_RUNTIME=agentscope   # 切换后
```

---

## 6. API 兼容承诺

迁移期间 **不改变** 以下对外契约：

| 契约 | 说明 |
|------|------|
| 路径 | 见 project-capability-inventory Layer A |
| 请求 JSON 字段 | camelCase；`ChatStreamRequest`、`RagStreamRequest` 不变 |
| SSE 主事件类型 | `stream_event`、`content_block_delta`、`result`、`error` |
| RAG 额外事件 | `event: retrieval` |
| conversationId 语义 | 对外 ID 不变；内部存储从 resume_id 改为 memory key |
| `/config` | 增加 `agentRuntime` 字段 |

**允许的内部变化**：

- `init.data.session_id` 格式可能变化（需文档说明）
- `/agent-sdk/history` 数据源从 Claude .jsonl 改为自建 store（旧 history 需迁移脚本或只读兼容层）
- `/agent-sdk/projects`、`/conversations` 可能 deprecated 或改语义

---

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Skills 无等价「自动匹配」 | 高 | Prompt 路由 + description 相似度预筛选；或显式 Skill 工具 |
| MCP partial stream 问题消失/变化 | 低 | AgentScope 原生流式；保留降级逻辑 |
| 历史会话不兼容 | 中 | 双读期：Claude .jsonl 只读 fallback |
| poetry-video-creator 依赖 Bash/Write | 高 | AgentScope 侧实现等价工具；调整 `GLOBAL_DISALLOWED_TOOLS` |
| 多 Model 提供商 | 中 | 统一 OpenAI-compatible 或 AgentScope Model 抽象 |
| 14 个 Skills 工作量大 | 高 | Phase 3 分 Skill 批次；优先业务关键路径 |

---

## 8. 迁移检查清单

### 8.1 每个 Phase 通用

- [ ] Feature flag 可切换 runtime
- [ ] pytest 相关套件通过
- [ ] SSE 样例与 inventory 文档一致
- [ ] `.env.example` 补充 AgentScope 配置项
- [ ] README 与 inventory 状态更新

### 8.2 Phase 1 完成标准

- [ ] 无 Claude CLI 依赖的基础对话
- [ ] Session memory/file 持久化
- [ ] history API 读自建 store
- [ ] eventMode / resultMode 行为一致

### 8.3 Phase 2 完成标准

- [ ] RAG 四工具在 AgentScope 下可用
- [ ] forceRetrieval + parse-only 行为一致
- [ ] citations / verification 在 result 中返回

### 8.4 Phase 3 完成标准

- [ ] 14 个 Skills 至少有明确的迁移策略标注（A/B/C）
- [ ] 核心业务 Skills 端到端验证通过
- [ ] cwd 文件输出 + Nginx 静态访问仍可用

### 8.5 最终完成标准

- [ ] 移除 `claude-agent-sdk` 依赖
- [ ] Docker 镜像不再要求 Claude Code CLI
- [ ] `AGENT_RUNTIME=agentscope` 为默认
- [ ] [project-capability-inventory.md](./project-capability-inventory.md) Layer B 更新为 AgentScope

---

## 9. AgentScope 2.0 配置草案

具体 API 以 AgentScope 官方文档为准；迁移实施时填写：

```env
# Agent 运行时
AGENT_RUNTIME=agentscope

# AgentScope Model（示例，按实际 provider 调整）
AGENTSCOPE_MODEL_PROVIDER=openai
AGENTSCOPE_MODEL_NAME=gpt-4o
AGENTSCOPE_API_KEY=
AGENTSCOPE_BASE_URL=

# Memory
AGENTSCOPE_MEMORY_STORE=file          # memory | file | db
AGENTSCOPE_MEMORY_FILE_PATH=./.agentscope/sessions

# Skills
AGENTSCOPE_SKILLS_DIR=./.claude/skills
AGENTSCOPE_SKILLS_MODE=prompt         # prompt | tool | hybrid
```

---

## 10. 相关文档

- [project-capability-inventory.md](./project-capability-inventory.md) — 完整能力矩阵
- [agent-plugin-architecture.md](./agent-plugin-architecture.md) — 插件与 Toolkit 扩展
- [rag-knowledge-qa.md](./rag-knowledge-qa.md) — RAG 设计（迁移后仍适用）
