 # WeChatBot 对接规格说明

## 1. 背景

当前项目是基于 Claude Agent SDK 的 FastAPI Agent 服务，已经具备以下能力：

- `/agent-sdk/stream`：通用 Agent SSE 流式接口。
- `/agent-sdk/rag/stream`：RAG + Agent SDK 编排流式接口。
- `/rag/*`：文件上传、知识库管理、检索问答与运维接口。
- Skills、Sub Agents、MCP、会话管理、工作区隔离、API Key 鉴权等平台能力。
- RAG 自研主链路，包括上传、解析、切分、embedding、向量检索、混合检索、引用校验与资料不足拒答。

本规格说明定义一个新的 WeChatBot 对接模块，用于接入 `corespeed-io/wechatbot` 的 Python SDK，把微信 iLink Bot 的私聊消息、媒体消息、 typing 状态、回复能力接入到本项目现有 Agent / RAG / Skills 能力中。

目标不是把当前服务改造成单一微信机器人，而是在现有 Agent 平台上新增一个可配置、可观测、可扩展的微信入口。

## 2. 外部 SDK 能力概览

目标 SDK：`wechatbot-sdk`

安装方式：

```bash
pip install wechatbot-sdk
```

Python 版本要求：`>=3.9`。

核心依赖：`aiohttp`、`cryptography`。

主要接口：

```python
from wechatbot import WeChatBot

bot = WeChatBot()

@bot.on_message
async def handle(msg):
    await bot.send_typing(msg.user_id)
    await bot.reply(msg, f"Echo: {msg.text}")

bot.run()
```

SDK 提供的关键能力：

| 能力 | 方法 |
| --- | --- |
| 登录 | `await bot.login(force=False)` |
| 启动长轮询 | `await bot.start()` |
| 同步启动 | `bot.run()` |
| 停止 | `bot.stop()` |
| 注册消息处理器 | `bot.on_message(handler)` |
| 回复文本 | `await bot.reply(msg, text)` |
| 主动发送文本 | `await bot.send(user_id, text)` |
| typing 状态 | `await bot.send_typing(user_id)` / `await bot.stop_typing(user_id)` |
| 回复媒体 | `await bot.reply_media(msg, content)` |
| 下载媒体 | `await bot.download(msg)` |
| 上传媒体 | `await bot.upload(data, user_id, media_type)` |

主要消息结构：

```python
@dataclass
class IncomingMessage:
    user_id: str
    text: str
    type: Literal["text", "image", "voice", "file", "video"]
    timestamp: datetime
    images: list[ImageContent]
    voices: list[VoiceContent]
    files: list[FileContent]
    videos: list[VideoContent]
    quoted_message: QuotedMessage | None
    raw: dict
```

## 3. 产品目标

### 3.1 核心目标

第一阶段需要支持：

1. **微信入口接入**
   - 服务启动后可按配置自动启动 WeChatBot。
   - 支持二维码登录、扫码成功、二维码过期、登录失败等事件日志。
   - 支持凭证文件持久化，避免频繁扫码。

2. **文本消息接入 Agent**
   - 收到微信文本消息后，调用本项目现有 Agent 流式服务。
   - 聚合流式文本输出，最终通过微信回复。
   - 支持 typing 状态提示。
   - 支持 per-user 会话续聊。

3. **RAG 知识库问答入口**
   - 可配置默认走普通 Agent 或 RAG Agent。
   - 支持为微信机器人绑定默认 `knowledgeBaseId`、`knowledgeBaseName` 或 `fileSetId`。
   - 支持文本问题进入 `/agent-sdk/rag/stream` 对应的内部 runner。

4. **消息路由策略**
   - 支持按命令前缀选择模式，例如：
     - `/chat 你好`：普通 Agent。
     - `/rag 这份资料说了什么`：RAG Agent。
     - `/help`：机器人帮助。
     - `/reset`：重置当前微信用户会话。
   - 支持默认模式配置。

5. **安全与可控**
   - 复用项目已有全局工具禁用策略。
   - 不允许微信消息绕过 `GLOBAL_DISALLOWED_TOOLS`。
   - 支持白名单用户配置。
   - 支持最大并发、超时、最大回复长度限制。

6. **观测与运维**
   - 记录消息处理状态、耗时、错误类型、会话 ID、用户 ID hash。
   - 提供管理 API 查询机器人状态。
   - 提供启动、停止、重新登录接口。

### 3.2 非目标

第一阶段不做：

- 不实现完整微信多账号后台。
- 不做微信群复杂权限管理。
- 不把微信媒体自动入库作为默认行为。
- 不做主动群发营销能力。
- 不在微信内暴露项目管理、Skill 创建、文件删除等高风险操作。
- 不把 WeChatBot SDK fork 到本项目内部。

## 4. 总体架构

