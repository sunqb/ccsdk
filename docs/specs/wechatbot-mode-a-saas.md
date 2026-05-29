# WeChatBot Mode A SaaS 规格：单 Bot 多用户/多租户

## 1. 背景与目标

Mode A 使用一套 WeChatBot 登录凭证和一个微信机器人账号服务多个 SaaS 用户。微信侧只提供 `user_id`，后端需要将其解析为平台内的 `tenant_id` 与 `app_user_id`，再把消息路由到对应的 Agent/RAG 会话、知识库范围和租户工作目录。

本规格将 Mode A 分为两层：

| 模式 | 定位 | 适用场景 |
| --- | --- | --- |
| Mode A-1：环境变量映射 | fallback / 开发 / 紧急兜底 | 内测、少量固定用户、生产应急覆盖 |
| Mode A-2：数据库自动绑定 | 推荐主路径 | 多用户 SaaS、用户自助绑定、规模化运营 |

最终目标是：**所有 SaaS 用户共享同一个微信机器人入口，但通过自动绑定流程在后端完成微信身份到系统租户/用户的映射**，避免管理员维护 `.env` 中的用户映射。

## 2. 非目标

- 不支持每个租户独立微信账号或独立扫码登录；该能力属于后续 Mode B。
- 不支持多 Bot 运行时调度、分布式锁、跨进程 Bot 迁移。
- 不把微信侧 `user_id` 明文写入日志、指标、审计记录、数据库绑定表或 `conversation_id`。
- 不允许微信消息覆盖租户绑定的 RAG scope、工作目录、工具白名单、API Key 或模型网关参数。
- 不在微信内暴露 Skill 创建、文件删除、项目管理、批量营销群发等高风险操作。
- 不依赖微信昵称、备注名、手机号等不稳定字段进行租户鉴权。

## 3. 当前实现状态

当前代码已包含 Mode A-1 的核心实现：

- `app/services/wechatbot/tenant.py`：环境变量租户解析、`user_id` 哈希、租户上下文模型。
- `app/services/wechatbot/message_router.py`：命令解析、`conversation_id` 生成、默认模式与 RAG scope 绑定。
- `app/services/wechatbot/session.py`：内存会话、租户元数据、限流计数；已按 `tenant_id:bot_instance_id:user_id_hash` 隔离。
- `app/services/wechatbot/runner.py`：调用普通 Agent 或 RAG runner，并传入 `space_id=tenant_id`。
- `app/services/wechatbot/manager.py`：Bot 生命周期、消息调度、租户上下文解析、并发控制。
- `app/services/wechatbot/adapter.py`：SDK 回调接入；文本与媒体入口均使用租户化 `conversation_id`。
- `app/services/wechatbot/audit.py` 与 `metrics.py`：审计日志和 OpenTelemetry 指标，默认使用脱敏用户标识。
- `app/routers/wechatbot.py`：管理 API，复用 `AGENT_SDK_API_KEY` 鉴权。
- `tests/test_wechatbot_mode_a.py`：Mode A 身份解析、会话隔离和 manager 传递上下文的回归测试。

下一阶段需要实现 Mode A-2：数据库自动绑定与自助绑定命令。

## 4. 总体身份模型

### 4.1 解析链路

```text
微信用户 user_id
  -> user_id_hash = sha256(user_id)[:16]
  -> bot_instance_id
  -> 绑定记录 e_wechatbot_user_binding
  -> tenant_id
  -> app_user_id
  -> default_mode
  -> rag_scope
  -> conversation_id = wechat:{tenant_id}:{bot_instance_id}:{user_id_hash}
  -> space_id = tenant_id
```

说明：

- `user_id` 明文只允许在运行时内存中用于调用 WeChatBot SDK。
- `user_id_hash` 用于日志、审计、指标、会话 ID、数据库绑定表和生产映射 key。
- `tenant_id` 是 SaaS 租户边界，也是 Agent 工作目录隔离的默认 `space_id`。
- `app_user_id` 是当前微信身份绑定的系统用户 ID。
- `bot_instance_id` 当前 Mode A 默认为单实例，但必须进入绑定和会话维度，为 Mode B 预留。

### 4.2 解析优先级

`resolve_tenant_context(user_id)` 应按以下顺序解析：

