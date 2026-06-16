# CC Agent SDK 能力清单

> 本文档是项目的**完整功能矩阵**，供二次开发、代码审查、框架迁移使用。  
> 面向用户的快速上手与部署说明见 [README.md](../../README.md)。

**最后核对**：2026-06-11（对照 `app/` 路由与 `tests/`）

---

## 1. 文档地图

| 文档 | 用途 |
|------|------|
| [README.md](../../README.md) | 快速开始、API 摘要、环境变量、部署 |
| **本文档** | 完整能力清单与实现状态 |
| [agentscope-migration.md](./agentscope-migration.md) | AgentScope 2.0 重写计划 |
| [agent-plugin-architecture.md](./agent-plugin-architecture.md) | 插件契约与 Phase 2 扩展 |
| [rag-knowledge-qa.md](./rag-knowledge-qa.md) | RAG 整体设计 |
| [rag-document-parsing.md](./rag-document-parsing.md) | 文档解析链路 |
| [rag-parse-only-qa.md](./rag-parse-only-qa.md) | 纯文件问答（parseOnly） |
| [rag-named-file-knowledge-base.md](./rag-named-file-knowledge-base.md) | 命名知识库 |
| [rag-kimi-parser.md](./rag-kimi-parser.md) | Kimi 解析器 |
| [rag-productionization.md](./rag-productionization.md) | RAG 产品化路线图（P3/P4） |
| [rag-technical-design.md](../design/rag-technical-design.md) | RAG 技术设计 |

---

## 2. 分层架构

```text
Layer A  HTTP API 契约        FastAPI routers（对外兼容 cc-agent-sdk）
Layer B  Agent 运行时          Claude Agent SDK CLI 子进程 + Skills + MCP
Layer C  RAG 子系统             解析 / 索引 / 检索 / 编排（框架相对独立）
Layer D  平台能力               Session、鉴权、工作目录隔离、插件
Layer E  路线图 / 未完成项      P3 队列、P4 多租户、db Session 等
```

---

## 3. Layer A — HTTP API

### 3.1 系统端点

| 方法 | 路径 | 状态 | 代码位置 |
|------|------|------|----------|
| GET | `/` | ✅ | `app/main.py` |
| GET | `/health` | ✅ | `app/main.py` |
| GET | `/config` | ✅ | `app/main.py` — 暴露 model、workDir、stream 模式、**插件状态** |

### 3.2 Agent SDK（正式 / 兼容 cc-agent-sdk）

| 方法 | 路径 | 状态 | 说明 |
|------|------|------|------|
| POST | `/agent-sdk/chat/stream` | ✅ | **推荐统一入口**；无 RAG 参数时等同 stream，有 RAG 参数时自动走文档问答 |
| POST | `/agent-sdk/stream` | ✅ | 普通 Agent + Skills 流式 |
| POST | `/agent-sdk/rag/stream` | ✅ | RAG + Agent + Skills 流式 |
| GET | `/agent-sdk/history` | ✅ | Claude Code 会话历史 |
| GET | `/agent-sdk/projects` | ✅ | 列出 Claude Code 项目 |
| GET | `/agent-sdk/conversations` | ✅ | 列出会话 |

鉴权：配置了 `AGENT_SDK_API_KEY` 时需请求头 `X-API-Key`。

### 3.3 简化 Agent API（Legacy）

| 方法 | 路径 | 状态 |
|------|------|------|
| POST | `/agent/query` | ✅ |
| POST | `/agent/query/stream` | ✅ |

### 3.4 Skills 管理

| 方法 | 路径 | 状态 |
|------|------|------|
| GET | `/skills` | ✅ |
| GET | `/skills/{name}` | ✅ |
| GET | `/skills/{name}/content` | ✅ |
| POST | `/skills` | ✅ |
| DELETE | `/skills/{name}` | ✅ |

**无** `/skills/{name}/invoke`：Skills 由 Agent 根据 description 自动匹配。

### 3.5 RAG — 文档与知识库

