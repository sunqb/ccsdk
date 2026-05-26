# CC Agent SDK

基于 Claude Agent SDK (Python) 的 Agent 服务，完全遵循 [cc-agent-sdk](https://github.com/Auto-200/cc-agent-sdk) 设计理念。在兼容原有 Agent / Skills 能力的基础上，内置 **RAG 知识库问答**（文档上传、混合检索、Claude SDK + in-process MCP 编排）。

## 特性

### Agent 与 API

- ✅ **完全兼容 cc-agent-sdk API**：`/agent-sdk/stream`、history、projects、conversations 等核心端点
- ✅ **SSE 流式响应**：实时推送 Agent 事件；支持 `eventMode`（`full` / `text_only`）与 `resultMode`（`full` / `empty` / `none`）
- ✅ **请求级配置覆盖**：支持 `model`、`baseURL`、`apiKey`、`cwd`、`allowedTools`、`maxTurns` 等覆盖
- ✅ **API Key 鉴权**：通过 `AGENT_SDK_API_KEY` 保护接口（未配置时不启用）
- ✅ **中文支持**：正确处理中文输出编码

### Skills 与工作区

- ✅ **Skills 自动匹配**：Claude 根据 description 自动调用 `.claude/skills/` 下的 Skills
- ✅ **Skills 管理 API**：`GET/POST/DELETE /skills` 查询、创建、删除 Skills
- ✅ **MCP 与权限注入**：通过环境变量注入附加 settings、permissions 与 MCP 服务，无需手写 `.claude/settings.json`
- ✅ **工具安全策略**：`GLOBAL_DISALLOWED_TOOLS` 全局禁用危险工具（默认禁用 `Write`/`Bash`）

### 会话与隔离

- ✅ **会话管理**：`conversationId` 续聊；`SESSION_STORE` 支持 `memory` / `file` / `db` 存储后端
- ✅ **用户数据隔离**：请求级 `cwd`，或 `SESSION_ISOLATED_WORKDIR` 按会话自动隔离工作目录
- ✅ **文件静态访问**：配合 Nginx 将生成文件映射为 HTTP URL，前端可直接访问

### RAG 知识库问答

- ✅ **知识库与临时文件**：持久化知识库 + 上传 `.txt/.md/.pdf/.docx` 进行问答
- ✅ **Claude SDK 统一编排**：RAG 流式走 Agent SDK + request-scoped in-process MCP（推荐 `POST /agent-sdk/rag/stream`）
- ✅ **检索增强**：混合检索、多 query 扩展、rerank、引用对齐校验与资料不足拒答
- ✅ **文档解析可配置**：`RAG_PARSER_PROVIDER=local` 本地解析，或 `mineru` 调用 MinerU 解析 PDF/DOCX（可配置回退）
- ✅ **运维接口**：知识库 CRUD、索引状态、provider 信息、检索评测与过期清理

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/sunqb/ccsdk.git
cd ccsdk
```

### 2. 安装依赖

```bash
# 使用 uv (推荐)
uv pip install -r requirements.txt

# 或使用 pip
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
vim .env
```

必填配置：
```env
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_BASE_URL=https://api.anthropic.com  # 可选
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
```

### 4. 启动服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. 测试 API

**Agent 流式（需配置 `AGENT_SDK_API_KEY` 时加 `-H "X-API-Key: ..."`）**

```bash
curl -X POST http://localhost:8000/agent-sdk/stream \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello, Claude!", "options": {"allowedTools": []}}'
```

**RAG（需 `RAG_ENABLED=true`）**

```bash
# 1. 上传文档
curl -X POST http://localhost:8000/rag/files \
  -F "file=@./docs/specs/rag-document-parsing.md"

# 2. 基于 fileSetId 流式问答（推荐入口）
curl -N -X POST http://localhost:8000/agent-sdk/rag/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "这份文档讲了什么？", "fileSetId": "<上一步返回的 fileSetId>"}'
```

## 核心架构

### 整体架构

```
                         ┌──────────────┐
                         │    Client    │
                         └──────┬───────┘
                                │ HTTP / SSE
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                     FastAPI (app/main.py)                         │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────┐ ┌────────────────┐ │
│  │ agent_sdk   │ │    rag      │ │  skills  │ │ agent (简化)   │ │
│  │ /agent-sdk/*│ │   /rag/*    │ │ /skills/*│ │   /agent/*     │ │
│  └──────┬──────┘ └──────┬──────┘ └────┬─────┘ └───────┬────────┘ │
│         │               │             │               │          │
│         ▼               ▼             ▼               ▼          │
│  services/agent   services/rag   services/skills   (同上)       │
│  services/session services/history                               │
└───────────────────────────────┬───────────────────────────────────┘
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
┌─────────────────────────┐              ┌────────────────────────────┐
│ Claude Agent SDK (CLI)  │              │ RAG Pipeline（可选启用）    │
│ • Skills 自动匹配        │              │ 解析 → 切分 → Embedding    │
│ • MCP（项目 + 注入）     │◄─ mcp_servers│ → Local SQLite 向量检索   │
│ • 会话 resume / 历史     │              │ → Hybrid Search / Rerank   │
└───────────┬─────────────┘              └────────────────────────────┘
            ▼
┌─────────────────────────┐
│ Anthropic / 兼容 API    │
└─────────────────────────┘
```

### RAG 数据流

```
上传 POST /rag/files
    → DocumentParser (local / mineru)
    → TextChunker → EmbeddingProvider → LocalVectorStore (rag.db)
    → 返回 fileSetId

问答 POST /agent-sdk/rag/stream  （推荐）
    → RagAgentRunner.stream_claude_sdk
    → 注入 request-scoped MCP: rag_hybrid_search / rag_read_chunk / ...
    → Claude 自主决定是否检索 → 流式 SSE 回答

纯 RAG 调试 POST /rag/stream
    → 同上，但 allowed_tools 仅限四个 RAG MCP 工具（无 Skills 编排）
```

### 路由分组

| 前缀 | 模块 | 说明 |
|------|------|------|
| `/agent-sdk` | `routers/agent_sdk.py` | cc-agent-sdk 兼容入口；含 `/rag/stream` |
| `/rag` | `routers/rag.py` | 文档上传、知识库、RAG 流式/非流式、运维 |
| `/skills` | `routers/skills.py` | Skills CRUD |
| `/agent` | `routers/agent.py` | 简化版非兼容 API（`/query`、`/query/stream`） |

## Skills 使用方式

### Skills 自动加载

Skills 存放在 `.claude/skills/` 目录，SDK 会自动加载：

```
.claude/skills/
├── Topic_Planning/
│   └── SKILL.md
└── example/
    └── SKILL.md
```

### SKILL.md 格式

```markdown
---
name: Topic_Planning
description: 选题策划主入口 - 识别策划场景，引导用户进入对应的专项Skill流程
version: 1.0.0
tags: [topic, planning, router]
---

# 选题策划主入口

## 核心任务
作为选题策划系统的总入口，负责...
```

### Skills 自动匹配机制

**无需手动指定 Skill**，Claude 会自动判断：

```bash
# 用户发送自然语言请求
curl -X POST http://localhost:8000/agent-sdk/stream \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "《长安的荔枝》选题",
    "cwd": "/path/to/project"
  }'

# Claude 自动：
# 1. 识别到 "选题" 关键词
# 2. 匹配 Topic_Planning skill 的 description
# 3. 决定是否调用该 Skill
# 4. 如果匹配度高，自动调用
```

**设计哲学**：完全信任 Claude 的判断能力，不需要人工指定 Skill 名称。

## API 端点

> 配置了 `AGENT_SDK_API_KEY` 时，受保护接口需请求头 `X-API-Key: <key>`（与 cc-agent-sdk 一致）。

### Agent SDK（cc-agent-sdk 兼容）

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/agent-sdk/stream` | Agent 流式查询 (SSE) |
| POST | `/agent-sdk/rag/stream` | **RAG + Skills 流式问答（推荐）** |
| GET | `/agent-sdk/history` | 查询会话历史 |
| GET | `/agent-sdk/projects` | 列出 Claude Code 项目 |
| GET | `/agent-sdk/conversations` | 列出会话 |

### RAG

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/rag/files` | 上传文档，解析索引，返回 `fileSetId` |
| GET | `/rag/files/{file_set_id}/status` | 查询 fileSet 索引进度 |
| POST | `/rag/knowledge-bases` | 创建持久化知识库 |
| GET | `/rag/knowledge-bases` | 列出知识库 |
| DELETE | `/rag/knowledge-bases/{id}` | 删除知识库 |
| POST | `/agent-sdk/rag/stream` | RAG + Agent + Skills（**生产推荐**） |
| POST | `/rag/agent/stream` | 同上，Legacy / 诊断入口 |
| POST | `/rag/stream` | 纯 RAG MCP 流式（无 Skills） |
| POST | `/rag/query` | 非流式问答（服务端预检索） |
| GET | `/rag/admin/provider-info` | 当前 RAG provider 配置摘要 |
| GET | `/rag/admin/stats` | 存储与索引统计 |
| POST | `/rag/admin/evaluate` | 检索评测 |
| POST | `/rag/admin/cleanup` | 清理过期临时 fileSet |

### Skills 管理

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/skills` | 列出所有 Skills |
| GET | `/skills/{name}` | 获取 Skill 详情 |
| GET | `/skills/{name}/content` | 获取 Skill 内容 |
| POST | `/skills` | 创建新 Skill |
| DELETE | `/skills/{name}` | 删除 Skill |

### 简化 Agent API

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/agent/query` | 非流式查询 |
| POST | `/agent/query/stream` | 流式查询 |

**注意**：没有 `/skills/{name}/invoke` 端点；Skills 通过 `/agent-sdk/stream` 或 `/agent-sdk/rag/stream` 由 Claude 自动匹配调用。

### POST /agent-sdk/stream

**请求体:**
```json
{
  "prompt": "用户提示词",
  "conversationId": "会话ID (可选)",
  "cwd": "/path/to/project",
  "settingSources": ["project"],
  "model": "claude-sonnet-4-5-20250929",
  "resultMode": "full",
  "eventMode": "full",
  "options": {
    "allowedTools": [],
    "maxTurns": 10
  }
}
```

**可选参数说明：**
- `eventMode=full`：输出完整事件流（默认，尽量与 Claude Code CLI/SDK 保持一致）
- `eventMode=text_only`：仅输出 `content_block_delta/text_delta`（并保留 `stream_event/end` 与 `error`）；该模式下服务会强制 `resultMode=none`，避免最后的全量 `result`

**响应 (text/event-stream):**
```
data: {"type": "stream_event", "subtype": "start", "conversationId": "xxx"}

data: {"type": "stream_event", "subtype": "init", "data": {...}, "conversationId": "xxx"}

data: {"type": "content_block_delta", "subtype": "text_delta", "data": {"text": "你好！"}, "conversationId": "xxx"}

data: {"type": "result", "subtype": "success", "data": {"result": "..."}, "conversationId": "xxx"}
```

### 会话（新建 / 继续 / 历史）

- **新建会话**：不传 `conversationId`（或传一个全新的 ID），服务会创建新会话
- **继续会话**：后续请求复用同一个 `conversationId`
- **查询历史**：调用 `GET /agent-sdk/history?conversationId=...`
  - Claude Code 的历史文件名是其内部 `session_id`（位于 `stream_event/init.data.session_id`，或可通过 `GET /agent-sdk/conversations` 列出）
  - 本服务也支持用”本服务的 conversationId”查询历史（会在进程内存中映射到 `session_id`）；若服务重启，需直接使用 Claude Code 的 `session_id`

### 会话 ID 的两层结构

本服务存在两个不同的 ID，理解它们的关系对二次开发至关重要：

| ID | 来源 | 作用 |
|----|------|------|
| `conversationId`（如 `74dfd566-...`） | 本服务生成的 UUID | 对外暴露给调用方，用于在本服务内查找 Session |
| `resume_id`（如 `e960de6f-...`） | Claude Code CLI 返回的 `session_id` | CLI 内部标识，对应磁盘上 `~/.claude/projects/.../<resume_id>.jsonl` |

**对话历史不存在本服务**，而是由 Claude Code CLI 自动写入 `.jsonl` 文件。本服务的 Session 只是一张”索引表”，记录 `conversationId → resume_id` 的映射关系：

```
下次请求携带 conversationId=74dfd566...
    ↓
SessionManager 查找 Session，取出 metadata.resume_id = e960de6f...
    ↓
options.resume = “e960de6f...” 传给 Claude Code CLI
    ↓
Claude Code CLI 读取 ~/.claude/projects/.../<resume_id>.jsonl
    ↓
对话上下文恢复
```

**快捷方式**：如果客户端保存了 Claude Code 原始的 `resume_id`，可以直接将其作为 `conversationId` 传入，本服务会透传给 CLI，跳过映射这一层。

### Session 存储模式

通过 `SESSION_STORE` 环境变量选择存储后端：

| 模式 | 适用场景 | 重启后恢复 | 多 Worker |
|------|---------|-----------|-----------|
| `memory`（默认） | 测试、无状态短会话 | ❌ | ❌ |
| `file` | 单机长期对话 | ✅ | ❌ |
| `db` | 生产多实例部署 | ✅ | ✅（待实现） |

`file` 模式将 `conversationId → resume_id` 映射持久化到本地 JSON 文件（默认 `.claude/sessions.json`），服务重启后自动加载。`db` 模式骨架已就位，实现时填充 `app/services/session.py` 中 `DbBackend` 的 TODO 方法即可，上层代码无需修改。

### 用户数据隔离与文件静态访问

Skills（如古诗词视频生成）运行过程中会产生图片、视频、音频等本地文件。通过以下配置实现多用户数据隔离并让前端可直接访问这些文件。

#### 工作目录隔离

每个会话的生成文件落在独立目录，有两种方式：

**方式 1：前端传 `cwd`（精确控制）**

```json
{
  "prompt": "帮我生成《静夜思》的古诗词视频",
  "conversationId": "user-123-session-abc",
  "cwd": "/data/outputs/user-123/session-abc"
}
```

同一 `conversationId` 后续请求不传 `cwd` 时，自动沿用第一次的值。

**方式 2：自动按 `conversationId` 隔离（推荐）**

```env
SESSION_ISOLATED_WORKDIR=true
WORK_DIR=/data/outputs
```

启用后，未传 `cwd` 的会话自动使用 `<WORK_DIR>/sessions/<conversationId>/` 作为工作目录。

两种方式优先级：**请求传入的 `cwd` > `SESSION_ISOLATED_WORKDIR` 自动生成 > `WORK_DIR`**。

#### Nginx 静态文件服务

将 `WORK_DIR` 映射为 HTTP 路径，前端通过 URL 直接访问生成的文件：

```nginx
server {
    listen 80;

    # 静态文件访问（生成的图片、视频、音频）
    location /outputs/ {
        alias /data/outputs/;
        add_header Access-Control-Allow-Origin *;
        # 视频文件支持 Range 请求（前端播放器需要）
        add_header Accept-Ranges bytes;
    }

    # API 反向代理
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # SSE 必须关闭缓冲
        proxy_buffering off;
        proxy_cache off;
    }
}
```

#### 文件访问 URL 规则

| 配置 | 本地路径 | 访问 URL |
|------|---------|---------|
| `SESSION_ISOLATED_WORKDIR=true`，`WORK_DIR=/data/outputs` | `/data/outputs/sessions/<conversationId>/assets/ref.jpg` | `http://your-server/outputs/sessions/<conversationId>/assets/ref.jpg` |
| 前端传 `cwd=/data/outputs/user-123/` | `/data/outputs/user-123/assets/ref.jpg` | `http://your-server/outputs/user-123/assets/ref.jpg` |

#### Skills 文件输出约定

支持输出文件的 Skills（如 `poetry-video-creator`）遵循以下目录约定：

```
$cwd/
├── assets/          # 中间产物（参考板图片、分镜视频、旁白音频）
│   ├── ref_*.jpg
│   ├── scene_*.mp4
│   └── narration_*.mp3
└── output/          # 最终成品
    └── final_video.mp4
```

所有路径均基于 `$PWD`（即 `cwd`）展开为绝对路径，不依赖 Node.js 进程目录。

### MCP（可选：接入搜索等外部工具）

Claude Agent SDK 底层通过 Claude Code CLI 启动 MCP Server。你需要：

1) 在 **Claude Code 可加载的 settings** 里配置 `mcpServers`（推荐放在项目下，随 `cwd` 生效）  
2) 确保请求的 `settingSources` 覆盖到你放置 settings 的来源（`project/user/local`）  
3) `options.allowedTools` 语义：推荐传 `[]` 表示 Skills 全开；非空列表为白名单。不要把白名单写窄到误排除 MCP（若需限制，应显式包含 `mcp__<server>__<tool>`）

**示例：在 `./.claude/settings.json` 配置一个 stdio MCP server（以“搜索类 server”为例，command/args 请以该 server 文档为准）**
```json
{
  "mcpServers": {
    "search": {
      "command": "npx",
      "args": ["-y", "<mcp-server-package>"],
      "env": {
        "API_KEY": "从环境变量或明文填写"
      }
    }
  }
}
```

**如果你把配置写在 `./.claude/settings.local.json`（不建议提交到 git）**  
请求里请传：`"settingSources": ["project", "local"]`

**验证是否生效**  
调用 `/agent-sdk/stream`，看 `stream_event/init` 事件里的 `mcp_servers` 是否出现你的 server 名称；同时 `tools` 列表里会出现形如 `mcp__search__xxx` 的工具名。

## 环境变量

完整示例见 [`.env.example`](.env.example)。下表列出常用项：

### Agent / 服务

| 变量名 | 描述 | 默认值 | 必填 |
|--------|------|--------|------|
| `ANTHROPIC_API_KEY` | Anthropic API Key | - | ✅ |
| `ANTHROPIC_AUTH_TOKEN` | 同 API_KEY | - | 否 |
| `ANTHROPIC_BASE_URL` | API Base URL | - | 否 |
| `ANTHROPIC_MODEL` | 使用的模型 | `claude-sonnet-4-20250514` | 否 |
| `AGENT_SDK_API_KEY` | 服务 API 认证密钥 | - | 否 |
| `AGENT_SDK_STREAM_RESULT_MODE` | result 输出：`full` / `empty` / `none` | `full` | 否 |
| `AGENT_SDK_STREAM_EVENT_MODE` | 事件输出：`full` / `text_only` | `full` | 否 |
| `AGENT_SDK_ADDITIONAL_SETTINGS_JSON` | 注入 `claude --settings` 的 JSON | `{"skipWebFetchPreflight":true}` | 否 |
| `AGENT_SDK_PERMISSIONS_ALLOW` | `permissions.allow` 规则（逗号分隔） | - | 否 |
| `AGENT_SDK_MCP_SERVERS_JSON` | 注入外部 MCP servers（JSON） | - | 否 |
| `HOST` / `PORT` | 监听地址与端口 | `0.0.0.0` / `8000` | 否 |
| `WORK_DIR` | Agent 工作目录 | 项目根目录 | 否 |
| `SKILLS_DIR` | Skills 目录 | `./.claude/skills` | 否 |
| `GLOBAL_DISALLOWED_TOOLS` | 全局禁用工具；空字符串表示全部放开 | `Write,Bash` | 否 |

### Session / 隔离

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| `SESSION_STORE` | `memory` / `file` / `db` | `memory` |
| `SESSION_FILE_PATH` | file 模式映射文件 | `./.claude/sessions.json` |
| `SESSION_DB_DSN` | db 模式连接串 | - |
| `SESSION_ISOLATED_WORKDIR` | 按 `conversationId` 自动隔离 cwd | `false` |

### RAG

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| `RAG_ENABLED` | 是否启用 RAG | `false` |
| `RAG_STORAGE_DIR` | 状态与向量快照目录 | `${WORK_DIR}/rag` |
| `RAG_VECTOR_PROVIDER` | 向量库 provider。当前真实可用：`local`；`qdrant` / `pgvector` / `milvus` 为预留 | `local` |
| `RAG_EMBEDDING_PROVIDER` | Embedding provider。支持 `local` / `openai_compatible` | `openai_compatible` |
| `RAG_EMBEDDING_MODEL` | Embedding 模型名称，例如 `bge-m3:latest` | `text-embedding-3-small` |
| `RAG_EMBEDDING_BASE_URL` | OpenAI-compatible embedding 服务地址，例如 `http://host:port/v1` | 空 |
| `RAG_EMBEDDING_API_KEY` | Embedding 服务 API Key | 空 |
| `RAG_PARSER_PROVIDER` | 解析：`local` / `mineru` | `local` |
| `MINERU_*` | MinerU 地址、密钥、超时、回退 | 见 `.env.example` |
| `RAG_ALLOWED_EXTENSIONS` | 允许上传扩展名 | `.txt,.md,.pdf,.docx` |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | 切分参数 | `1000` / `120` |
| `RAG_MAX_CONCURRENT_INGESTIONS` | 入库并发上限 | `4` |
| `RAG_MAX_CONCURRENT_QUERIES` | 查询并发上限 | `16` |

#### BGE-M3 embedding + local vector store 示例

开发环境可以使用远程 BGE-M3 作为 embedding 模型，同时继续使用本地 `LocalVectorStore` 作为向量存储：

```env
RAG_ENABLED=true

# 向量库：本地开发/单机测试
RAG_VECTOR_PROVIDER=local

# Embedding：OpenAI-compatible BGE-M3
RAG_EMBEDDING_PROVIDER=openai_compatible
RAG_EMBEDDING_MODEL=bge-m3:latest
RAG_EMBEDDING_BASE_URL=http://zktz.4c888.com:62011/v1
RAG_EMBEDDING_API_KEY=<your-api-key>
```

链路如下：

```text
文档文本
  ↓
BGE-M3 生成 1024 维 embedding
  ↓
LocalVectorStore 保存 chunk + embedding
  ↓
查询文本通过同一 BGE-M3 生成 query embedding
  ↓
LocalVectorStore 做 cosine similarity 检索
```

该组合适合开发验证和单机小规模测试。生产环境建议替换为 Qdrant、Milvus、pgvector 等真实向量数据库。

## 项目结构

```
ccsdk/
├── app/
│   ├── main.py                 # FastAPI 入口，注册全部路由
│   ├── config.py               # 环境变量与 Settings
│   ├── auth.py                 # X-API-Key 鉴权
│   ├── models/
│   │   ├── request.py          # Agent 请求模型
│   │   ├── response.py         # 通用响应
│   │   └── rag.py              # RAG 请求/响应模型
│   ├── routers/
│   │   ├── agent_sdk.py        # /agent-sdk/*（含 /rag/stream）
│   │   ├── rag.py              # /rag/*
│   │   ├── skills.py           # /skills/*
│   │   └── agent.py            # /agent/* 简化 API
│   └── services/
│       ├── agent.py            # Claude Agent SDK 封装
│       ├── session.py          # conversationId ↔ resume_id
│       ├── skills.py           # Skills 加载与管理
│       ├── history.py          # 历史记录读取
│       └── rag/                # RAG 子系统
│           ├── ingestion.py    # 上传入库
│           ├── parser.py       # local / MinerU 文档解析
│           ├── chunker.py      # 文本切分
│           ├── embeddings.py          # Embedding provider 实现
│           ├── embedding_factory.py   # Embedding 单点真值与健康检查
│           ├── vector_store.py        # 本地向量检索与维度一致性防护
│           ├── retriever.py    # 混合检索 + rerank
│           ├── mcp.py          # in-process RAG MCP 四件套
│           ├── agent_runner.py # RAG 流式编排（Claude SDK）
│           ├── answer_verifier.py
│           └── ...
│
├── .claude/
│   ├── skills/                 # Skills（SDK 自动加载）
│   └── settings.json           # 项目级 Claude Code 配置
│
├── docs/specs/
│   ├── rag-knowledge-qa.md     # RAG 整体设计
│   └── rag-document-parsing.md # 文档解析链路
│
├── tests/                      # pytest（RAG MVP / parser / smoke）
├── .env.example
├── Dockerfile
├── requirements.txt
└── README.md
```

## 关键实现细节

### 1. API Key 配置

支持 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_AUTH_TOKEN` 两种环境变量：

```python
# config.py
anthropic_api_key: str = field(
    default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
)
```

### 2. 环境变量继承

SDK 子进程需要完整的环境变量：

```python
# agent.py
env = dict(os.environ)  # 继承所有环境变量
env["ANTHROPIC_API_KEY"] = effective_api_key
env["ANTHROPIC_BASE_URL"] = effective_base_url
```

### 3. 中文编码修复

SSE 响应中正确显示中文：

```python
# agent.py
def to_sse(self) -> str:
    return f"data: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"
```

### 4. 默认工具配置

使用 SDK 默认工具集（Skills 全开），推荐显式传 `[]`，不要限制为 `["Skill"]`：

```python
# agent_sdk.py
tools = allowed_tools if allowed_tools is not None else []
```

### 5. 设置加载

默认只加载项目级别配置，避免用户配置冲突：

```python
# agent.py
effective_setting_sources = setting_sources if setting_sources is not None else ["project"]
```

## 常见问题

### Q: WebFetch 报错 "Unable to verify if domain xxx is safe to fetch"？

**重要发现**：这是因为 WebFetch 的预检（preflight）功能尝试访问 `claude.ai` 验证域名安全性，但由于网络限制导致验证失败。

**解决方案**：在 `.claude/settings.json` 中添加 `skipWebFetchPreflight: true` 跳过预检：

```json
{
  "skipWebFetchPreflight": true
}
```

### ⚠️ 重要：Claude Code CLI 配置优先级

Claude Code CLI 的配置加载机制比较复杂，理解优先级关系对于正确配置至关重要：

#### 配置来源

| 来源 | 说明 | CLI 参数 |
|------|------|----------|
| `--settings` | 通过命令行传入的 JSON 配置 | `--settings '{"key": value}'` |
| `user` | 用户级配置 `~/.claude/settings.json` | `--setting-sources user` |
| `project` | 项目级配置 `{cwd}/.claude/settings.json` | `--setting-sources project` |
| `local` | 本地配置 `{cwd}/.claude/settings.local.json` | `--setting-sources local` |

#### 优先级规则（从高到低）

```
1. local  (.claude/settings.local.json)     ← 最高优先级
2. project (.claude/settings.json)
3. user   (~/.claude/settings.json)
4. --settings 参数                           ← 最低优先级（会被文件配置覆盖！）
```

#### 关键发现

**`--settings` 参数的优先级最低！** 当同时指定了 `--setting-sources` 和 `--settings` 时：

```bash
# 这个命令中，skipWebFetchPreflight 可能不会生效！
claude --settings '{"skipWebFetchPreflight": true}' --setting-sources project ...
```

如果 `.claude/settings.json` 中没有 `skipWebFetchPreflight` 字段，CLI 会使用默认值 `false`，**覆盖掉** `--settings` 传入的 `true`。

#### 解决方案

**方案 1（推荐）**：在项目的 `.claude/settings.json` 中显式配置

```json
{
  "skipWebFetchPreflight": true,
  "其他配置": "..."
}
```

**方案 2**：不加载任何配置文件，仅使用 `--settings`

```python
# 将 setting_sources 设为空列表
effective_setting_sources = []  # 不加载 user/project/local 配置
```

但方案 2 会导致 Skills 无法加载（Skills 需要 `project` 配置源）。

#### 本项目的处理方式

本项目通过两种方式确保 `skipWebFetchPreflight` 生效：

1. **代码默认值**（`config.py`）：
   ```python
   agent_sdk_additional_settings_json = '{"skipWebFetchPreflight": true}'
   ```

2. **项目配置文件**（`.claude/settings.json`）：
   ```json
   {"skipWebFetchPreflight": true}
   ```

两者缺一不可，因为配置文件会覆盖代码传入的值。

### Q: 如何让 Claude 调用我的 Skill？

确保 SKILL.md 的 `description` 字段准确描述功能，Claude 会根据用户 prompt 自动匹配。

### Q: Skills 不被调用怎么办？

1. 检查 `settingSources` 是否包含 `"project"`
2. 检查 `.claude/skills/` 目录下是否有 SKILL.md
3. 确认 SKILL.md 的 YAML frontmatter 格式正确
4. 查看 init 事件中的 `skills` 字段是否包含你的 Skill

### Q: 中文显示为 \uXXXX 怎么办？

最新版本已修复，确保使用 `ensure_ascii=False` 序列化 JSON。

### Q: API 401 错误？

检查 `ANTHROPIC_API_KEY` 是否正确设置，SDK 子进程是否能访问该环境变量。

### Q: 如何调试 Skills 加载？

检查服务启动日志：
```
Loaded 2 skills from ./.claude/skills
```

查看 init 事件的 `skills` 字段：
```json
{
  "skills": ["Topic_Planning", "example"]
}
```

## 与 cc-agent-sdk 对比

| 功能 | cc-agent-sdk | 本实现 |
|------|--------------|--------|
| 语言 | TypeScript | Python |
| 框架 | Bun | FastAPI |
| Skills 加载 / 匹配 | ✅ | ✅ |
| SSE 流式响应 | ✅ | ✅（`eventMode` / `resultMode` 可配） |
| 会话管理 | ✅ | ✅（`memory` / `file` / `db`） |
| 中文支持 | ✅ | ✅ |
| API 端点 | `/agent-sdk/*` | `/agent-sdk/*` + `/skills/*` |
| RAG 知识库问答 | ❌ | ✅ `/rag/*` + `/agent-sdk/rag/stream` |
| 文档上传解析 | ❌ | ✅ local / MinerU |
| RAG MCP 工具 | ❌ | ✅ hybrid_search / read_chunk / list_sources / outline |
| Skills 管理 API | 无 | `/skills/*` CRUD |

## 开发

### 安装开发依赖

```bash
pip install -r requirements.txt
```

### 运行测试

```bash
pytest
```

### 代码格式化

```bash
black app/
ruff check app/
```

### RAG 流式接口与 `allowedTools`

RAG 流式问答**统一走 Claude Agent SDK + request-scoped in-process MCP**，由**接口路径**决定能力边界，**不再**通过 `RAG_AGENT_MODE` 等环境变量切换运行模式。

| 接口 | 用途 | 实现路径 | 服务端 `allowed_tools` |
|------|------|----------|------------------------|
| `POST /agent-sdk/rag/stream` | **推荐**：上传文件/知识库问答 + Skills | `RagAgentRunner.stream_claude_sdk` | `[]`（Skills 全开；RAG 经 `mcp_servers` 注入） |
| `POST /rag/agent/stream` | Legacy / 诊断（与上一行等价） | 同上 | `[]` |
| `POST /rag/stream` | 纯 RAG 调试（无 Skills 编排） | `stream_claude_sdk` | 仅 `rag_hybrid_search` 等四个 MCP 工具 |
| `POST /rag/query` | 非流式问答 | 服务端预检索 + `agent_service.query_stream` + MCP | 四个 RAG MCP 工具 |

说明：

- `app/services/rag/agent_runner.py` 中的 `stream_direct`（Anthropic-compatible `/v1/messages` tool loop）为**内部保留实现**，当前 **HTTP 路由未接入**；流式生产/调试入口均使用 `stream_claude_sdk`。
- `RAG_DIRECT_TIMEOUT_SECONDS` / `RAG_DIRECT_MAX_TOKENS` 仅在与 `stream_direct` 相关的测试或后续扩展时使用，不影响上述流式接口。

### RAG 文档解析器配置

RAG 上传解析由 `RAG_PARSER_PROVIDER` 决定，配置从 `.env` 读取：

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `RAG_PARSER_PROVIDER` | `local` | `local` 使用本地依赖解析 `.txt/.md/.pdf/.docx`；`mineru` 使用 Hybrid 路由，`.txt/.md` 本地解析，`.pdf/.docx` 调用 MinerU。 |
| `MINERU_BASE_URL` | 空 | MinerU 服务地址，例如 `https://mineru.internal.example`。仅 `RAG_PARSER_PROVIDER=mineru` 时需要。 |
| `MINERU_API_KEY` | 空 | MinerU Bearer Token；为空则不发送 `Authorization`。 |
| `MINERU_TIMEOUT_SECONDS` | `120` | 单文件 MinerU 解析超时。 |
| `MINERU_FALLBACK_TO_LOCAL` | `false` | MinerU 失败时是否回退本地 PDF/DOCX 解析。生产推荐 `false`，让单文件进入失败状态；开发可设为 `true`。 |
| `RAG_ALLOWED_EXTENSIONS` | `.txt,.md,.pdf,.docx` | 上传允许的扩展名；可显式收窄或扩展。 |

开发/本地默认配置：

```env
RAG_PARSER_PROVIDER=local
RAG_ALLOWED_EXTENSIONS=.txt,.md,.pdf,.docx
```

生产 MinerU 配置示例：

```env
RAG_PARSER_PROVIDER=mineru
MINERU_BASE_URL=https://mineru.internal.example
MINERU_API_KEY=
MINERU_TIMEOUT_SECONDS=120
MINERU_FALLBACK_TO_LOCAL=false
RAG_ALLOWED_EXTENSIONS=.txt,.md,.pdf,.docx
```

**`allowedTools` 语义（新版 Claude Agent SDK）**

- `[]`：Skills / 原生工具全开（**推荐显式传 `[]`**，不要依赖 `null`）。
- 非空数组：白名单，仅允许列出的工具。
- 未传 / `null`：进入服务后会归一化为 `[]`，效果与 `[]` 相同，但语义不清晰。

详细设计见 [docs/specs/rag-knowledge-qa.md](docs/specs/rag-knowledge-qa.md)；文档上传解析链路见 [docs/specs/rag-document-parsing.md](docs/specs/rag-document-parsing.md)。

### RAG + Agent 后续 TODO

- [ ] 为 `/agent-sdk/rag/stream` 增加可选的 Skills 白名单（例如 `allowedSkills`），在保持默认 `allowed_tools=[]` 的前提下，将范围收窄为前端显式传入的 Skills。

## 部署

### 部署检查清单

上线前逐项确认：

**必填环境变量**
- [ ] `ANTHROPIC_API_KEY` — Anthropic / 兼容 API 的密钥
- [ ] `ANTHROPIC_BASE_URL` — 若使用代理或第三方兼容接口需填写
- [ ] `ANTHROPIC_MODEL` — 指定模型，如 `claude-sonnet-4-6`
- [ ] `WORK_DIR` — 生产环境建议设为独立数据目录，如 `/data/ccsdk`

**Session 持久化（生产必须）**
- [ ] `SESSION_STORE=file`（单机）或 `SESSION_STORE=db`（多实例）
- [ ] `SESSION_FILE_PATH` — file 模式下持久化文件路径，需在 `WORK_DIR` 内
- [ ] `SESSION_DB_DSN` — db 模式下数据库连接串（db 模式尚待实现，见 TODO）

**用户数据隔离**
- [ ] `SESSION_ISOLATED_WORKDIR=true` — 推荐生产环境开启，每个会话独立目录
- [ ] 确认 `WORK_DIR` 目录有写权限

**安全**
- [ ] `AGENT_SDK_API_KEY` — 设置 API 认证密钥，否则接口无鉴权
- [ ] `GLOBAL_DISALLOWED_TOOLS` — 默认 `Write,Bash`；若 Skill 需要写文件，按需调整（如改为仅 `Bash`）

**RAG（启用知识库问答时）**
- [ ] `RAG_ENABLED=true`
- [ ] `RAG_STORAGE_DIR` — 与 `WORK_DIR` 一并挂载，避免容器重建丢索引
- [ ] `RAG_PARSER_PROVIDER=mineru` 时配置 `MINERU_BASE_URL` / `MINERU_API_KEY`
- [ ] `RAG_EMBEDDING_*` — 生产建议使用真实 embedding API，而非仅本地 hash

**Nginx（Skills 生成文件需要前端访问时必须）**
- [ ] 配置静态文件映射（见下方 Nginx 配置）
- [ ] 视频文件需支持 Range 请求

---

### 本机 / 裸机部署

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
vim .env   # 填写必填项

# 3. 启动服务（生产建议去掉 --reload）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 或后台运行
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > ccsdk.log 2>&1 &
```

### Docker

项目根目录已有 `Dockerfile`。构建时注意 Skills 目录：镜像内默认 `SKILLS_DIR=/app/skills`，生产建议挂载宿主机的 `.claude/skills`：

```bash
docker build -t ccsdk .

docker run -d \
  --name ccsdk \
  -p 8000:8000 \
  -v /data/ccsdk:/data/ccsdk \
  -v "$(pwd)/.claude/skills:/app/.claude/skills:ro" \
  -e SKILLS_DIR=/app/.claude/skills \
  -e ANTHROPIC_API_KEY=xxx \
  -e ANTHROPIC_BASE_URL=https://api.anthropic.com \
  -e ANTHROPIC_MODEL=claude-sonnet-4-6 \
  -e WORK_DIR=/data/ccsdk \
  -e SESSION_STORE=file \
  -e SESSION_FILE_PATH=/data/ccsdk/.claude/sessions.json \
  -e SESSION_ISOLATED_WORKDIR=true \
  -e AGENT_SDK_API_KEY=your-api-key \
  -e GLOBAL_DISALLOWED_TOOLS=Bash \
  -e RAG_ENABLED=true \
  -e RAG_STORAGE_DIR=/data/ccsdk/rag \
  ccsdk
```

> `-v /data/ccsdk:/data/ccsdk` 挂载数据目录，容器重启后 session 和生成文件均不丢失。

### Docker Compose

```yaml
version: "3.8"
services:
  ccsdk:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - /data/ccsdk:/data/ccsdk
    environment:
      ANTHROPIC_API_KEY: xxx
      ANTHROPIC_BASE_URL: https://api.anthropic.com
      ANTHROPIC_MODEL: claude-sonnet-4-6
      WORK_DIR: /data/ccsdk
      SESSION_STORE: file
      SESSION_FILE_PATH: /data/ccsdk/.claude/sessions.json
      SESSION_ISOLATED_WORKDIR: "true"
      AGENT_SDK_API_KEY: your-api-key
      GLOBAL_DISALLOWED_TOOLS: Bash
    restart: unless-stopped
```

```bash
docker-compose up -d
```

### Nginx 完整配置

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # ── 静态文件：Skills 生成的图片 / 视频 / 音频 ──────────────────
    location /outputs/ {
        alias /data/ccsdk/;              # 与 WORK_DIR 保持一致
        add_header Access-Control-Allow-Origin *;
        add_header Accept-Ranges bytes;  # 前端视频播放器需要 Range 支持
        # 防止 .json 等配置文件被访问
        location ~* \.(json|md|jsonl)$ {
            return 403;
        }
    }

    # ── API 反向代理 ────────────────────────────────────────────────
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # SSE 流式响应必须关闭缓冲
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;         # Skills 生成耗时较长，适当延长超时
    }
}
```

生成文件的访问 URL 格式：

```
# SESSION_ISOLATED_WORKDIR=true 时
http://your-domain.com/outputs/sessions/<conversationId>/assets/ref_portrait.jpg
http://your-domain.com/outputs/sessions/<conversationId>/output/final_video.mp4

# 前端传 cwd=/data/ccsdk/user-123/ 时
http://your-domain.com/outputs/user-123/assets/ref_portrait.jpg
```

---

## TODO

以下功能尚待实现，欢迎贡献：

### 高优先级

- [ ] **`db` Session 后端**：实现 `app/services/session.py` 中 `DbBackend` 的 4 个 TODO 方法（`load` / `save` / `delete` / `delete_many`），推荐使用 SQLAlchemy async + MySQL/PostgreSQL，适合多 Worker 生产部署
- [ ] **生成文件清理**：`SESSION_ISOLATED_WORKDIR=true` 时，会话过期后自动清理对应目录，避免磁盘无限增长；建议与 `cleanup_expired` 联动

### 中优先级

- [ ] **文件 URL 自动注入**：Claude 回复里的本地文件路径自动转换为可访问的 HTTP URL，无需前端手动拼接；需在 SSE 事件流里做路径替换
- [ ] **多 Worker 支持**：当前 `memory` / `file` 模式均不支持多进程共享，生产多 Worker 场景需先完成 `db` 后端
- [ ] **会话列表 API**：`GET /agent-sdk/sessions` 返回当前所有活跃会话及对应工作目录，便于运维排查

### 低优先级

- [ ] **Docker 镜像优化**：已有基础 `Dockerfile`，可补充多阶段构建、`.claude/skills` 挂载说明
- [ ] **Skills 热重载**：当前 Skills 在服务启动时加载，修改后需重启；支持 `POST /skills/reload` 热重载
- [ ] **`db` 后端迁移脚本**：提供建表 SQL 和迁移脚本，降低 `db` 模式接入成本

---

## 许可证

MIT

## 贡献

欢迎提交 Issue 和 Pull Request！

### 分支约定

- **`main`**：稳定分支，**禁止直接在 `main` 上提交或推送功能改动**
- **特性分支**（如 `rag`、`feature/xxx`）：在此开发、提交，经 Review 后合并到 `main`

推荐流程：

```bash
git checkout main && git pull
git checkout -b feature/your-change
# ... 开发与提交 ...
git checkout main && git merge feature/your-change
git push origin main
```