1. **数据库绑定表**：查 `e_wechatbot_user_binding` 中 `bot_instance_id + user_id_hash + status=1` 的记录。
2. **环境变量 fallback**：查 `WECHATBOT_USER_TENANT_MAP`，兼容 Mode A-1。
3. **默认租户 fallback**：当 `WECHATBOT_REQUIRE_USER_TENANT=false` 时，归属 `WECHATBOT_DEFAULT_TENANT_ID`。
4. **拒绝处理**：当 `WECHATBOT_REQUIRE_USER_TENANT=true` 且未绑定时，返回未绑定提示。

生产 SaaS 推荐：

```env
WECHATBOT_BINDING_STORE=db
WECHATBOT_REQUIRE_USER_TENANT=true
```

开发或灰度可使用：

```env
WECHATBOT_BINDING_STORE=env
WECHATBOT_REQUIRE_USER_TENANT=false
```

## 5. Mode A-2 自动绑定流程

### 5.1 用户体验

1. 用户登录 SaaS Web 系统。
2. 用户进入“绑定微信机器人”页面。
3. 后端生成短期绑定码，例如：`WX-8K3P2Q`。
4. 页面提示用户添加同一个微信机器人，并发送：`/bind WX-8K3P2Q`。
5. 微信机器人收到 `/bind` 后，根据绑定码自动写入绑定表。
6. 后续用户直接发送问题，后端自动识别其 `tenant_id/app_user_id/rag_scope`。

### 5.2 绑定码生命周期

```text
create token -> pending -> used/expired/revoked
```

约束：

- token 默认有效期建议 10 分钟，可配置。
- token 必须一次性使用，绑定成功后写入 `used_time`。
- token 不应在日志中完整输出；最多输出后 4 位或 hash。
- token 应具备足够随机性，避免被枚举。
- 同一用户短时间内生成多个 token 时，旧 token 可自动作废。

### 5.3 未绑定用户行为

当 `WECHATBOT_REQUIRE_USER_TENANT=true` 且用户未绑定：

- `/bind <code>`：允许执行绑定。
- `/help`：允许返回帮助，并提示先绑定。
- `/me`：允许返回“未绑定”。
- 其他消息：不调用 Agent/RAG，返回绑定指引。

推荐文案：

```text
你还没有绑定系统账号。
请先登录 Web 系统生成微信绑定码，然后发送：/bind 绑定码
```

## 6. 数据模型设计

### 6.1 e_wechatbot_user_binding

用于持久化微信身份与 SaaS 身份的绑定关系。

```sql
CREATE TABLE e_wechatbot_user_binding (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  bot_instance_id VARCHAR(128) NOT NULL,
  user_id_hash VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(128) NOT NULL,
  app_user_id VARCHAR(128) NOT NULL,
  default_mode VARCHAR(32) DEFAULT NULL,
  rag_scope_json JSON DEFAULT NULL,
  status SMALLINT NOT NULL DEFAULT 1,
  bind_source VARCHAR(32) NOT NULL DEFAULT 'token',
  last_seen_time DATETIME DEFAULT NULL,
  unbound_time DATETIME DEFAULT NULL,
  create_by VARCHAR(64) DEFAULT NULL,
  create_time DATETIME NOT NULL,
  update_by VARCHAR(64) DEFAULT NULL,
  update_time DATETIME NOT NULL,
  is_delete SMALLINT NOT NULL DEFAULT 1,
  KEY idx_wechat_binding (bot_instance_id, user_id_hash)
);
```

| 字段 | 说明 |
| --- | --- |
| `bot_instance_id` | Bot 实例 ID；Mode A 默认 `default`。 |
| `user_id_hash` | `sha256(user_id)[:16]`。 |
| `tenant_id` | SaaS 租户 ID。 |
| `app_user_id` | SaaS 应用用户 ID。 |
| `default_mode` | 可选，`agent` 或 `rag`；为空时使用全局默认模式。 |
| `rag_scope_json` | 可选，用户级 RAG scope；优先级高于租户级配置。 |
| `status` | 状态，1：启用，2：解绑/禁用。 |
| `bind_source` | `token`、`admin`、`import` 等。 |
| `last_seen_time` | 最近一次收到该微信用户消息时间。 |
| `unbound_time` | 软解绑时间。 |
| `create_by` | 创建人。 |
| `create_time` | 创建时间。 |
| `update_by` | 更新人。 |
| `update_time` | 更新时间。 |
| `is_delete` | 是否删除，1：正常，2：删除。 |