| 方法 | 路径 | 状态 | 说明 |
|------|------|------|------|
| POST | `/rag/files` | ✅ | 上传并入库；支持 `parseOnly=true` |
| GET | `/rag/files/{fileSetId}/status` | ✅ | 索引进度 |
| POST | `/rag/knowledge-bases` | ✅ | 创建持久知识库 |
| GET | `/rag/knowledge-bases` | ✅ | 列出知识库 |
| DELETE | `/rag/knowledge-bases/{id}` | ✅ | 删除知识库 |

### 3.6 RAG — 问答

| 方法 | 路径 | 状态 | 说明 |
|------|------|------|------|
| POST | `/agent-sdk/rag/stream` | ✅ | **生产推荐** |
| POST | `/agent-sdk/chat/stream` | ✅ | 带 RAG 参数时同上 |
| POST | `/rag/agent/stream` | ✅ | Legacy / 诊断 |
| POST | `/rag/stream` | ✅ | 纯 RAG MCP（无 Skills） |
| POST | `/rag/query` | ✅ | 非流式；服务端预检索 |

### 3.7 RAG — 运维 / Admin

| 方法 | 路径 | 状态 | 说明 |
|------|------|------|------|
| GET | `/rag/admin/provider-info` | ✅ | Provider 配置摘要 |
| GET | `/rag/admin/stats` | ✅ | 存储与索引统计 |
| POST | `/rag/admin/evaluate` | ✅ | 检索评测 |
| POST | `/rag/admin/cleanup` | ✅ | 清理过期临时 fileSet |
| GET | `/rag/admin/jobs/{jobId}` | ✅ | 入库任务状态 |
| POST | `/rag/admin/jobs/{jobId}/retry` | ✅ | 失败任务重试 |
| POST | `/rag/admin/jobs/{jobId}/cancel` | ✅ | 取消未完成任务 |

> P4 规划但尚未实现：query-logs、audit-logs、usage、health、orphan-cleanup、rebuild-index 等 Admin API。

### 3.8 SSE 事件契约（摘要）

**Agent SDK 流**（`/agent-sdk/stream`、`/chat/stream`）：

| type | subtype | 说明 |
|------|---------|------|
| `stream_event` | `start` / `init` / `end` | 流生命周期；`init` 含 session_id、tools、skills |
| `content_block_delta` | `text_delta` | 文本增量 |
| `assistant` | — | 助手消息块 |
| `result` | `success` / `error` | 最终结果；受 `resultMode` 控制 |
| `error` | — | 错误 |

**RAG 流**额外事件：

| event | 说明 |
|-------|------|
| `retrieval` | 强制预检索或 parse-only 命中；含 `mode`、`resultCount` 等 |
| `result` | 可含 `citations`、`toolCalls`、`verification` |

`eventMode=text_only` 时仅输出 `text_delta` + `end` + `error`，并强制 `resultMode=none`。

---

## 4. Layer B — Agent 运行时

> **迁移替换层**：AgentScope 2.0 重写时，本层是主要改动对象。详见 [agentscope-migration.md](./agentscope-migration.md)。

| 能力 | 状态 | 实现位置 | 说明 |
|------|------|----------|------|
| Claude Agent SDK 子进程 | ✅ | `app/services/agent.py` | 通过 `claude-agent-sdk` 启动 CLI |
| SSE 流式输出 | ✅ | `AgentService.query_stream` | 含中文 `ensure_ascii=False` |
| `eventMode` / `resultMode` | ✅ | `routers/agent_sdk.py` | full / text_only；full / empty / none |
| 请求级 model/baseURL/apiKey | ✅ | `StreamRequest` | 覆盖环境变量 |
| `allowedTools` / `disallowedTools` | ✅ | `AgentSDKOptions` | `[]` = Skills 全开 |
| `maxTurns` | ✅ | 透传 SDK | |
| `systemPrompt` + 项目 CLAUDE.md | ✅ | `agent.py` | 合并 cwd 下 `.claude/CLAUDE.md` |
| `settingSources` | ✅ | 默认 `["user","project"]` | project 加载 Skills |
| MCP 外部服务注入 | ✅ | `AGENT_SDK_MCP_SERVERS_JSON` | 环境变量注入 settings |
| MCP partial stream + fallback | ✅ | `agent.py` | `AGENT_SDK_INCLUDE_PARTIAL_WITH_MCP` |
| Stale resume 检测 | ✅ | `agent.py` | cwd 变化导致 resume 失败 |
| 全局工具禁用 | ✅ | `GLOBAL_DISALLOWED_TOOLS` | 默认 Write,Bash |
| Skills 自动匹配 | ✅ | Claude Code CLI | `.claude/skills/*/SKILL.md` |
| 历史读取 | ✅ | `app/services/history.py` | 读 Claude Code `.jsonl` |
| Markdown 资源 URL 重写 | ✅ | `agent.py` | 本地路径 → 可访问 URL（部分场景） |