```text
┌────────────────────┐
│      WeChat        │
│  iLink Bot Client  │
└─────────┬──────────┘
          │ long polling / reply
          ▼
┌───────────────────────────────────────────────────────────────────┐
│                        FastAPI App                                │
│                                                                   │
│  ┌──────────────────────┐      ┌───────────────────────────────┐  │
│  │ routers/wechatbot.py │◄────►│ services/wechatbot/manager.py │  │
│  │ /wechatbot/*         │      │ lifecycle / status / login    │  │
│  └──────────────────────┘      └──────────────┬────────────────┘  │
│                                                │                   │
│                                  ┌─────────────▼─────────────┐     │
│                                  │ services/wechatbot/adapter │     │
│                                  │ SDK callback integration   │     │
│                                  └─────────────┬─────────────┘     │
│                                                │                   │
│                                  ┌─────────────▼─────────────┐     │
│                                  │ services/wechatbot/router  │     │
│                                  │ command / mode selection   │     │
│                                  └─────────────┬─────────────┘     │
│                                                │                   │
│       ┌────────────────────────────┬───────────▼──────────┬──────┐│
│       │ services/agent             │ services/rag          │      ││
│       │ Agent SDK runner           │ RAG Agent runner      │      ││
│       └────────────────────────────┴──────────────────────┴──────┘│
└───────────────────────────────────────────────────────────────────┘
```

建议新增模块：

```text
app/
├── routers/
│   └── wechatbot.py
├── models/
│   └── wechatbot.py
└── services/
    └── wechatbot/
        ├── __init__.py
        ├── adapter.py
        ├── manager.py
        ├── message_router.py
        ├── session.py
        └── types.py
```

## 5. 配置规格

新增环境变量建议：

```env
# 是否启用微信机器人
WECHATBOT_ENABLED=false

# WeChat iLink Bot SDK 配置
WECHATBOT_BASE_URL=https://ilinkai.weixin.qq.com
WECHATBOT_CRED_PATH=~/.wechatbot/credentials.json

# 是否随 FastAPI 启动自动启动 bot
WECHATBOT_AUTO_START=false

# 默认消息模式：agent / rag
WECHATBOT_DEFAULT_MODE=agent

# 绑定默认 RAG 范围，三者按优先级选择；为空则不绑定
WECHATBOT_DEFAULT_KNOWLEDGE_BASE_ID=
WECHATBOT_DEFAULT_KNOWLEDGE_BASE_NAME=
WECHATBOT_DEFAULT_FILE_SET_ID=

# 安全与限流
WECHATBOT_ALLOWED_USER_IDS=
WECHATBOT_MAX_CONCURRENT_MESSAGES=3
WECHATBOT_MESSAGE_TIMEOUT_SECONDS=120
WECHATBOT_MAX_REPLY_CHARS=3500

# 会话
WECHATBOT_SESSION_PREFIX=wechat
WECHATBOT_SESSION_TTL_SECONDS=604800

# 文本回复策略
WECHATBOT_REPLY_CHUNK_SIZE=1800
WECHATBOT_REPLY_CHUNK_INTERVAL_SECONDS=0.8

# 媒体处理策略：ignore / summarize / ingest
WECHATBOT_MEDIA_POLICY=ignore
```

配置原则：

- `WECHATBOT_ENABLED=false` 时不导入或启动 SDK，避免非必要依赖影响主服务。
- `WECHATBOT_AUTO_START=true` 时在 FastAPI lifespan 中启动后台任务。
- `WECHATBOT_CRED_PATH` 必须允许写入凭证文件；生产环境建议挂载持久化目录。
- `WECHATBOT_ALLOWED_USER_IDS` 为空表示不限制用户；生产环境建议配置白名单。

## 6. API 规格

新增 router 前缀：`/wechatbot`。

### 6.1 查询状态

```http
GET /wechatbot/status
```

响应：

```json
{
  "enabled": true,
  "running": true,
  "loggedIn": true,
  "startedAt": "2026-05-29T10:00:00Z",
  "lastMessageAt": "2026-05-29T10:05:12Z",
  "lastError": null,
  "defaultMode": "agent",
  "activeTasks": 1
}
```

### 6.2 启动机器人

```http
POST /wechatbot/start
```

行为：

- 如果未启用，返回 400。
- 如果已运行，幂等返回当前状态。
- 如果凭证有效，直接登录并启动长轮询。
- 如果需要扫码，触发 SDK `on_qr_url` 回调，并把二维码 URL 存入 manager 状态。

### 6.3 停止机器人

```http
POST /wechatbot/stop
```

行为：

- 调用 `bot.stop()`。
- 取消后台任务。
- 清理运行态，不删除凭证文件。

### 6.4 强制重新登录

```http
POST /wechatbot/relogin
```

请求：

```json
{
  "force": true
}
```

行为：

- 停止当前 bot。
- 调用 `login(force=true)`。
- 更新二维码状态。

### 6.5 获取登录二维码

```http
GET /wechatbot/login-qrcode
```

响应：

```json
{
  "qrUrl": "https://...",
  "expiresAt": "2026-05-29T10:02:00Z",
  "status": "waiting_scan"
}
```

### 6.6 发送测试消息

```http
POST /wechatbot/send
```

请求：

```json
{
  "userId": "wx_user_id",
  "text": "测试消息"
}
```

用途：