### 6.2 e_wechatbot_bind_token

用于 Web 系统生成短期绑定码。

```sql
CREATE TABLE e_wechatbot_bind_token (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  token_hash VARCHAR(128) NOT NULL,
  token_preview VARCHAR(16) NOT NULL,
  tenant_id VARCHAR(128) NOT NULL,
  app_user_id VARCHAR(128) NOT NULL,
  bot_instance_id VARCHAR(128) NOT NULL,
  default_mode VARCHAR(32) DEFAULT NULL,
  rag_scope_json JSON DEFAULT NULL,
  expires_time DATETIME NOT NULL,
  used_time DATETIME DEFAULT NULL,
  revoked_time DATETIME DEFAULT NULL,
  used_by_user_id_hash VARCHAR(64) DEFAULT NULL,
  create_by VARCHAR(64) DEFAULT NULL,
  create_time DATETIME NOT NULL,
  update_by VARCHAR(64) DEFAULT NULL,
  update_time DATETIME NOT NULL,
  is_delete SMALLINT NOT NULL DEFAULT 1
);
```

| 字段 | 说明 |
| --- | --- |
| `token_hash` | 绑定码大写归一化后的 sha256 哈希，不保存明文绑定码。 |
| `token_preview` | 绑定码预览，用于管理端展示，如后6位。 |
| `tenant_id` | SaaS 租户ID。 |
| `app_user_id` | SaaS 应用用户ID。 |
| `bot_instance_id` | 机器人实例ID。 |
| `default_mode` | 默认路由模式，可选 `agent` 或 `rag`。 |
| `rag_scope_json` | 绑定成功后写入用户绑定记录的 RAG 作用域 JSON。 |
| `expires_time` | 绑定码过期时间。 |
| `used_time` | 绑定码使用时间。 |
| `revoked_time` | 绑定码撤销时间。 |
| `used_by_user_id_hash` | 使用该绑定码的微信 user_id 哈希前16位。 |
| `create_by` | 创建人。 |
| `create_time` | 创建时间。 |
| `update_by` | 更新人。 |
| `update_time` | 更新时间。 |
| `is_delete` | 是否删除，1：正常，2：删除。 |

说明：

- 数据库只保存 `token_hash`，不保存明文 token。
- `token_preview` 用于管理端展示，例如 `8K3P2Q`，不能用于验证。
- `/bind <code>` 时计算 code 的 hash，再查表验证。

## 7. 绑定 Store 抽象

新增服务建议：

```text
app/services/wechatbot/binding_store.py
```

核心接口：

```python
class WeChatBindingStore:
    async def get_binding(bot_instance_id: str, user_id_hash: str) -> WeChatUserBinding | None: ...
    async def create_bind_token(tenant_id: str, app_user_id: str, ...) -> BindTokenCreated: ...
    async def bind_with_token(bot_instance_id: str, user_id_hash: str, token: str) -> WeChatUserBinding: ...
    async def unbind(bot_instance_id: str, user_id_hash: str) -> bool: ...
    async def touch_last_seen(bot_instance_id: str, user_id_hash: str) -> None: ...
```

实现分层：

| Store | 用途 |
| --- | --- |
| `EnvWeChatBindingStore` | 兼容 `WECHATBOT_USER_TENANT_MAP`。 |
| `DbWeChatBindingStore` | 生产主路径。 |
| `CompositeWeChatBindingStore` | 先 DB 后 env fallback。 |

## 8. 微信命令设计

| 命令 | 是否需要已绑定 | 行为 |
| --- | --- | --- |
| `/bind <code>` | 否 | 使用绑定码绑定当前微信用户。 |
| `/unbind` | 是 | 解除当前微信绑定或将绑定置为 disabled。 |
| `/me` | 否 | 查看当前绑定状态。 |
| `/help`、`/h`、`/?` | 否 | 返回帮助说明。 |
| `/chat <message>`、`/c <message>` | 是 | 强制普通 Agent 模式。 |
| `/rag <message>`、`/r <message>` | 是 | 强制 RAG 模式，但 scope 仍来自服务端绑定。 |
| `/reset`、`/reboot` | 是 | 重置当前微信用户会话。 |
| `/status`、`/stat`、`/s` | 是 | 返回当前会话与默认模式摘要。 |

### 8.1 `/bind` 行为

成功回复：

