# 纯文件问答规格说明

## 1. 背景

当前文件上传问答链路：

```
上传 → parse → chunk → embed → vector store → 检索 → 问答
```

完整走 RAG 管线，适合大文件、长期知识库。但很多场景只需要：

```
上传 → parse → 文本存 MySQL → 问答时直接注入上下文
```

即"纯文件问答"：跳过 chunk / embed / vector store，解析后文本直接作为上下文注入 LLM，无需检索。

典型场景：

- 用户上传一份合同，直接问"第三条写了什么"
- 上传一个简历，问"这个人的工作经历"
- 一次性小文件问答，不需要建知识库

## 2. 两种模式对比

| | RAG 模式（现有） | 纯文件问答模式（新增） |
|---|---|---|
| 上传参数 | `parseOnly=false`（默认） | `parseOnly=true` |
| 解析 | DocumentParser | DocumentParser |
| 切分 / 嵌入 / 索引 | chunk → embed → vector store | **跳过** |
| 文本存储 | chunk 存 MySQL + 向量存 Qdrant | 解析文本存 `e_rag_parsed_file` |
| 问答时 | 从 vector store 检索 | 从 MySQL 读文本注入上下文 |
| 适用 | 大文件、长期知识库、多轮检索 | 小文件、一次性问答 |
| 延迟 | 检索 ~100ms | 无检索延迟 |

## 3. 新增 MySQL 表

### 3.1 e_rag_parsed_file

```sql
CREATE TABLE e_rag_parsed_file (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'id',
  file_id         VARCHAR(64)  NOT NULL COMMENT '文件业务ID，唯一标识',
  file_set_id     VARCHAR(64)  NOT NULL COMMENT '文件集业务ID，同一次上传共享',
  filename        VARCHAR(512) NOT NULL COMMENT '原始文件名',
  md5             CHAR(32)     NOT NULL COMMENT '文件内容MD5，用于去重复用',
  mime_type       VARCHAR(128) COMMENT 'MIME类型',
  file_size       BIGINT       DEFAULT 0 COMMENT '文件大小，单位字节',
  parsed_text     LONGTEXT     COMMENT '解析后文本',
  parser          VARCHAR(32)  COMMENT '解析器：local / mineru / kimi',
  status          SMALLINT     DEFAULT 1 COMMENT '状态，1：处理中，2：就绪，3：失败',
  error_code      VARCHAR(64)  COMMENT '错误码',
  error_message   VARCHAR(1024) COMMENT '错误信息',
  metadata_json   JSON         COMMENT '扩展元数据',
  create_by       VARCHAR(64)  COMMENT '创建人',
  create_time     DATETIME     COMMENT '创建时间',
  update_by       VARCHAR(64)  COMMENT '更新人',
  update_time     DATETIME     COMMENT '更新时间',
  is_delete       SMALLINT     DEFAULT 1 COMMENT '是否删除，1：正常，2：删除',

  UNIQUE KEY uk_file_id (file_id),
  INDEX idx_file_set_id (file_set_id),
  INDEX idx_md5 (md5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG解析文件表';
```

说明：

- `file_id`：唯一标识，一行一个文件。
- `file_set_id`：分组字段，同一次上传的多个文件共享。问答时按 `file_set_id` 查询全部文件文本。
- `md5`：文件内容哈希，用于去重。相同文件不重复 parse，直接复用已有 `parsed_text`。
- `parsed_text`：解析后的纯文本，直接存入 LONGTEXT。
- `status`：与 `e_rag_file` 一致，1=处理中，2=就绪，3=失败。
- 不设 `tenant_id` / `owner_id` / `api_key_id`，访问控制走 `e_rag_file_set` 那层。

### 3.2 e_rag_file_set 新增字段

```sql
ALTER TABLE e_rag_file_set ADD COLUMN parse_only SMALLINT DEFAULT 1 COMMENT '是否仅解析不入库RAG，1：否（默认，走RAG），2：是（纯文件问答）';
```

说明：

- `parse_only=1`（默认）：走现有 RAG 管线（chunk → embed → vector store）。
- `parse_only=2`：仅解析，文本存 `e_rag_parsed_file`，问答时直接注入上下文。
- 用 SMALLINT 与现有 `temporary` 字段风格一致。