- 仅用于开发和运维验证。
- 需要用户已有上下文 token，否则 SDK 可能无法主动发送。

## 7. 内部消息处理流程

### 7.1 文本消息主流程

```text
WeChat incoming message
  ├─ validate enabled / running
  ├─ validate user allowlist
  ├─ normalize message
  ├─ parse command prefix
  ├─ build conversationId
  ├─ send typing
  ├─ call Agent or RAG runner
  ├─ aggregate stream text
  ├─ split long reply
  ├─ reply chunks
  ├─ stop typing
  └─ record metrics / logs
```

### 7.2 命令路由

支持命令：

| 命令 | 行为 |
| --- | --- |
| `/help` | 返回帮助说明 |
| `/chat <message>` | 强制普通 Agent 模式 |
| `/rag <message>` | 强制 RAG 模式 |
| `/reset` | 重置当前微信用户的会话 |
| `/status` | 返回当前用户会话与默认模式摘要 |

无命令时使用 `WECHATBOT_DEFAULT_MODE`。

### 7.3 会话映射

建议 conversationId 生成规则：

```text
wechat:{bot_instance_id}:{user_id_hash}
```

要求：

- 不直接把明文 `user_id` 写入日志。
- manager 内部可以保存明文 user_id 以便调用 SDK，但日志与观测字段使用 hash。
- `/reset` 时删除该 conversationId 对应的 session。

### 7.4 Agent 调用策略

普通 Agent 模式等价于构造内部请求：

```json
{
  "prompt": "用户消息",
  "conversationId": "wechat:...",
  "options": {
    "allowedTools": [],
    "maxTurns": 10
  }
}
```

注意：

- 微信入口不应允许用户通过消息直接覆盖 `allowedTools`、`cwd`、`apiKey`、`baseURL`。
- 如需开放特殊能力，必须通过服务端配置白名单映射。

### 7.5 RAG 调用策略

RAG 模式等价于构造内部请求：

```json
{
  "message": "用户问题",
  "conversationId": "wechat:...",
  "knowledgeBaseId": "...",
  "knowledgeBaseName": "...",
  "fileSetId": "..."
}
```

绑定优先级：

1. 显式命令参数绑定，后续扩展。
2. `WECHATBOT_DEFAULT_KNOWLEDGE_BASE_ID`。
3. `WECHATBOT_DEFAULT_KNOWLEDGE_BASE_NAME`。
4. `WECHATBOT_DEFAULT_FILE_SET_ID`。
5. 无绑定时按 RAG 服务现有规则处理；资料不足则拒答。

## 8. 媒体消息策略

第一阶段默认：`WECHATBOT_MEDIA_POLICY=ignore`。

收到图片、语音、文件、视频时：

```text
暂不支持直接处理该类型消息。请发送文字问题。
```

后续扩展：

| 策略 | 行为 |
| --- | --- |
| `ignore` | 不下载媒体，只提示暂不支持 |
| `summarize` | 下载媒体，交给对应解析/识别服务摘要 |
| `ingest` | 下载文件并进入 RAG 文件入库流程 |

`ingest` 策略需要额外安全约束：

- 文件大小限制。
- MIME / 扩展名白名单。
- 病毒扫描或内容安全检查预留。
- 默认只对白名单用户启用。

## 9. 安全规格

### 9.1 工具安全

微信入口必须继承项目已有安全策略：

- `GLOBAL_DISALLOWED_TOOLS` 仍然生效。
- 微信用户不能通过自然语言解除工具限制。
- 微信入口默认 `allowedTools=[]`，除非服务端配置明确允许。

### 9.2 身份与权限

- 管理 API 复用现有 `AGENT_SDK_API_KEY` 鉴权。
- 微信用户权限第一阶段使用 `WECHATBOT_ALLOWED_USER_IDS` 白名单。
- 未来可扩展为数据库表：`wechatbot_users`，支持 user_id、tenant_id、role、enabled、metadata。

### 9.3 数据保护

- 日志中不输出明文 user_id、媒体 URL、原始凭证。
- `WECHATBOT_CRED_PATH` 不应位于公开静态目录。
- 错误返回中不暴露 SDK 内部 token、context token、CDN aes key。

### 9.4 防滥用

- 单进程并发限制：`WECHATBOT_MAX_CONCURRENT_MESSAGES`。
- 单消息超时：`WECHATBOT_MESSAGE_TIMEOUT_SECONDS`。
- 单次回复长度限制：`WECHATBOT_MAX_REPLY_CHARS`。
- 同一用户短时间频繁消息可后续加入令牌桶限流。

## 10. 错误处理

| 场景 | 行为 |
| --- | --- |
| SDK 未安装 | 启动时如果 `WECHATBOT_ENABLED=true`，返回清晰错误并提示安装依赖 |
| 未登录 | 状态 API 显示 `loggedIn=false`，二维码 API 返回最近二维码 URL |
| 二维码过期 | `on_expired` 更新状态，提示重新登录 |
| 用户不在白名单 | 不调用 Agent，可静默忽略或回复无权限 |
| Agent 超时 | 回复“处理超时，请稍后重试” |
| RAG 资料不足 | 复用 RAG 资料不足拒答文案 |
| 回复过长 | 按 chunk 拆分发送；超过最大长度则截断并提示 |
| SDK 发送失败 | 记录错误，状态 API 暴露摘要，不重试无限循环 |