```text
绑定成功。
租户：tenant-a
用户：user-a
现在可以直接发送问题。
```

失败场景：

| 场景 | 回复 |
| --- | --- |
| token 不存在 | 绑定码无效，请重新生成。 |
| token 过期 | 绑定码已过期，请在系统中重新生成。 |
| token 已使用 | 绑定码已被使用，请重新生成。 |
| 当前微信已绑定 | 当前微信已绑定账号，如需更换请先发送 `/unbind`。 |

### 8.2 `/me` 行为

已绑定返回租户、用户和默认模式；未绑定返回绑定指引。

### 8.3 `/unbind` 行为

建议默认软删除：

```text
status=2
unbound_time=now()
```

解绑后应重置当前会话并清理限流状态。

## 9. RAG Scope 绑定

RAG scope 只能来自服务端配置或数据库绑定记录，不能由微信自然语言消息覆盖。优先级：

1. 数据库绑定记录 `e_wechatbot_user_binding.rag_scope_json`。
2. 绑定 token 携带的 `rag_scope_json`，绑定成功后写入用户绑定记录。
3. 环境变量映射 value 中的 `ragScope`。
4. `WECHATBOT_TENANT_RAG_SCOPE_MAP` 中当前租户的配置。
5. 全局 `WECHATBOT_DEFAULT_RAG_SCOPE`。
6. 兼容的单项配置：`WECHATBOT_DEFAULT_KNOWLEDGE_BASE_ID`、`WECHATBOT_DEFAULT_KNOWLEDGE_BASE_NAME`、`WECHATBOT_DEFAULT_FILE_SET_ID`。

支持字段：`knowledgeBaseId`、`knowledgeBaseName`、`knowledgeBaseNames`、`fileSetId`。

无有效 scope 时返回：

```text
当前未配置知识库，无法使用 RAG 模式。请联系管理员配置知识库范围。
```

## 10. 会话、限流与工作目录隔离

### 10.1 Conversation ID

```text
wechat:{tenant_id}:{bot_instance_id}:{user_id_hash}
```

该 ID 用于普通 Agent、RAG Agent、`/reset` 和审计。不得包含微信明文 `user_id`。

### 10.2 工作目录隔离

微信入口调用普通 Agent 和 RAG runner 时必须传入：

```text
space_id = tenant_id
```

`AgentService` 使用 `space_id` 将工作目录隔离到租户空间，例如：

```text
<WORK_DIR>/spaces/{tenant_id}
```

### 10.3 限流维度

```text
tenant_id + bot_instance_id + user_id_hash
```

## 11. 管理 API

Router 前缀：`/wechatbot`。所有管理 API 复用 `AGENT_SDK_API_KEY` 鉴权。

### 11.1 现有运行态 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/wechatbot/status` | 查询 Bot 状态；禁用时返回 `enabled=false`。 |
| `POST` | `/wechatbot/start` | 启动 Bot 或发起登录流程；已运行时幂等返回当前状态。 |
| `POST` | `/wechatbot/stop` | 停止 Bot，不删除凭证文件。 |
| `POST` | `/wechatbot/relogin` | 重新登录；请求体支持 `{"force": true}`。 |
| `GET` | `/wechatbot/qrcode` | 获取当前二维码。 |
| `GET` | `/wechatbot/login-qrcode` | 规格兼容路径，等价于 `/qrcode`。 |
| `POST` | `/wechatbot/send` | 运维测试发送文本消息。 |

### 11.2 新增绑定 API

#### 创建绑定码

```http
POST /wechatbot/bind-tokens
```

请求：

```json
{
  "tenantId": "tenant-a",
  "appUserId": "user-a",
  "defaultMode": "rag",
  "ragScope": {"knowledgeBaseId": "kb-a"},
  "ttlSeconds": 600
}
```

响应：

```json
{
  "token": "WX-8K3P2Q",
  "expiresAt": "2026-05-29T10:10:00Z",
  "bindCommand": "/bind WX-8K3P2Q"
}
```

明文 token 只在创建响应中返回一次。

#### 查询绑定列表

```http
GET /wechatbot/bindings?tenantId=tenant-a&appUserId=user-a
```

#### 禁用/解绑绑定

```http
DELETE /wechatbot/bindings/{id}
```

行为：设置 `status=2` 和 `unbound_time=now()`，不删除审计历史。

## 12. 配置项总览