**内部保留、HTTP 未接入**：

| 能力 | 位置 | 说明 |
|------|------|------|
| `RagAgentRunner.stream_direct` | `agent_runner.py` | Anthropic-compatible tool loop |
| Plugin `get_tools` 消费 | Phase 2 | 通用 `/agent-sdk/stream` 尚未接入插件 ToolSpec |

---

## 5. Layer C — RAG 子系统

> **建议保留**：与 Agent 框架耦合主要在 `RagAgentRunner.stream_claude_sdk` 调用 `agent_service.query_stream` 一处。

### 5.1 入库管线

| 能力 | 状态 | 代码 |
|------|------|------|
| 文件上传 | ✅ | `routers/rag.py`, `ingestion.py` |
| 文档解析 local | ✅ | `parser.py` |
| 文档解析 MinerU | ✅ | `parser.py` |
| 文档解析 Kimi | ✅ | `kimi_parser.py` |
| Hybrid 路由解析 | ✅ | `parser.py` |
| 文本切分 | ✅ | `chunker.py` |
| Embedding（local / openai_compatible） | ✅ | `embeddings.py`, `embedding_factory.py` |
| 向量存储 local (SQLite) | ✅ | `vector_store.py` |
| 向量存储 Qdrant | ✅ | `qdrant_vector_store.py`, `vector_store_factory.py` |
| pgvector / milvus | ⏳ 预留 | factory 未实现 |
| BackgroundTasks 异步入库 | ✅ | 进程内；P3 计划外部队列 |
| MySQL metadata store | ✅ | `mysql_store.py`, `database.py` |
| SQLite fallback | ✅ | `state_store.py` |
| parse-only 纯文件问答 | ✅ | `e_rag_parsed_file`；见 rag-parse-only-qa spec |
| ingestion job 状态机 | ✅ | pending → running → ready/failed |
| job retry / cancel API | ✅ | admin jobs 端点 |
| 过期 fileSet 清理 | ✅ | `RagPlugin.cleanup_tasks` |

### 5.2 检索与问答

| 能力 | 状态 | 代码 |
|------|------|------|
| 向量检索 | ✅ | `retriever.py` |
| 关键词 / 混合检索 | ✅ | `retriever.py` |
| query rewrite / multi-query | ✅ | `retriever.py` |
| rerank（local_lexical / cross_encoder_http） | ✅ | `reranker.py` |
| context window 扩展 | ✅ | `RagQueryOptions.contextWindow` |
| forceRetrieval 预检索 | ✅ | `routers/rag.py` |
| 引用对齐 / 答案验证 | ✅ | `answer_verifier.py` |
| 资料不足拒答 | ✅ | `pipeline.py` |
| RAG MCP 四工具 | ✅ | `mcp.py` |
| Claude SDK + in-process MCP 编排 | ✅ | `agent_runner.py` |
| 非流式预检索问答 | ✅ | `/rag/query` |
| 检索评测 | ✅ | `evaluation.py` |

**RAG MCP 工具名**：

- `rag_hybrid_search`
- `rag_read_chunk`
- `rag_get_file_outline`
- `rag_list_sources`

### 5.3 RAG 请求选项（`RagQueryOptions`）