## 4. MD5 去重逻辑

### 4.1 上传流程

```
上传文件 → 算 MD5 → 查 e_rag_parsed_file WHERE md5=? AND status=2 LIMIT 1
  ├── 找到 → 复用 parsed_text，创建新 file 记录（省去 parse 调用）
  └── 没找到 → 调 DocumentParser → 存入 parsed_text
```

### 4.2 去重范围

全局去重。MD5 碰撞概率极低，相同文件内容不论谁上传，解析结果一样。

### 4.3 复用语义

- 复用的是 `parsed_text`，不是整条记录。
- 每次 upload 仍创建新的 `file_id` 和 `file_set_id` 关联。
- 复用时不调 parser，省去网络请求和等待时间。

## 5. API 改动

前置条件：parse-only 依赖 MySQL metadata store，请配置 `DB_DSN`。历史变量 `RAG_DB_DSN` 仅作为兼容 fallback；新环境统一使用 `DB_DSN`。

### 5.1 上传端点

`POST /rag/files` 新增参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `parseOnly` | bool | false | true 时仅解析不入库 RAG，文本存 MySQL |

`parseOnly=true` 时的行为：

1. 调 DocumentParser 解析文件。
2. MD5 去重检查。
3. 解析文本存入 `e_rag_parsed_file`。
4. `e_rag_file_set` 记录 `parse_only=2`。
5. **不做** chunk / embed / vector store 操作。
6. 返回格式与现有一致（`fileSetId` + `files`）。

`parseOnly=true` 时 `asyncMode` 参数不生效（parse 通常 1-5 秒内完成，无需异步）。

### 5.2 问答端点

`POST /rag/stream` / `POST /agent-sdk/rag/stream` **无需新增参数**。

问答时根据 `fileSetId` 自动判断模式：

```
fileSetId → 查 e_rag_file_set.parse_only
  ├── parse_only=1（RAG 模式）→ 走现有检索链路
  └── parse_only=2（纯文件问答）→ 从 e_rag_parsed_file 读文本 → 注入上下文
```

### 5.3 问答时上下文注入

`parse_only=2` 时的注入策略：

1. 按 `file_set_id` 查 `e_rag_parsed_file WHERE file_set_id=? AND status=2`。
2. 拼接为参考上下文：

```
以下是用户上传的文件内容，请基于此回答问题：

--- 文件：contract.pdf ---
{parsed_text}

--- 文件：policy.docx ---
{parsed_text}
```

3. 作为 `prompt_override` 或 system prompt 的一部分注入 LLM。
4. **不走 RAG 检索**（不调 `rag_hybrid_search` 等 MCP 工具）。
5. 不走 rerank / citation 对齐（无检索结果可引用）。

### 5.4 上下文长度保护

- 单文件解析文本可能很长（如 100 页 PDF）。
- 需要检查总注入文本是否超过模型上下文窗口。
- 超限时截断并提示用户：

```
注意：文件内容过长（约 {total_chars} 字符），已截断至 {max_chars} 字符。如需查看完整内容，请使用 RAG 模式上传。
```

- 截断阈值由 `RAG_PARSE_ONLY_MAX_TOKENS` 控制；为空或小于等于 0 表示不限制。
- token 到字符的估算为 `max_tokens * 3`（中文/英文混合粗略估算）。例如 `RAG_PARSE_ONLY_MAX_TOKENS=2048` 约为 6000 字符。

## 6. 代码改动范围

| 文件 | 改动 |
|------|------|
| `app/database.py` | 新增 `ERagParsedFile` ORM 模型；`ERagFileSet` 新增 `parse_only` 字段 |
| `sql/rag_parsed_file.sql` | **新增**：DDL 建表 + ALTER 语句 |
| `app/services/rag/mysql_store.py` | 新增 `save_parsed_file` / `get_parsed_files_by_set` / `get_parsed_file_by_md5` 方法 |
| `app/routers/rag.py` | `upload_rag_files` 新增 `parseOnly` 参数；`_generate_rag_stream` 增加 parse_only 分支 |
| `app/services/rag/agent_runner.py` | 新增 `stream_file_context` 方法（读 MySQL → 拼上下文 → 调 LLM） |
| `app/models/rag.py` | 无需改动，`fileSetId` 自动判断模式 |