### 12.1 基础运行

```env
WECHATBOT_ENABLED=false
WECHATBOT_AUTO_START=false
WECHATBOT_BASE_URL=https://ilinkai.weixin.qq.com
WECHATBOT_CRED_PATH=~/.wechatbot/credentials.json
WECHATBOT_CREDENTIALS_DIR=<WORK_DIR>/.wechatbot/credentials
WECHATBOT_ILINK_APP_ID=
WECHATBOT_ILINK_APP_SECRET=
WECHATBOT_ILINK_DEVICE_ID=
```

### 12.2 自动绑定

```env
# db / env / composite
WECHATBOT_BINDING_STORE=composite

# DB store 复用 DB_DSN 指向的同一个 MySQL 数据库

# 绑定码默认有效期
WECHATBOT_BIND_TOKEN_TTL_SECONDS=600

# 未绑定用户是否必须先绑定；生产推荐 true
WECHATBOT_REQUIRE_USER_TENANT=true
```

### 12.3 Mode A fallback

```env
WECHATBOT_DEFAULT_TENANT_ID=default
WECHATBOT_BOT_INSTANCE_ID=default
WECHATBOT_USER_TENANT_MAP={}
WECHATBOT_TENANT_RAG_SCOPE_MAP={}
```

## 13. 安全要求

- 管理 API 必须复用 `AGENT_SDK_API_KEY`，后续应支持 SaaS Web 登录态。
- `/bind` 是唯一允许未绑定微信用户执行的状态变更命令。
- 绑定码必须一次性、短期有效、不可枚举。
- 微信入口默认不开放工具：`allowed_tools=[]`。
- `GLOBAL_DISALLOWED_TOOLS` 必须继续生效。
- 日志、审计、指标和 DB 中只记录 `user_id_hash`。
- 不输出微信凭证、context token、媒体 URL、CDN key、API Key、绑定码明文。
- RAG scope 只由 DB 绑定记录或服务端配置决定。

## 14. 观测与审计

审计条目应包含：`timestamp`、`event_type`、`user_id_hash`、`conversation_id`、`tenant_id`、`app_user_id`、`direction`、`status`、`message_type`、`processing_time_ms`、`error_message`、可选 `content_preview`。

绑定事件也必须审计：

| 事件 | 内容 |
| --- | --- |
| `bind_token_created` | token preview、tenant_id、app_user_id、expires_time |
| `bind_success` | user_id_hash、tenant_id、app_user_id |
| `bind_failed` | 失败原因，不记录 token 明文 |
| `unbind` | user_id_hash、tenant_id、app_user_id |

指标应包括绑定成功/失败次数、未绑定用户消息次数，以及现有消息处理指标。

## 15. 示例配置

### 15.1 开发环境：默认租户 fallback

```env
WECHATBOT_ENABLED=true
WECHATBOT_AUTO_START=false
WECHATBOT_BINDING_STORE=env
WECHATBOT_DEFAULT_TENANT_ID=default
WECHATBOT_DEFAULT_MODE=agent
WECHATBOT_REQUIRE_USER_TENANT=false
```

### 15.2 生产推荐：数据库自动绑定

```env
WECHATBOT_ENABLED=true
WECHATBOT_AUTO_START=true
WECHATBOT_BINDING_STORE=composite
DB_DSN=mysql+asyncmy://user:pass@host:3306/dbname
WECHATBOT_DEFAULT_TENANT_ID=public
WECHATBOT_BOT_INSTANCE_ID=main-wechatbot
WECHATBOT_REQUIRE_USER_TENANT=true
WECHATBOT_TENANT_RAG_SCOPE_MAP={"tenant-a":{"knowledgeBaseId":"kb-tenant-a"}}
WECHATBOT_AUDIT_ENABLED=true
WECHATBOT_OTEL_ENABLED=true
```

### 15.3 应急 fallback：环境变量覆盖

```env
WECHATBOT_USER_TENANT_MAP={"sha256:13d52e633f4c93e0":{"tenantId":"tenant-a","appUserId":"u-1001","defaultMode":"rag"}}
```

## 16. 实施 TODO

### Phase 1：规格与配置

- [x] 将 Mode A 拆分为 A-1 fallback 与 A-2 自动绑定。
- [x] 明确绑定码流程、数据模型、命令、API 和验收标准。
- [ ] 在 `app/config.py` 增加：
  - `WECHATBOT_BINDING_STORE`
  - `WECHATBOT_BIND_TOKEN_TTL_SECONDS`