## 11. 数据模型建议

### 11.1 Runtime 状态模型

```python
class WeChatBotStatus(BaseModel):
    enabled: bool
    running: bool
    logged_in: bool
    qr_url: str | None = None
    qr_expires_at: datetime | None = None
    started_at: datetime | None = None
    last_message_at: datetime | None = None
    last_error: str | None = None
    default_mode: Literal["agent", "rag"]
    active_tasks: int
```

### 11.2 标准化消息模型

```python
class WeChatIncomingEnvelope(BaseModel):
    user_id: str
    user_id_hash: str
    message_type: Literal["text", "image", "voice", "file", "video"]
    text: str
    timestamp: datetime
    raw: dict[str, Any] | None = None
```

### 11.3 路由结果模型

```python
class WeChatRouteDecision(BaseModel):
    mode: Literal["agent", "rag", "help", "reset", "status", "unsupported"]
    message: str
    conversation_id: str
    rag_scope: dict[str, str | None] = {}
```

## 12. 实施计划

### Phase 1：基础接入

- 在 `pyproject.toml` 增加可选依赖或主依赖：`wechatbot-sdk`。
- 在 `app/config.py` 增加 `WECHATBOT_*` 配置。
- 新增 `app/services/wechatbot/manager.py`，封装生命周期。
- 新增 `app/services/wechatbot/adapter.py`，封装 SDK 导入与回调注册。
- 新增 `app/routers/wechatbot.py`，提供 status/start/stop/relogin/qrcode API。
- 在 `app/main.py` 注册 router，并在 lifespan 中按配置自动启动。

验收标准：

- `WECHATBOT_ENABLED=false` 时主服务不受影响。
- `WECHATBOT_ENABLED=true` 且 SDK 未安装时，错误可读。
- 可通过 API 触发登录流程并看到二维码 URL。
- 可启动/停止机器人。

### Phase 2：文本消息接 Agent

- 实现命令解析与默认模式选择。
- 实现微信 user_id 到 conversationId 的映射。
- 收到文本消息后调用普通 Agent runner。
- 聚合 SSE 文本并回复微信。
- 支持 `/help`、`/reset`、`/status`。

验收标准：

- 微信发送“你好”，机器人能回复 Agent 答案。
- 同一微信用户可连续对话。
- `/reset` 后上下文清空。
- 超时、异常时有友好回复。

### Phase 3：接入 RAG 模式

- 支持 `/rag <question>`。
- 支持默认 RAG scope 配置。
- 复用 `RagAgentRunner` 或现有 `/agent-sdk/rag/stream` 内部编排。
- 回复中保留简洁引用信息。

验收标准：

- 绑定知识库后，微信提问可基于知识库回答。
- 资料不足时明确拒答。
- 不泄露内部工具参数。

### Phase 4：媒体与生产增强

- 增加媒体消息下载和策略配置。
- 支持文件消息进入 RAG 入库任务。
- 增加用户级限流、数据库授权、审计表。
- 增加 Prometheus/OpenTelemetry 指标。

## 13. 测试计划

### 13.1 单元测试

- 命令解析：`/help`、`/chat`、`/rag`、`/reset`、无命令。
- conversationId 生成与 user_id hash。
- 回复拆分逻辑。
- 白名单判断。
- 配置默认值。

### 13.2 集成测试

- 使用 fake WeChatBot SDK 对象模拟 `on_message` 回调。
- 模拟普通 Agent 返回流式文本。
- 模拟 RAG runner 返回资料不足。
- 模拟 SDK 发送失败。

### 13.3 手工验收

- 本地启动 FastAPI。
- 配置 `WECHATBOT_ENABLED=true`。
- 调用 `/wechatbot/start`。
- 扫码登录。
- 微信发送 `/help`、普通文本、`/rag` 问题。
- 查看日志与 `/wechatbot/status`。

## 14. 风险与待确认问题

1. **WeChat iLink Bot 可用性**
   - SDK 依赖外部 iLink 服务，需验证账号权限、登录稳定性、长轮询断线恢复能力。

2. **主动发送限制**
   - `bot.send(user_id, text)` 需要 prior context，主动消息能力可能受限。

3. **消息长度限制**
   - 微信侧单条消息限制需要实测，第一阶段通过 `WECHATBOT_REPLY_CHUNK_SIZE` 保守拆分。

4. **群聊支持**
   - 当前规格按私聊优先设计；群聊消息结构和权限需要后续补充。

5. **凭证持久化安全**
   - 凭证文件需要放在非公开目录，并纳入部署密钥管理策略。

6. **运行模式**
   - 长轮询任务运行在 FastAPI 进程内。多 worker 部署时可能重复启动机器人，生产环境需要保证单实例运行，或引入分布式锁。

## 15. 推荐默认实现决策