| 字段 | 默认 | 说明 |
|------|------|------|
| `topK` | 8 | 检索 TopK |
| `retrieveTopK` | 100 | 召回候选池 |
| `finalTopK` | — | 最终证据数 |
| `hybrid` | true | 混合检索 |
| `forceRetrieval` | false | 服务端强制预检索 |
| `rerank` | false | 启用 rerank |
| `rerankProvider` | — | local_lexical / cross_encoder_http |
| `queryRewrite` | true | 查询扩展 |
| `multiQuery` | true | 多 query 召回 |
| `contextWindow` | 0 | 邻居 chunk 扩展 |
| `minConfidence` | 0 | 非流式最低置信度 |
| `lowConfidenceStrategy` | insufficient_context | |
| `verificationMode` | standard | off / standard / strict |
| `abstentionMode` | insufficient_context | |
| `answerWithCitations` | true | |
| `maxTurns` | 10 | Agent 最大轮次 |
| `eventMode` | rag | rag / agent-sdk-compatible |

### 5.4 RAG 鉴权（当前）

请求头（生产 P4 需从认证上下文派生，禁止信任客户端 metadata）：

| Header | 用途 |
|--------|------|
| `X-API-Key` | 服务鉴权 |
| `x-tenant-id` | 租户隔离 |
| `x-owner-id` | 所有者隔离 |
| `x-api-key-id` | API Key 维度 |

解析逻辑：`routers/rag.py` → `_auth_scope_from_request`。

---

## 6. Layer D — 平台能力

### 6.1 Session

| 能力 | 状态 | 说明 |
|------|------|------|
| `conversationId` ↔ `resume_id` 映射 | ✅ | `session.py` |
| `memory` 后端 | ✅ | 默认；重启丢失 |
| `file` 后端 | ✅ | JSON 持久化 |
| `db` 后端 | ⏳ 骨架 | `DbBackend` 四个方法待实现 |
| Session cwd 粘性 | ✅ | 同 conversationId 沿用首次 cwd |
| TTL / cleanup | 部分 | fileSet 过期清理有；会话目录清理 TODO |

### 6.2 工作目录解析

优先级（`resolve_agent_cwd`）：

```text
1. 请求 cwd（最高）
2. spaceId  → <WORK_DIR>/spaces/<spaceId>/
3. SESSION_ISOLATED_WORKDIR + conversationId → <WORK_DIR>/sessions/<conversationId>/
4. WORK_DIR（默认）
```

### 6.3 插件架构（Phase 1）

| 能力 | 状态 | 代码 |
|------|------|------|
| `AgentPlugin` 契约 | ✅ | `plugins/base.py` |
| `PluginRegistry` | ✅ | `plugins/registry.py` |
| `RagPlugin` | ✅ | `plugins/rag_plugin.py` |
| 启动/关闭钩子 | ✅ | DB init、embedding health check |
| 条件路由挂载 | ✅ | `RAG_ENABLED` |
| cleanup 任务注册 | ✅ | 过期 fileSet |
| `/config` 插件状态 | ✅ | `list_plugin_status()` |
| 通用 stream 接入插件 tools | ⏳ Phase 2 | 见 agent-plugin-architecture spec |

### 6.4 Skills 清单（14 个）

目录：`.claude/skills/`

| Skill | 主要能力 | 外部依赖 |
|-------|----------|----------|
| `Topic_Planning` | 选题策划路由 | — |
| `content-generate` | 多平台内容生成 | — |
| `style-transform` | 风格改写 | — |
| `text-optimize` | 文本优化 | — |
| `translate` | 多语言翻译 | — |
| `quality-review` | 内容审核 | — |
| `poetry-video-creator` | 古诗词视频全流程 | Seedream, Seedance, MiniMax TTS, FFmpeg |
| `seedream-ark` | AI 生图 | Volcengine API |
| `seedance-ark` | AI 生视频 | Volcengine API |
| `minimax-tts` | 语音合成 | MiniMax API |
| `ffmpeg-cli` | 音视频处理 | FFmpeg, Node.js |
| `primary-math-question-generator` | 小学数学出题 | — |
| `gaokao-politics-question-generator` | 高考政治出题 | — |
| `example` | 示例 Skill | — |

Skills 输出目录约定（基于 `$cwd`）：