### Phase 2：绑定 Store 与数据模型

- [ ] 新增 `app/services/wechatbot/binding_store.py`。
- [ ] 定义 `WeChatUserBinding`、`BindTokenCreated`、`BindTokenRecord` 数据模型。
- [ ] 实现 `EnvWeChatBindingStore`，复用当前 `WECHATBOT_USER_TENANT_MAP` 逻辑。
- [ ] 实现 `DbWeChatBindingStore`，基于 SQLAlchemy async engine。
- [ ] 实现 `CompositeWeChatBindingStore`，按 DB -> env fallback 顺序解析。
- [ ] 提供初始化建表或 migration 脚本说明。

### Phase 3：租户解析改造

- [ ] 将 `resolve_tenant_context()` 改造为 async 或新增 `resolve_tenant_context_async()`。
- [ ] 优先查 DB 绑定记录，再查 env fallback，再按默认租户 fallback。
- [ ] 绑定命中时更新 `last_seen_time`。
- [ ] 保持现有同步 env resolver 兼容测试或旧调用。

### Phase 4：微信命令

- [ ] 扩展 `RouteMode`：`BIND`、`UNBIND`、`ME`。
- [ ] `parse_command()` 支持 `/bind <code>`、`/unbind`、`/me`。
- [ ] 未绑定用户只允许 `/bind`、`/help`、`/me`。
- [ ] `/bind` 成功后创建绑定并返回租户/用户摘要。
- [ ] `/unbind` 软删除绑定并重置会话。

### Phase 5：管理 API

- [ ] `POST /wechatbot/bind-tokens` 创建绑定码。
- [ ] `GET /wechatbot/bindings` 查询绑定列表。
- [ ] `DELETE /wechatbot/bindings/{id}` 禁用绑定。
- [ ] API 返回中不泄露 token hash 或微信明文 user_id。

### Phase 6：测试与验证

- [ ] 单元测试：token 创建、hash 校验、过期、重复使用、解绑。
- [ ] 单元测试：DB 绑定优先于 env fallback。
- [ ] 单元测试：未绑定用户只能执行 `/bind`、`/help`、`/me`。
- [ ] 集成测试：绑定后 `/status` 显示租户化 conversation ID。
- [ ] 安全测试：日志和 API 响应不出现明文 `user_id` 和 token hash。
- [ ] 运行：`uv run ruff check ...`。
- [ ] 运行：`PYTHONPATH=. pytest tests/test_wechatbot_mode_a.py`。

## 17. 验收标准

### 17.1 自动绑定

- Web/API 可创建绑定码，并返回一次性明文 token。
- 用户发送 `/bind <code>` 后，DB 中创建或更新 `e_wechatbot_user_binding`。
- token 过期、已使用、已撤销时不能绑定。
- 当前微信已绑定时，重复 `/bind` 不应覆盖已有绑定，除非后续显式支持换绑流程。

### 17.2 身份与隔离

- DB 绑定命中时，消息进入绑定的 `tenant_id/app_user_id`。
- DB 绑定优先于 env fallback。
- 未绑定且 `WECHATBOT_REQUIRE_USER_TENANT=true` 时，不调用 Agent/RAG。
- 生成的 `conversation_id` 不包含明文 `user_id`。
- Agent/RAG 调用收到的 `space_id` 等于 `tenant_id`。

### 17.3 RAG Scope

- DB 用户级 `rag_scope_json` 优先于租户级 scope。
- 租户级 scope 优先于全局默认 scope。
- `/rag` 不能通过消息文本切换到其他租户知识库。
- 无 scope 时返回未配置知识库提示。

### 17.4 安全与观测

- 管理 API 无 API Key 时拒绝访问。
- 微信入口调用 Agent/RAG 时 `allowed_tools=[]`。
- 日志、审计、指标、DB、API 响应中不出现明文微信 `user_id`。
- 日志、审计、指标、DB、API 响应中不出现绑定码明文；创建 API 响应除外。
- 限流触发时不调用 Agent/RAG，并记录脱敏观测信息。

## 18. 当前实现边界与风险