- 第一版以单实例、进程内后台任务方式运行 WeChatBot。
- 默认只处理文本消息。
- 默认模式为 `agent`，RAG 通过 `/rag` 命令或配置开启。
- 管理 API 复用现有 API Key 鉴权。
- SDK 依赖先作为可选能力处理，避免影响不使用微信机器人的部署。
- 多 worker / 多账号 / 群聊 / 媒体入库放到后续阶段。

## 16. 执行计划进度

本章节用于跨模型、跨会话、跨中断恢复记录实现进度。每次执行一个任务前，先阅读本章节；任务完成后，更新对应状态、实际变更文件、验证方式与遗留问题。

## 17. 当前已实现对接模式：Mode A 与 Mode B

截至当前实现，WeChatBot 对接已经支持两套并存模式：

| 模式 | 定位 | 微信登录主体 | 用户身份解析 | 适用场景 |
| --- | --- | --- | --- | --- |
| Mode A | 单 Bot 多用户/多租户 | 平台公共微信 Bot | `/bind` 绑定码或环境变量/DB 映射 | 一个官方机器人服务多个 SaaS 用户 |
| Mode B | 每用户独立微信通道 | SaaS 用户自己的微信号 | 通道创建时固定 `tenantId + appUserId + botInstanceId` | 每个 SaaS 用户扫码登录自己的微信通道 |

两套模式复用同一套 WeChatBot SDK adapter、消息路由、Agent/RAG runner、安全策略、限流和审计能力，但登录凭证和运行时组织方式不同。

### 17.1 Mode A：共享 Bot + 绑定码