总计 6 个文件，其中 1 个新增。

## 7. 问答模式判断流程

```
RagStreamRequest.fileSetId
  ↓
查 e_rag_file_set WHERE file_set_id=?
  ↓
parse_only = ?
  ├── 1（RAG 模式，默认）
  │   ↓
  │   现有链路：build_request_context → stream_claude_sdk（MCP RAG tools）
  │
  └── 2（纯文件问答）
      ↓
      查 e_rag_parsed_file WHERE file_set_id=? AND status=2
      ↓
      拼接上下文文本
      ↓
      检查长度 → 截断（如需）
      ↓
      stream_claude_sdk（不注入 MCP RAG tools，上下文直接拼入 prompt）
```

## 8. 错误处理

| 场景 | 处理方式 |
|------|---------|
| parseOnly=true 但文件格式不支持 | 与 RAG 模式一致，单文件失败不影响其他文件 |
| 解析后文本为空 | 记录 error，返回 `partial_ready` |
| 文件过大导致 parsed_text 超出 LONGTEXT | MySQL LONGTEXT 最大 4GB，实际不会超限 |
| 问答时 fileSetId 对应的 parsed_file 全部失败 | 返回错误提示"文件解析失败，请重新上传" |
| 上下文超长 | 截断 + 提示用户 |
| fileSetId 不存在 | 与现有逻辑一致，返回 missing_sources 错误 |

## 9. MD5 去重边界情况

| 场景 | 处理方式 |
|------|---------|
| 同文件不同文件名 | MD5 相同，复用 parsed_text，file 记录用实际上传的 filename |
| 同文件多次上传到不同 fileSet | 每次创建新 file 记录，parsed_text 复用 |
| MD5 相同但文件实际不同（碰撞） | 概率极低，暂不处理；后续可加 size 二次校验 |
| 已有记录 status=failed | 不复用，重新 parse |
| 已有记录 status=parsing（并发） | 短暂等待或直接重新 parse |

## 10. 不在本次范围

- parsed_file 定时清理（复用 `e_rag_file_set` 的 TTL 机制）。
- 前端 parseOnly 切换 UI。
- 纯文件问答模式的 citation 引用（无检索结果）。
- 文件内容变更检测（同一文件名内容变了）。
- 对象存储集成（parsed_text 指向外链）。

## 11. curl 验证用例

以下用例用于验证上传 `parseOnly=true` 后，问答是否进入纯文件上下文分支。

```bash
# 如启用了 AGENT_SDK_API_KEY，请追加：-H "X-API-Key: <your-api-key>"

# 1. 上传文件并仅解析，不入库向量索引
UPLOAD_RESPONSE=$(curl -sS -X POST http://localhost:8000/rag/files \
  -F "parseOnly=true" \
  -F "file=@./docs/specs/rag-parse-only-qa.md;type=text/markdown")

echo "$UPLOAD_RESPONSE"
FILE_SET_ID=$(python -c 'import json,sys; print(json.load(sys.stdin)["fileSetId"])' <<< "$UPLOAD_RESPONSE")

# 2. 查询 fileSet 状态
curl -sS "http://localhost:8000/rag/files/${FILE_SET_ID}/status"

# 3. 基于同一个 fileSetId 调用问答流
curl -N -X POST http://localhost:8000/agent-sdk/rag/stream \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"请概括这个文件的主要内容，并说明 parse-only 问答的核心流程。\",\"fileSetId\":\"${FILE_SET_ID}\"}"
```

期望结果：

- 上传响应 `status=ready`，文件 `status=ready`。
- 状态接口中 `indexedChunks=0`、`totalChunks=0`，表示没有执行 chunk / embedding / vector store。
- SSE 首个检索事件为 `mode=parse_only`，例如：

```text
event: retrieval
data: {"mode":"parse_only","resultCount":1,"totalChars":6111,"truncated":false,...}
```

已验证示例：上传 `docs/specs/rag-parse-only-qa.md` 后，返回 `mode=parse_only`，并正常输出 `agent_delta` 回答。