- 当前已完成 Mode A-1 fallback 与 Mode A-2 绑定码主流程。
- `WECHATBOT_USER_TENANT_MAP` 仍作为 fallback 保留，不应作为生产主路径。
- Mode A 单 Bot runtime 与会话统计为单进程内存状态，进程重启后运行态丢失，但 DB 绑定记录和凭证文件可持久化。
- Mode B 已作为并行模式实现；详见第 19 章。

## 19. Mode B 并行实现说明

Mode B 不替代 Mode A，而是与 Mode A 并存：

| 模式 | 核心语义 | 是否需要 `/bind` | 凭证文件 |
| --- | --- | --- | --- |
| Mode A | 一个公共微信 Bot 服务多个 SaaS 用户 | 需要，或依赖 env/DB 映射 | `WECHATBOT_CRED_PATH` |
| Mode B | 每个 SaaS 用户登录自己的微信通道 | 不需要 | `<WECHATBOT_CREDENTIALS_DIR>/mode_b/<hash>.json` |

### 19.1 Mode B 身份模型

Mode B 通道由以下字段唯一确定：

```text
tenant_id + app_user_id + bot_instance_id
```

通道启动时即固定 SaaS 上下文：

```text
用户扫自己的微信登录二维码
  -> 独立 WeChatBotManager / WeChatBotAdapter
  -> 后续消息直接使用该通道所属 tenant_id/app_user_id/bot_instance_id
  -> conversation_id = wechat:{tenant_id}:{bot_instance_id}:{user_id_hash}
```

因此 Mode B 收到消息后不再要求微信用户发送 `/bind`。`/bind` 仍保留给 Mode A 使用。

### 19.2 新增实现文件

Mode B 相关实现包括：

| 文件 | 说明 |
| --- | --- |
| `app/services/wechatbot/channel_manager.py` | 管理每用户独立通道，负责通道 key、credential path、manager 生命周期。 |
| `app/services/wechatbot/adapter.py` | `WeChatBotAdapter(cred_path=...)` 支持自定义凭证路径。 |
| `app/services/wechatbot/manager.py` | `WeChatBotManager(...)` 支持固定 tenant/app_user/bot_instance 上下文。 |
| `app/routers/wechatbot.py` | 新增 `/wechatbot/mode-b/channels/*` 管理 API。 |
| `app/main.py` | 服务关闭时停止 Mode B channel manager 中所有通道。 |

### 19.3 Mode B 管理 API

#### 启动或创建用户独立通道

```http
POST /wechatbot/mode-b/channels/start
```

请求：

```json
{
  "tenantId": "tenant-a",
  "appUserId": "user-a",
  "botInstanceId": "default",
  "forceLogin": false
}
```

说明：

- `forceLogin=false`：优先复用已有本地凭证。
- `forceLogin=true`：强制发起登录流程，通常用于重新扫码。
- 首次调用需要扫码时返回 `qrcode_url`。
- 已运行或凭证可复用时返回 `running`，`qrcode_url` 可能为 `null`。

#### 查询用户独立通道状态

```http
GET /wechatbot/mode-b/channels/status?tenantId=tenant-a&appUserId=user-a&botInstanceId=default
```

#### 停止用户独立通道

```http
POST /wechatbot/mode-b/channels/stop
```

请求：

```json
{
  "tenantId": "tenant-a",
  "appUserId": "user-a",
  "botInstanceId": "default"
}
```

### 19.4 当前推荐选择

- 如果产品希望提供一个统一官方微信机器人入口，选择 **Mode A**。
- 如果产品希望每个 SaaS 用户扫码登录自己的微信机器人通道，选择 **Mode B**。
- 两套模式可以同时启用；需要前端清晰区分“绑定公共 Bot”和“登录我的微信通道”。
- Mode A 的单微信账号存在平台风控、频率和账号可用性风险；高可用场景应演进到 Mode B。
- 绑定码需要和 SaaS Web 登录态打通，否则无法自动知道 `tenant_id/app_user_id`。

## 19. 后续演进：Mode B

Mode B 可在本模式基础上引入：

- `tenant_wechat_bots` 数据表，存储租户独立微信账号、凭证路径、状态和配额。
- 多 Bot registry，支持 bot_instance 动态注册、状态查询和租户绑定。
- Redis 分布式锁，避免多个 worker 同时启动同一个 Bot。
- Bot runtime worker，与 FastAPI API 进程解耦。
- 租户级审计、计费、配额和告警。
- 租户级工具白名单和 RAG scope 管理后台。