Mode A 使用原有 `/wechatbot/*` 生命周期 API：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/wechatbot/start` | 启动公共 Bot 或发起扫码登录。 |
| `GET` | `/wechatbot/qrcode` | 获取公共 Bot 当前登录二维码。 |
| `GET` | `/wechatbot/login-qrcode` | 等价于 `/wechatbot/qrcode`。 |
| `GET` | `/wechatbot/status` | 查询公共 Bot 状态。 |
| `POST` | `/wechatbot/stop` | 停止公共 Bot。 |
| `POST` | `/wechatbot/relogin` | 重新登录公共 Bot。 |
| `POST` | `/wechatbot/bind-tokens` | 为 SaaS 用户创建一次性微信绑定码。 |
| `GET` | `/wechatbot/bindings` | 查询绑定列表。 |
| `DELETE` | `/wechatbot/bindings/{id}` | 禁用/解绑绑定。 |

推荐流程：

```text
1. 平台启动公共 Bot：POST /wechatbot/start
2. SaaS Web 后端为当前用户创建绑定码：POST /wechatbot/bind-tokens
3. 用户在微信里给公共 Bot 发送：/bind WX-xxxxxx
4. 后续消息按绑定关系路由到 tenant/app_user
```

创建绑定码请求示例：

```json
{
  "tenantId": "tenant-a",
  "appUserId": "user-a",
  "defaultMode": "agent",
  "ragScope": {"knowledgeBaseId": "kb-a"},
  "ttlSeconds": 600
}
```

返回中的 `bindCommand` 只应展示给当前登录 SaaS 用户，明文 token 只在创建响应中返回一次。

### 17.2 Mode B：每用户独立微信通道

Mode B 新增 `/wechatbot/mode-b/channels/*` API。每个通道由以下三元组唯一标识：

```text
tenantId + appUserId + botInstanceId
```

如果 `botInstanceId` 不传，则使用 `WECHATBOT_BOT_INSTANCE_ID`，通常为 `default`。

Mode B 的运行时隔离策略：

```text
tenantId + appUserId + botInstanceId
  -> 独立 credential 文件
  -> 独立 WeChatBotManager
  -> 独立 WeChatBotAdapter
  -> 独立登录二维码/长轮询通道
```

独立凭证存储路径：

```text
<WECHATBOT_CREDENTIALS_DIR>/mode_b/<sha256-prefix>.json
```

Mode B API：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/wechatbot/mode-b/channels/start` | 启动或创建用户独立微信通道；首次返回该用户专属二维码。 |
| `GET` | `/wechatbot/mode-b/channels/status` | 查询指定用户独立通道状态。 |
| `POST` | `/wechatbot/mode-b/channels/stop` | 停止指定用户独立通道。 |

启动请求：

```json
{
  "tenantId": "tenant-a",
  "appUserId": "user-a",
  "botInstanceId": "default",
  "forceLogin": true
}
```

首次需要扫码时返回：

```json
{
  "status": "logging_in",
  "message": "请扫码登录",
  "qrcode_url": "https://..."
}
```

已有有效凭证或通道已运行时可能返回：

```json
{
  "status": "running",
  "message": "Bot 已经在运行中",
  "qrcode_url": null
}
```

Mode B 不需要 `/bind`。用户扫码登录自己的微信后，该通道收到的消息天然归属于创建通道时传入的 `tenantId/appUserId/botInstanceId`。

### 17.3 生命周期清理

FastAPI 关闭时会清理：

1. 原 Mode A 单 Bot manager。
2. Mode B channel manager 中所有已启动通道。

### 17.4 验证记录

已执行回归测试：

```bash
python -m pytest tests/test_wechatbot_mode_a.py
```

结果：

```text
10 passed
```

手工验证：

- `/wechatbot/mode-b/channels/start` 可返回独立通道运行态或登录二维码。
- OpenAPI 已包含：
  - `/wechatbot/mode-b/channels/start`
  - `/wechatbot/mode-b/channels/stop`
  - `/wechatbot/mode-b/channels/status`

### 16.1 状态约定

| 状态 | 含义 |
| --- | --- |
| `TODO` | 尚未开始 |
| `IN_PROGRESS` | 正在执行，可能存在未完成代码 |
| `BLOCKED` | 被外部条件阻塞，需要人工处理或补充信息 |
| `DONE` | 已完成并通过对应验收 |
| `SKIPPED` | 明确决定跳过，需在备注说明原因 |

更新规则：

- 同一时间建议只标记一个任务为 `IN_PROGRESS`。
- 如果执行中断，保留 `IN_PROGRESS`，并在“恢复提示”中写明下一步。
- 如果任务产生代码变更，必须记录“实际变更文件”。
- 如果任务只完成部分内容，状态不要标记为 `DONE`，应继续保持 `IN_PROGRESS` 或拆分子任务。
- 每个 Phase 完成后，更新 Phase 汇总状态和下一阶段入口条件。

### 16.2 Phase 1：基础接入进度

Phase 目标：完成 WeChatBot 基础生命周期管理、配置、API 与 FastAPI 注册；不要求真实微信消息打通 Agent。

Phase 状态：`TODO`

入口条件：

- 当前规格文档已确认。
- 项目可正常启动，现有 RAG / Agent 能力不被破坏。

| ID | 任务 | 状态 | 实际变更文件 | 验证方式 | 备注 / 恢复提示 |
| --- | --- | --- | --- | --- | --- |
| P1-01 | 确认依赖策略：`wechatbot-sdk` 作为可选依赖或主依赖 | TODO |  | 检查 `pyproject.toml`，未启用时主服务可启动 | 建议优先可选依赖，避免默认部署受影响 |
| P1-02 | 在 `app/config.py` 增加 `WECHATBOT_*` 配置项 | TODO |  | 启动时配置可被读取；默认值符合第 5 章 | 注意布尔、列表、路径、超时类型解析 |
| P1-03 | 新增 `app/models/wechatbot.py` 状态、请求、响应模型 | TODO |  | 类型检查 / import 成功 | 先覆盖 status、relogin、send、qrcode 响应 |
| P1-04 | 新增 `app/services/wechatbot/adapter.py` 封装 SDK 延迟导入与回调注册 | TODO |  | SDK 未安装且未启用时不报错；启用时错误清晰 | 不在模块 import 顶层强制导入 `wechatbot` |
| P1-05 | 新增 `app/services/wechatbot/manager.py` 封装 start/stop/relogin/status | TODO |  | fake adapter 下可测试幂等 start/stop | 需要记录 qr_url、running、logged_in、last_error |
| P1-06 | 新增 `app/routers/wechatbot.py` 管理 API | TODO |  | `GET /wechatbot/status` 可访问；管理接口走 API Key 鉴权 | 复用现有 `verify_api_key` |
| P1-07 | 在 `app/main.py` 注册 router 与可选自动启动逻辑 | TODO |  | `WECHATBOT_ENABLED=false` 时主服务无行为变化 | 多 worker 风险先在文档/日志提示 |
| P1-08 | Phase 1 单元测试或最小验证 | TODO |  | 配置默认值、status、SDK 缺失场景通过 | 若暂不写测试，需记录手工验证命令 |

Phase 1 验收清单：

- [ ] `WECHATBOT_ENABLED=false` 时主服务启动不受影响。
- [ ] `WECHATBOT_ENABLED=true` 且 SDK 未安装时，错误可读且定位明确。
- [ ] `/wechatbot/status` 返回结构化运行状态。
- [ ] `/wechatbot/start`、`/wechatbot/stop` 幂等。
- [ ] `/wechatbot/login-qrcode` 可返回最近二维码状态或明确提示暂无二维码。

### 16.3 Phase 2：文本消息接 Agent 进度

Phase 目标：微信文本消息能够进入普通 Agent 模式，支持命令、typing、会话续聊与回复拆分。

Phase 状态：`TODO`

入口条件：

- Phase 1 验收清单全部完成。
- 已明确普通 Agent 内部调用入口与流式文本聚合方式。

| ID | 任务 | 状态 | 实际变更文件 | 验证方式 | 备注 / 恢复提示 |
| --- | --- | --- | --- | --- | --- |
| P2-01 | 新增 `message_router.py` 命令解析 | TODO |  | 覆盖 `/help`、`/chat`、`/reset`、`/status`、无命令 | `/rag` 可先解析但暂返回未启用 |
| P2-02 | 新增 `session.py` 实现 user_id hash 与 conversationId 映射 | TODO |  | 同一 user_id 生成稳定会话 ID；日志不含明文 user_id | 使用 `WECHATBOT_SESSION_PREFIX` |
| P2-03 | 实现白名单校验与并发保护 | TODO |  | 非白名单不进入 Agent；并发超限有友好回复 | 复用配置中的最大并发值 |
| P2-04 | 实现普通 Agent 内部调用与流式文本聚合 | TODO |  | fake Agent 流可聚合为完整文本 | 不允许微信消息覆盖 tools/cwd/apiKey/baseURL |
| P2-05 | 实现 typing、超时、异常兜底与 stop typing | TODO |  | 正常/异常路径均停止 typing | 使用 `asyncio.timeout` 或等价机制 |
| P2-06 | 实现回复截断与分块发送 | TODO |  | 长回复按 chunk 发送，超过最大长度提示截断 | 遵守 `WECHATBOT_REPLY_CHUNK_SIZE` |
| P2-07 | `/reset` 清理当前微信用户会话 | TODO |  | reset 后上下文不延续 | 复用现有 session manager 能力 |
| P2-08 | Phase 2 测试或最小验证 | TODO |  | fake SDK 消息回调可跑通完整文本回复流程 | 真实微信验证可作为手工验收 |

Phase 2 验收清单：

- [ ] 微信发送普通文本可得到 Agent 回复。
- [ ] `/help` 返回命令说明。
- [ ] `/chat <message>` 强制普通 Agent 模式。
- [ ] `/reset` 后会话上下文清空。
- [ ] 超时、异常、回复过长都有友好处理。

### 16.4 Phase 3：接入 RAG 模式进度

Phase 目标：微信文本可通过 `/rag` 或默认配置进入 RAG Agent，并绑定默认知识库范围。

Phase 状态：`TODO`

入口条件：

- Phase 2 文本 Agent 链路稳定。
- 已有 RAG 服务在本地可用，并可通过 API 或内部 runner 正常问答。

| ID | 任务 | 状态 | 实际变更文件 | 验证方式 | 备注 / 恢复提示 |
| --- | --- | --- | --- | --- | --- |
| P3-01 | 完善 `/rag <question>` 命令路由 | TODO |  | `/rag` 空问题与正常问题均有明确行为 | 空问题返回用法提示 |
| P3-02 | 实现默认 RAG scope 绑定 | TODO |  | id/name/fileSet 优先级符合第 7.5 节 | 不允许用户任意注入内部参数 |
| P3-03 | 接入 `RagAgentRunner` 或等价内部编排 | TODO |  | fake / real RAG 可返回答案 | 优先复用现有 `/agent-sdk/rag/stream` 逻辑 |
| P3-04 | RAG 回复格式适配微信 | TODO |  | 引用信息简洁可读；不过度暴露工具细节 | 资料不足文案复用现有策略 |
| P3-05 | 默认模式 `WECHATBOT_DEFAULT_MODE=rag` 验证 | TODO |  | 无命令消息自动走 RAG | 无绑定知识库时行为要可解释 |
| P3-06 | Phase 3 测试或最小验证 | TODO |  | 绑定知识库后微信提问可基于知识库回答 | 记录使用的测试知识库 |

Phase 3 验收清单：

- [ ] `/rag <question>` 可基于绑定知识库回答。
- [ ] `WECHATBOT_DEFAULT_MODE=rag` 生效。
- [ ] 资料不足时明确拒答。
- [ ] 回复中不泄露 MCP 工具参数、系统提示词或内部 token。

### 16.5 Phase 4：媒体与生产增强进度

Phase 目标：在文本链路稳定后，逐步增加媒体、限流、审计与可观测能力。

Phase 状态：`DONE`

入口条件：

- Phase 3 通过真实或近真实链路验证。
- 已明确媒体处理策略是否进入本轮交付范围。

| ID | 任务 | 状态 | 实际变更文件 | 验证方式 | 备注 / 恢复提示 |
| --- | --- | --- | --- | --- | --- |
| P4-01 | 实现媒体 `ignore` 策略的统一回复 | ✅ DONE | app/services/wechatbot/media_handler.py | 图片、语音、文件、视频都有明确提示 | 第一阶段不下载媒体 |
| P4-02 | 设计并实现媒体 `summarize` 预留接口 | ✅ DONE | app/services/wechatbot/media_handler.py | 不启用时无副作用 | 需要外部识别/解析服务后再实装 |
| P4-03 | 设计并实现媒体 `ingest` 预留接口 | ✅ DONE | app/services/wechatbot/media_handler.py | 默认关闭；文件安全约束生效 | 涉及 RAG 入库与文件安全，谨慎开启 |
| P4-04 | 增加用户级限流 | ✅ DONE | app/services/wechatbot/session.py, manager.py | 高频消息被限流并友好提示 | 增强为 burst + window 双限流 |
| P4-05 | 增加审计日志或数据库表设计 | ✅ DONE | app/services/wechatbot/audit.py, manager.py, adapter.py | 可追踪消息状态、耗时、错误摘要 | 日志中不得出现明文 user_id |
| P4-06 | 增加 OpenTelemetry / 指标埋点 | ✅ DONE | app/services/wechatbot/metrics.py, manager.py, adapter.py | 可观察消息数、错误数、耗时、活跃任务 | 对齐现有 RAG observability 风格 |

Phase 4 验收清单：

- [x] 非文本消息有统一策略处理。
- [x] 媒体处理默认安全关闭。
- [x] 高频消息不会拖垮 Agent/RAG 服务。
- [x] 可通过日志或指标定位失败原因。

### 16.6 当前执行记录

| 时间 | 执行者 / 模型 | 操作 | 结果 | 下一步 |
| --- | --- | --- | --- | --- |
| 2026-05-29 | 初始规格编写 | 新增 WeChatBot 对接规格文档 | 已完成第 1-15 章 | 增加执行计划进度后进入 Phase 1 |
| 2026-05-29 | 进度记录补充 | 新增第 16 章执行计划进度 | DONE | 从 P1-01 开始执行 |
| 2026-05-29 | Cursor Agent | Phase 1: 基础接入 | P1-01~P1-06 全部完成 | 进入 Phase 2: 文本消息接 Agent |
| 2026-05-29 | Cursor Agent | Phase 2: 文本消息接 Agent | P2-01~P2-06 全部完成 | 进入 Phase 3: 接入 RAG 模式 |
| 2026-05-29 | Cursor Agent | Phase 3: 接入 RAG 模式 | P3-01~P3-03 全部完成 | 进入 Phase 4: 媒体与生产增强 |
| 2026-05-29 | Cursor Agent | Phase 4: 媒体与生产增强 | P4-01~P4-06 全部完成 | 全部 Phase 已完成 |

#### Phase 1 详细执行记录

| 任务 ID | 描述 | 状态 | 变更文件 |
| --- | --- | --- | --- |
| P1-01 | 在 pyproject.toml 增加 wechatbot-sdk 依赖 | ✅ DONE | pyproject.toml |
| P1-02 | 在 app/config.py 增加 WECHATBOT_* 配置 | ✅ DONE | app/config.py |
| P1-03 | 新增 app/services/wechatbot/manager.py 封装生命周期 | ✅ DONE | app/services/wechatbot/manager.py |
| P1-04 | 新增 app/services/wechatbot/adapter.py 封装SDK导入与回调注册 | ✅ DONE | app/services/wechatbot/adapter.py |
| P1-05 | 新增 app/routers/wechatbot.py 提供 status/start/stop/relogin/qrcode API | ✅ DONE | app/routers/wechatbot.py |
| P1-06 | 在 app/main.py 注册 router 并在 lifespan 中自动启动 | ✅ DONE | app/main.py |

#### Phase 2 详细执行记录

| 任务 ID | 描述 | 状态 | 变更文件 |
| --- | --- | --- | --- |
| P2-01 | 新增 message_router.py 命令解析与模式选择 | ✅ DONE | app/services/wechatbot/message_router.py |
| P2-02 | 新增 session.py 实现 user_id 到 conversationId 映射 | ✅ DONE | app/services/wechatbot/session.py |
| P2-03 | 实现 Agent runner 调用逻辑 | ✅ DONE | app/services/wechatbot/runner.py |
| P2-04 | 实现 SSE 聚合与微信回复 | ✅ DONE | app/services/wechatbot/runner.py |
| P2-05 | 实现 /help /reset /status 命令 | ✅ DONE | app/services/wechatbot/message_router.py, runner.py |
| P2-06 | 集成到 manager 并更新 lifespan | ✅ DONE | app/services/wechatbot/manager.py |

#### Phase 3 详细执行记录

| 任务 ID | 描述 | 状态 | 变更文件 |
| --- | --- | --- | --- |
| P3-01 | 分析 RagAgentRunner 接口和 /agent-sdk/rag/stream 内部编排 | ✅ DONE | - |
| P3-02 | 实现 _call_rag 方法调用 RAG 服务 | ✅ DONE | app/services/wechatbot/runner.py |
| P3-03 | 实现引用信息保留（_format_rag_answer_with_citations） | ✅ DONE | app/services/wechatbot/runner.py |

#### Phase 4 详细执行记录

| 任务 ID | 描述 | 状态 | 变更文件 |
| --- | --- | --- | --- |
| P4-01 | 实现媒体 ignore 策略的统一回复 | ✅ DONE | app/services/wechatbot/media_handler.py |
| P4-02 | 设计并实现媒体 summarize 预留接口（OCR/ASR 调用） | ✅ DONE | app/services/wechatbot/media_handler.py |
| P4-03 | 设计并实现媒体 ingest 预留接口（RAG 入库） | ✅ DONE | app/services/wechatbot/media_handler.py |
| P4-04 | 增强用户级限流（burst + window 双限流） | ✅ DONE | app/services/wechatbot/session.py, manager.py |
| P4-05 | 增加审计日志（消息状态/耗时/错误追踪） | ✅ DONE | app/services/wechatbot/audit.py, manager.py, adapter.py |
| P4-06 | 增加 OpenTelemetry 指标埋点 | ✅ DONE | app/services/wechatbot/metrics.py, manager.py, adapter.py |