```text
$cwd/assets/   # 中间产物
$cwd/output/   # 最终成品
```

### 6.5 测试覆盖（pytest）

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_rag_mvp.py` | RAG 核心流程 |
| `test_rag_smoke.py` | 冒烟 |
| `test_rag_parsers.py` | 文档解析 |
| `test_rag_vector_store_factory.py` | 向量库 factory |
| `test_rag_qdrant_vector_store.py` | Qdrant |
| `test_chat_stream.py` | 统一 chat/stream |
| `test_agent_sdk_fallback.py` | MCP partial fallback |
| `test_session_cwd.py` | cwd 解析 |
| `test_plugins.py` | 插件 registry |

**缺口**：job admin E2E、多租户越权、db Session、P4 审计/计费。

---

## 7. Layer E — 未完成 / 路线图

### 7.1 README 全局 TODO

| 项 | 优先级 | 状态 |
|----|--------|------|
| `db` Session 后端 | 高 | ⏳ |
| 会话过期目录清理 | 高 | ⏳ |
| 文件 URL 自动注入 SSE | 中 | ⏳ |
| 多 Worker Session 共享 | 中 | 依赖 db 后端 |
| `GET /agent-sdk/sessions` | 中 | ⏳ |
| Skills 热重载 | 低 | ⏳ |
| Docker 多阶段构建 | 低 | ⏳ |
| `allowedSkills` 白名单 | 低 | ⏳ |

### 7.2 RAG P3 — 异步入库队列

API 已有 job 查询/retry/cancel，但：

- [ ] 外部队列（Celery / ARQ / Dramatiq）
- [ ] Web / Worker 进程拆分
- [ ] 重启恢复、指数退避重试
- [ ] Worker 侧 cancel 中断
- [ ] `partial_ready` 稳定语义
- [ ] 并发控制、死信队列
- [ ] job admin **端到端测试**

### 7.3 RAG P4 — 权限、审计、计费

见 [rag-productionization.md](./rag-productionization.md) 与 README P4 章节。

### 7.4 与 cc-agent-sdk 差异矩阵

| 功能 | cc-agent-sdk | 本实现 |
|------|--------------|--------|
| 语言 / 框架 | TypeScript / Bun | Python / FastAPI |
| 统一 chat 入口 | — | `/agent-sdk/chat/stream` |
| RAG 知识库 | ❌ | ✅ |
| Skills 管理 API | ❌ | ✅ |
| 插件架构 | ❌ | ✅ Phase 1 |
| Plugin 状态 `/config` | ❌ | ✅ |
| parse-only 问答 | ❌ | ✅ |
| Qdrant 向量库 | ❌ | ✅ |

---

## 8. 环境变量索引

完整列表见 [`.env.example`](../../.env.example)。关键分组：

| 分组 | 代表变量 |
|------|----------|
| Anthropic | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL` |
| Agent SDK | `AGENT_SDK_API_KEY`, `AGENT_SDK_STREAM_*`, `AGENT_SDK_INCLUDE_PARTIAL_WITH_MCP` |
| Session | `SESSION_STORE`, `SESSION_FILE_PATH`, `SESSION_DB_DSN`, `SESSION_ISOLATED_WORKDIR` |
| 工作目录 | `WORK_DIR`, `SKILLS_DIR`, `GLOBAL_DISALLOWED_TOOLS` |
| RAG 开关 | `RAG_ENABLED`, `DB_DSN`, `RAG_STORAGE_DIR` |
| 向量 / Embedding | `RAG_VECTOR_PROVIDER`, `RAG_QDRANT_*`, `RAG_EMBEDDING_*` |
| 检索 | `RAG_RERANK_*`, `RAG_CHUNK_*`, `RAG_RETRIEVE_TOP_K` |
| 解析 | `FILE_PARSER_PROVIDER`, `MINERU_*`, `KIMI_*` |

---

## 9. 维护说明

更新本清单的时机：

1. 新增 / 删除 HTTP 路由
2. 变更 SSE 事件格式或请求模型
3. 新增 Skill 或外部依赖
4. 完成 TODO 项（更新状态列）
5. 开始 / 完成框架迁移阶段
