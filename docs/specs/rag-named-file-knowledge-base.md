# RAG 命名文件知识库需求规格说明

## 1. 背景

当前项目已经具备基于 RAG 的文档问答能力，主要包含以下使用方式：

1. 上传文件生成临时 `fileSetId`，然后基于 `fileSetId` 问答。
2. 将已索引的 `fileSetId` 提升为持久知识库，生成 `knowledgeBaseId`。
3. 问答时通过 `knowledgeBaseId`、`fileSetId` 或显式 `sources` 指定检索范围。

现有能力可以完成基础的“上传文件后问答”和“基于知识库 ID 问答”，但在用户视角下仍然比较脆弱：

- `fileSetId` / `knowledgeBaseId` 是系统生成 ID，不易记忆。
- 用户很难自然地管理“某一组文件形成的知识库”。
- 当用户有多组文件时，例如合同资料、产品资料、售后政策资料，需要能把它们归类成可读名称。
- 用户希望后续能直接说“基于 zsk1 问答”或“比较 zsk1 和 zsk2”。

因此，本需求新增“命名文件知识库”能力：

> 用户可以把一组上传文件生成的知识库命名为 `zsk1`、`zsk2` 等业务名称，并在后续问答中基于这些命名知识库进行检索和回答。

该能力是对现有 RAG 文档知识库问答能力的增量增强，必须保持原有 API 与行为兼容。

## 2. 目标

### 2.1 核心目标

新增“命名文件知识库”能力，支持：

1. 用户上传一个或多个文件时，可指定知识库名称，例如 `zsk1`。
2. 系统完成文件解析、切分、embedding、索引后，自动创建一个持久知识库。（这个最好在service层做成通用能力，因为后面也可能从已经上传的文件里面选取文件然后来创建一个持久知识库）
3. 系统将用户指定的名称与内部 `knowledgeBaseId` 建立绑定。
4. 用户后续可以通过 `knowledgeBaseName` 进行问答。
5. 用户可以通过 `knowledgeBaseNames` 同时基于多个命名知识库问答。
6. 原有 `fileSetId`、`knowledgeBaseId`、`sources` 问答能力保持不变。

### 2.2 当前实现状态补充

当前开发实现已支持以下能力：

1. `/rag/files` 支持单文件字段 `file` 和多文件字段 `files`。
2. 一次 `/rag/files` 请求中上传的一个或多个文件会组成一个 `fileSet`。
3. 如果同时传入 `knowledgeBaseName`，该 `fileSet` 会被提升为一个持久命名知识库。
4. 当前语义是：

```text
一次多文件上传 + 一个 knowledgeBaseName = 一个命名知识库
```

示例：

```bash
curl -X POST "http://localhost:8000/rag/files" \
  -F "files=@doc1.txt" \
  -F "files=@doc2.txt" \
  -F "knowledgeBaseName=zsk1"
```

表示 `doc1.txt` 和 `doc2.txt` 一起构成名为 `zsk1` 的知识库。

注意：当前阶段不支持“向已有 `knowledgeBaseName` 追加文件”。如果再次使用已存在的 `knowledgeBaseName` 上传，会返回冲突错误。后续正式开发阶段可新增“追加文件到已有知识库”的专用接口或逻辑。

### 2.3 非目标

本次需求不包含以下内容：

1. 不实现完整知识库管理后台 UI。
2. 不强制迁移现有所有 RAG 状态到结构化数据库表。
3. 不改变现有向量检索逻辑。
4. 不改变 Agent SDK 与 RAG MCP 工具调用机制。
5. 不实现跨租户共享知识库。
6. 不实现复杂权限后台。
7. 不实现知识库版本管理。
8. 本阶段不实现知识库文件级增量更新；后续正式开发阶段可单独设计“向已有知识库追加文件 / 删除文件 / 重建索引”的能力。
9. 不实现知识库重建队列。
10. 不实现知识库名称的模糊搜索。

## 3. 术语定义

### 3.1 fileSet

`fileSet` 是当前系统已有概念，表示一次上传的一个或多个文件集合。

示例：

```text
fileSetId = fs_xxx
```

它可以用于临时文件问答。

### 3.2 knowledgeBase

`knowledgeBase` 是持久知识库，当前系统已有 `knowledgeBaseId` 概念。

示例：

```text
knowledgeBaseId = kb_xxx
```

它通常来源于一个已经索引完成的 `fileSet`。

### 3.3 named file knowledge base

命名文件知识库是本次新增概念。

它本质上仍然是一个 `knowledgeBase`，但增加了用户可读名称：

```text
name = zsk1
knowledgeBaseId = kb_xxx
sourceFileSetId = fs_xxx
```

用户可以通过 `zsk1` 来引用该知识库。

### 3.4 knowledgeBaseName

用户可读知识库名称。

示例：

```text
zsk1
zsk2
contract_policy
refund_docs
```

### 3.5 knowledgeBaseNames

多个用户可读知识库名称。

示例：

```json
["zsk1", "zsk2"]
```

## 4. 总体设计

### 4.1 设计原则

1. **兼容优先**
   - 原有 `fileSetId` 问答不变。
   - 原有 `knowledgeBaseId` 问答不变。
   - 原有 `sources` 问答不变。

2. **名称只做解析，不改变底层检索**
   - 问答时，先把 `knowledgeBaseName` 解析为 `knowledgeBaseId`。
   - 检索仍然基于现有 `knowledge_base` source scope。

3. **名称必须持久化**
   - `zsk1` / `zsk2` 是用户可感知资源，不能只放在内存。
   - 服务重启后，用户仍应可以通过名称问答。

4. **权限隔离**
   - 名称解析必须考虑 `tenantId`、`ownerId`、`apiKeyId` 等隔离字段。
   - 不允许用户通过名称访问其他用户的知识库。

5. **唯一性**
   - 推荐同一作用域内知识库名称唯一。
   - 作用域建议为：`tenantId + ownerId + name`。
   - 如果没有多租户信息，则至少应保证全局名称唯一，避免歧义。

6. **Embedding 一致性优先**
   - 文档入库时使用的 embedding provider 与查询时使用的 embedding provider 必须一致。
   - 系统必须避免 ingestion 使用一种嵌入模型、retriever 使用另一种嵌入模型。
   - embedding provider 只能通过统一工厂创建和获取，不能在不同模块中各自独立实例化。
   - 服务启动时应检查当前 embedding provider 的可用性与实际向量维度。
   - 已持久化的历史向量必须记录 embedding provider / model / dimension 信息，以便切换模型时发现维度偏差。

### 4.2 高层流程

```text
上传文件 + knowledgeBaseName
  ↓
生成 fileSetId
  ↓
解析 / chunk / embedding / index
  ↓
创建 knowledgeBaseId
  ↓
数据库保存 name -> knowledgeBaseId
  ↓
chunk metadata 写入 knowledgeBaseId
  ↓
用户通过 knowledgeBaseName 问答
  ↓
服务端解析 name -> knowledgeBaseId
  ↓
沿用现有 RAG 检索和 Agent 回答链路
```

### 4.3 Embedding 与向量库设计

当前实现将 embedding 模型和向量存储解耦：

```text
文本 chunk
  ↓
EmbeddingProvider 生成向量
  ↓
VectorStore 存储 chunk + embedding
  ↓
查询时使用同一 EmbeddingProvider 生成 query embedding
  ↓
VectorStore 执行相似度检索
```

当前开发环境支持：

```env
RAG_EMBEDDING_PROVIDER=openai_compatible
RAG_EMBEDDING_MODEL=bge-m3:latest
RAG_EMBEDDING_BASE_URL=http://zktz.4c888.com:62011/v1
RAG_VECTOR_PROVIDER=local
```

这表示：

```text
Embedding 模型：远程 BGE-M3
向量库：本地 LocalVectorStore
```

即：文档文本调用远程 BGE-M3 生成 1024 维 embedding，再将 chunk + embedding 写入本地 LocalVectorStore；查询时继续调用同一 BGE-M3 生成 query embedding，并由 LocalVectorStore 通过 cosine similarity 检索。

该组合适合开发验证和单机小规模测试。生产环境建议将 `RAG_VECTOR_PROVIDER` 切换为 Qdrant、Milvus、pgvector 等真实向量数据库，并实现对应 `VectorStore` provider。

## 5. 用户场景

### 5.1 上传文件并命名为 zsk1

用户上传一组文件：

```text
refund_policy.md
after_sales.md
```

并指定：

```text
knowledgeBaseName = zsk1
```

系统行为：

1. 接收文件。
2. 解析文件内容。
3. 切分 chunk。
4. 生成 embedding。
5. 写入向量库。
6. 创建 `fileSetId`。
7. 创建持久知识库 `knowledgeBaseId`。
8. 将 `zsk1` 与 `knowledgeBaseId` 绑定。
9. 返回 `fileSetId` 和 `knowledgeBase` 信息。

返回示例：

```json
{
  "fileSetId": "fs_123",
  "status": "ready",
  "conversationId": "conv_001",
  "files": [
    {
      "fileId": "file_001",
      "filename": "refund_policy.md",
      "mimeType": "text/markdown",
      "size": 1024,
      "status": "ready"
    }
  ],
  "knowledgeBase": {
    "knowledgeBaseId": "kb_123",
    "name": "zsk1",
    "description": "售后政策资料",
    "sourceFileSetId": "fs_123",
    "status": "ready",
    "createdAt": "2026-05-25T10:00:00Z",
    "updatedAt": "2026-05-25T10:00:00Z"
  }
}
```

### 5.2 基于 zsk1 问答

请求：

```json
{
  "message": "请总结这个知识库里的退款政策",
  "knowledgeBaseName": "zsk1"
}
```

系统行为：

1. 读取 `knowledgeBaseName = zsk1`。
2. 查询数据库，解析为 `knowledgeBaseId = kb_123`。
3. 构造内部 source：

```json
{
  "type": "knowledge_base",
  "id": "kb_123",
  "metadata": {
    "knowledgeBaseName": "zsk1"
  }
}
```

4. 调用现有 RAG 检索。
5. Agent 基于检索结果回答。
6. 返回带引用答案。

### 5.3 基于多个命名知识库问答

请求：

```json
{
  "message": "请比较 zsk1 和 zsk2 中关于退款周期的差异",
  "knowledgeBaseNames": ["zsk1", "zsk2"]
}
```

系统行为：

1. 分别解析 `zsk1`、`zsk2`。
2. 得到多个 `knowledgeBaseId`。
3. 构造多个 source。
4. 在多个知识库范围内检索。
5. 返回综合答案，并尽量标注来源知识库和文件。

### 5.4 保持原有 knowledgeBaseId 问答

原请求继续有效：

```json
{
  "message": "退款政策是什么？",
  "knowledgeBaseId": "kb_123"
}
```

系统行为不变。

### 5.5 保持原有 fileSetId 问答

原请求继续有效：

```json
{
  "message": "这个文件讲了什么？",
  "fileSetId": "fs_123"
}
```

系统行为不变。

### 5.6 混合使用 ID 和名称

允许同时传入：

```json
{
  "message": "综合这些资料回答",
  "knowledgeBaseId": "kb_001",
  "knowledgeBaseNames": ["zsk1", "zsk2"],
  "fileSetId": "fs_001"
}
```

系统行为：

1. 保留 `knowledgeBaseId` 对应 source。
2. 保留 `fileSetId` 对应 source。
3. 解析 `knowledgeBaseNames` 对应 source。
4. 合并 source。
5. 去重。
6. 进行检索问答。

## 6. API 设计

### 6.1 上传文件并可选创建命名知识库

#### Endpoint

```http
POST /rag/files
```

#### Content-Type

```http
multipart/form-data
```

#### 现有字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `file` | file | 否 | 单文件上传 |
| `files` | file[] | 否 | 多文件上传 |
| `conversationId` | string | 否 | 会话 ID |
| `metadata` | string | 否 | JSON 对象字符串 |

#### 新增字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `knowledgeBaseName` | string | 否 | 上传成功后自动创建的知识库名称 |
| `knowledgeBaseDescription` | string | 否 | 知识库描述 |

#### 多文件上传语义

`/rag/files` 支持一次上传多个文件。一次请求中的所有文件共同组成一个 `fileSet`。

如果请求中传入 `knowledgeBaseName`，则这个 `fileSet` 会被提升为一个命名知识库。

```text
files=[doc1, doc2, doc3] + knowledgeBaseName=zsk1
  ↓
fileSetId=fs_xxx
  ↓
knowledgeBaseId=kb_xxx
  ↓
name=zsk1
```

因此，`knowledgeBaseName` 不是给单个文件命名，而是给本次上传形成的文件集合命名。

当前阶段不支持同名追加。如果 `zsk1` 已存在，再次上传并传 `knowledgeBaseName=zsk1` 会返回 `409 Conflict`。

#### 示例

```bash
curl -X POST "http://localhost:8000/rag/files" \
  -H "Authorization: Bearer <api-key>" \
  -F "file=@refund_policy.md" \
  -F "knowledgeBaseName=zsk1" \
  -F "knowledgeBaseDescription=售后退款政策"
```

#### 返回

如果未传 `knowledgeBaseName`，保持原响应结构：

```json
{
  "fileSetId": "fs_123",
  "status": "ready",
  "conversationId": null,
  "files": []
}
```

如果传了 `knowledgeBaseName`，新增 `knowledgeBase` 字段：

```json
{
  "fileSetId": "fs_123",
  "status": "ready",
  "conversationId": null,
  "files": [],
  "knowledgeBase": {
    "knowledgeBaseId": "kb_123",
    "name": "zsk1",
    "description": "售后退款政策",
    "sourceFileSetId": "fs_123",
    "status": "ready",
    "createdAt": "2026-05-25T10:00:00Z",
    "updatedAt": "2026-05-25T10:00:00Z",
    "tenantId": null,
    "ownerId": null,
    "apiKeyId": null,
    "metadata": {}
  }
}
```

#### 错误

##### 重名

```json
{
  "detail": "Knowledge base name already exists: zsk1"
}
```

推荐 HTTP 状态码：

```text
409 Conflict
```

如果保持现有错误风格，也可以先使用：

```text
400 Bad Request
```

##### 文件处理失败

保持现有逻辑。如果文件全部失败，不应创建知识库。

### 6.2 基于命名知识库流式问答

#### Endpoint

```http
POST /rag/stream
```

或：

```http
POST /agent-sdk/rag/stream
```

#### 新增请求字段

在现有 `RagStreamRequest` 中新增：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `knowledgeBaseName` | string | 否 | 单个知识库名称 |
| `knowledgeBaseNames` | string[] | 否 | 多个知识库名称 |

#### 示例：单知识库

```json
{
  "message": "这个知识库里有哪些退款政策？",
  "knowledgeBaseName": "zsk1"
}
```

#### 示例：多知识库

```json
{
  "message": "比较两个知识库中退款周期的不同",
  "knowledgeBaseNames": ["zsk1", "zsk2"]
}
```

#### 示例：混合 source

```json
{
  "message": "综合所有资料回答",
  "knowledgeBaseId": "kb_existing",
  "knowledgeBaseNames": ["zsk1", "zsk2"],
  "fileSetId": "fs_temp"
}
```

#### 内部转换

请求：

```json
{
  "knowledgeBaseName": "zsk1"
}
```

转换为：

```json
{
  "sources": [
    {
      "type": "knowledge_base",
      "id": "kb_123",
      "metadata": {
        "knowledgeBaseName": "zsk1"
      }
    }
  ]
}
```

之后沿用现有 RAG 工具链。

#### 错误：名称不存在

```json
{
  "code": "knowledge_base_not_found",
  "message": "Knowledge base name not found: zsk1",
  "requestId": "req_xxx"
}
```

HTTP 或 SSE error 事件中返回。

#### 错误：无 source

如果既没有传：

- `fileSetId`
- `knowledgeBaseId`
- `knowledgeBaseName`
- `knowledgeBaseNames`
- `sources`

则返回：

```json
{
  "code": "missing_sources",
  "message": "Provide fileSetId, knowledgeBaseId, knowledgeBaseName, knowledgeBaseNames, or sources."
}
```

### 6.3 知识库列表接口

当前项目已有 `KnowledgeBaseListResponse` 模型，建议继续提供或增强：

```http
GET /rag/knowledge-bases
```

#### Query 参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `tenantId` | string | 否 | 租户 ID |
| `ownerId` | string | 否 | 所有者 ID |
| `apiKeyId` | string | 否 | API Key ID |
| `name` | string | 否 | 精确名称过滤 |

#### 返回

```json
{
  "knowledgeBases": [
    {
      "knowledgeBaseId": "kb_123",
      "name": "zsk1",
      "description": "售后退款政策",
      "sourceFileSetId": "fs_123",
      "status": "ready",
      "createdAt": "2026-05-25T10:00:00Z",
      "updatedAt": "2026-05-25T10:00:00Z",
      "tenantId": "tenant_001",
      "ownerId": "user_001",
      "apiKeyId": "key_001",
      "metadata": {}
    }
  ]
}
```

## 7. 数据模型设计

### 7.1 Pydantic 模型变更

#### UploadFileResponse

新增字段：

```python
knowledge_base: KnowledgeBaseInfo | None
```

别名：

```python
knowledgeBase
```

用途：

- 当上传时指定 `knowledgeBaseName`，返回创建出的知识库。
- 未指定时为 `null` 或不返回，保持兼容。

#### RagStreamRequest

新增字段：

```python
knowledge_base_name: str | None
knowledge_base_names: list[str] | None
```

别名：

```python
knowledgeBaseName
knowledgeBaseNames
```

新增方法：

```python
def get_knowledge_base_names(self) -> list[str]:
    ...
```

用途：

- 统一获取单个名称和多个名称。
- 去空格。
- 去重。
- 保持顺序。

### 7.2 内部记录模型

当前已有：

```python
KnowledgeBaseRecord
```

其字段应至少包含：

```python
knowledge_base_id: str
name: str
source_file_set_id: str
status: str
description: str | None
created_at: datetime
updated_at: datetime
tenant_id: str | None
owner_id: str | None
api_key_id: str | None
metadata: dict[str, Any]
```

该模型可以继续复用。

## 8. 数据库存储设计

### 8.1 是否必须入库

`zsk1` / `zsk2` 必须持久化。

原因：

1. 用户可见名称属于长期资源。
2. 服务重启后仍需可用。
3. 需要支持列表、删除、重命名等后续管理能力。
4. 需要做重名约束。
5. 需要做权限隔离。

### 8.2 短期实现：复用 SQLite JSON Snapshot

当前项目已有：

```python
SQLiteRagStateStore
```

短期可继续将知识库元数据保存到 `rag_state` JSON snapshot 中。

#### 优点

- 改动小。
- 与当前项目已有机制一致。
- 可以快速实现重启后名称仍可解析。

#### 缺点

- 不适合大规模知识库。
- 不适合复杂查询。
- 重名唯一性只能在应用层保证。
- 无法利用数据库索引。

### 8.3 长期实现：MySQL 结构化表

推荐最终升级为 MySQL 结构化表，并遵循项目现有表风格：

数据库建表 SQL 已单独拆分到：

```text
sql/rag_named_knowledge_base.sql
```

本文保留核心字段说明和设计约束；实际建表以 SQL 文件为准。

- 主键字段统一使用自增 `id int(11) NOT NULL AUTO_INCREMENT COMMENT 'id'`。
- 表引擎使用 `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`。
- 字段使用 snake_case。
- 数据库物理表字段命名必须与 API 层保持一致性优先：API 层使用 `knowledgeBaseId`、`fileSetId`、`fileId`、`chunkId`，数据库层对应使用 `knowledge_base_id`、`file_set_id`、`file_id`、`chunk_id`。
- `id` 字段固定表示数据库自增主键；`knowledge_base_id`、`file_set_id`、`file_id`、`chunk_id` 等字段表示系统生成的业务 ID，不作为数据库自增主键。
- 每张业务表必须包含以下 5 个审计/软删除字段：
  - `create_by varchar(64) DEFAULT NULL COMMENT '创建人'`
  - `create_time datetime DEFAULT NULL COMMENT '创建时间'`
  - `update_by varchar(64) DEFAULT NULL COMMENT '更新人'`
  - `update_time datetime DEFAULT NULL COMMENT '更新时间'`
  - `is_delete tinyint(1) DEFAULT '1' COMMENT '是否删除，1：正常，2：删除'`
- 业务查询必须默认过滤 `is_delete = 1`。

#### e_rag_knowledge_base

命名知识库主表。核心作用是保存 `zsk1 -> kb_xxx` 这类用户可读名称到内部知识库业务 ID 的绑定关系。

```sql
CREATE TABLE `e_rag_knowledge_base` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT 'id',
  `knowledge_base_id` varchar(64) NOT NULL COMMENT '知识库业务ID，如kb_xxx，对应API层knowledgeBaseId',
  `name` varchar(128) NOT NULL COMMENT '知识库名称，如zsk1',
  `description` varchar(512) DEFAULT NULL COMMENT '知识库描述',
  `source_file_set_id` varchar(64) NOT NULL COMMENT '来源文件集业务ID，如fs_xxx，对应API层sourceFileSetId',
  `status` tinyint(2) DEFAULT '1' COMMENT '状态，1：处理中，2：就绪，3：部分就绪，4：失败',
  `tenant_id` varchar(64) DEFAULT NULL COMMENT '租户ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT '所有者ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key ID',
  `vector_provider` varchar(64) DEFAULT NULL COMMENT '向量库类型，如local、chroma、qdrant、milvus、pgvector',
  `vector_collection` varchar(128) DEFAULT NULL COMMENT '向量库collection/index/table名称',
  `vector_namespace` varchar(128) DEFAULT NULL COMMENT '向量库namespace/partition，可选',
  `vector_filter` json DEFAULT NULL COMMENT '向量检索过滤条件，如knowledgeBaseId过滤',
  `metadata` json DEFAULT NULL COMMENT '扩展元数据',
  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint(1) DEFAULT '1' COMMENT '是否删除，1：正常，2：删除',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_kb_id` (`knowledge_base_id`) USING BTREE,
  UNIQUE KEY `uk_scope_name` (`tenant_id`, `owner_id`, `name`, `is_delete`) USING BTREE,
  KEY `idx_source_file_set_id` (`source_file_set_id`) USING BTREE,
  KEY `idx_name` (`name`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG知识库表';
```

说明：

- `knowledge_base_id` 是系统内部稳定业务 ID，API 层对应 `knowledgeBaseId`，问答检索最终仍按它定位向量数据。
- `name` 是用户可读名称，如 `zsk1`、`zsk2`。
- `api_key_id` 是创建或归属该知识库的 API Key 标识，用于调用凭证维度的归属追踪、权限隔离、统计和审计；它不是 API Key 明文，也不应保存真实密钥值。
- `vector_provider` / `vector_collection` / `vector_namespace` / `vector_filter` 用于描述该知识库在底层向量库中的定位方式。
- `uk_scope_name` 用于保证同一 `tenant_id + owner_id` 范围内名称不重复。
- 如果项目后续要求不同 `api_key_id` 下也允许同名，可将唯一键调整为 `tenant_id + owner_id + api_key_id + name + is_delete`。

##### api_key_id 字段详细说明

`api_key_id` 表示当前知识库关联的“调用凭证 ID”或“接入应用 ID”，用于描述这个知识库是由哪个 API Key 创建、归属或授权访问的。它只保存系统内部的 API Key 标识，例如 `ak_123`、`key_001`、`app_a_key`，不得保存真实 API Key 明文，例如 `sk-xxxx`。

`api_key_id` 的定位如下：

| 字段 | 含义 | 示例 | 是否是密钥明文 |
| --- | --- | --- | --- |
| `tenant_id` | 租户/组织维度 | `tenant_001` | 否 |
| `owner_id` | 所有者/用户维度 | `user_001` | 否 |
| `api_key_id` | 调用凭证/API Key/接入应用维度 | `ak_123` | 否 |
| `create_by` | 审计字段，记录创建操作人 | `admin` / `user_001` | 否 |

典型用途：

1. **权限隔离**：当同一租户或同一用户存在多个 API Key / 应用时，可以限制某个 API Key 只能访问自己创建或授权范围内的知识库。
2. **归属追踪**：排查问题时可以判断某个知识库是由哪个调用凭证创建的。
3. **统计计费**：可以按 `api_key_id` 统计知识库数量、文件数量、chunk 数量、检索调用量等。
4. **限流治理**：后续可以按 API Key 维度限制创建知识库数量、上传文件大小或检索频次。

名称解析时，如果请求上下文中带有 `apiKeyId`，推荐加入过滤条件：

```sql
SELECT *
FROM e_rag_knowledge_base
WHERE name = ?
  AND tenant_id = ?
  AND owner_id = ?
  AND api_key_id = ?
  AND is_delete = 1;
```

如果当前系统暂时不需要按 API Key 隔离，则 `api_key_id` 可以为空，名称唯一约束先保持：

```sql
UNIQUE KEY `uk_scope_name` (`tenant_id`, `owner_id`, `name`, `is_delete`) USING BTREE
```

如果后续确认需要同一用户下不同 API Key 可以创建同名知识库，则唯一约束调整为：

```sql
UNIQUE KEY `uk_scope_api_name` (`tenant_id`, `owner_id`, `api_key_id`, `name`, `is_delete`) USING BTREE
```

安全要求：真实 API Key 必须由专门的密钥表或认证系统加密保存，RAG 知识库相关表只保存 `api_key_id` 这类引用标识。

#### e_rag_file_set

文件集主表。一次上传的一组文件会生成一个 `file_set_id`，API 层对应 `fileSetId`，可以是临时文件集，也可以被提升为持久知识库。

```sql
CREATE TABLE `e_rag_file_set` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT 'id',
  `file_set_id` varchar(64) NOT NULL COMMENT '文件集业务ID，如fs_xxx，对应API层fileSetId',
  `conversation_id` varchar(64) DEFAULT NULL COMMENT '会话ID',
  `status` tinyint(2) DEFAULT '1' COMMENT '状态，1：处理中，2：就绪，3：部分就绪，4：失败',
  `indexed_chunks` int(11) DEFAULT '0' COMMENT '已索引chunk数',
  `total_chunks` int(11) DEFAULT '0' COMMENT '总chunk数',
  `temporary` tinyint(1) DEFAULT '1' COMMENT '是否临时文件集，1：临时，2：持久',
  `knowledge_base_id` varchar(64) DEFAULT NULL COMMENT '关联知识库业务ID，对应API层knowledgeBaseId',
  `tenant_id` varchar(64) DEFAULT NULL COMMENT '租户ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT '所有者ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key ID',
  `metadata` json DEFAULT NULL COMMENT '扩展元数据',
  `expires_time` datetime DEFAULT NULL COMMENT '过期时间',
  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint(1) DEFAULT '1' COMMENT '是否删除，1：正常，2：删除',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_knowledge_base_id` (`knowledge_base_id`) USING BTREE,
  KEY `idx_conversation_id` (`conversation_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG文件集表';
```

说明：

- `temporary = 1` 表示临时文件问答上下文。
- `temporary = 2` 表示已经被提升为持久知识库或长期保留。
- `knowledge_base_id` 为空时，表示该文件集尚未绑定持久知识库。

#### e_rag_file

文件明细表。保存文件集内每个原始文件的处理状态和存储地址。文件内容不建议直接存入业务表，表内保存本地路径、对象存储 Key 或外部 URL 等定位信息。

```sql
CREATE TABLE `e_rag_file` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT 'id',
  `file_id` varchar(64) NOT NULL COMMENT '文件业务ID，如file_xxx，对应API层fileId',
  `file_set_id` varchar(64) NOT NULL COMMENT '文件集业务ID，如fs_xxx，对应API层fileSetId',
  `filename` varchar(512) NOT NULL COMMENT '原始文件名',
  `mime_type` varchar(128) DEFAULT NULL COMMENT 'MIME类型',
  `file_size` bigint(20) DEFAULT '0' COMMENT '文件大小，单位字节',
  `storage_type` tinyint(2) DEFAULT '1' COMMENT '存储类型，1：本地文件，2：对象存储，3：外部URL',
  `file_path` varchar(1024) DEFAULT NULL COMMENT '原始文件存储地址，本地路径、对象存储Key或外部URL',
  `parsed_file_path` varchar(1024) DEFAULT NULL COMMENT '解析后文本文件地址，可选',
  `file_url` varchar(1024) DEFAULT NULL COMMENT '文件访问URL，可选',
  `status` tinyint(2) DEFAULT '1' COMMENT '状态，1：处理中，2：就绪，3：失败',
  `error_code` varchar(64) DEFAULT NULL COMMENT '错误码',
  `error_message` varchar(1024) DEFAULT NULL COMMENT '错误信息',
  `metadata` json DEFAULT NULL COMMENT '扩展元数据',
  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint(1) DEFAULT '1' COMMENT '是否删除，1：正常，2：删除',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_file_id` (`file_id`) USING BTREE,
  KEY `idx_file_set_id` (`file_set_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG文件表';
```

说明：

- `file_path` 是必须在业务逻辑上写入的核心字段，用于重新读取原始文件、重新解析或重建索引。
- `parsed_file_path` 用于保存解析后的纯文本/Markdown 中间产物地址，便于后续重切 chunk 或排查解析问题。
- `file_url` 只作为可访问 URL 使用，不建议作为唯一存储定位依据；私有对象存储场景下可以为空，由服务端根据 `file_path` 临时签名生成访问地址。
- 如果文件只保存在对象存储，`file_path` 建议保存对象 Key，而不是带签名的临时 URL。

#### e_rag_chunk 可选

如果使用本地向量库或需要在业务库中保留 chunk 元数据，可结构化保存 chunk。若使用外部向量库，正文和 embedding 可以只存外部向量库，本表可只保存索引映射和必要 metadata。

```sql
CREATE TABLE `e_rag_chunk` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT 'id',
  `chunk_id` varchar(128) NOT NULL COMMENT 'Chunk业务ID，对应API层chunkId',
  `file_set_id` varchar(64) NOT NULL COMMENT '文件集业务ID，对应API层fileSetId',
  `knowledge_base_id` varchar(64) DEFAULT NULL COMMENT '知识库业务ID，对应API层knowledgeBaseId',
  `source_file_id` varchar(64) DEFAULT NULL COMMENT '来源文件业务ID，对应API层sourceFileId',
  `vector_provider` varchar(64) DEFAULT NULL COMMENT '向量库类型，如local、chroma、qdrant、milvus、pgvector',
  `vector_collection` varchar(128) DEFAULT NULL COMMENT '向量库collection/index/table名称',
  `vector_id` varchar(128) DEFAULT NULL COMMENT '向量库中的向量点ID/文档ID，可选',
  `chunk_index` int(11) DEFAULT NULL COMMENT 'Chunk序号',
  `chunk_text` mediumtext COMMENT 'Chunk文本内容',
  `token_count` int(11) DEFAULT '0' COMMENT 'Token数量',
  `metadata` json DEFAULT NULL COMMENT '扩展元数据',
  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint(1) DEFAULT '1' COMMENT '是否删除，1：正常，2：删除',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_chunk_id` (`chunk_id`) USING BTREE,
  KEY `idx_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_knowledge_base_id` (`knowledge_base_id`) USING BTREE,
  KEY `idx_source_file_id` (`source_file_id`) USING BTREE,
  KEY `idx_vector_id` (`vector_provider`, `vector_collection`, `vector_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG Chunk表';
```

说明：

- 数据库与向量库的 chunk 级对应关系优先通过 `e_rag_chunk` 建立。
- `chunk_id` 是业务侧 chunk ID，必须同时写入数据库和向量库 metadata。
- `vector_provider`、`vector_collection`、`vector_id` 用于在需要时反查底层向量库中的具体向量点。
- 如果向量库采用“统一 collection + metadata 过滤”的方式，`vector_id` 可以为空，检索时通过向量库 metadata 中的 `knowledgeBaseId` / `fileSetId` / `chunkId` 过滤和回填。
- 如果向量库采用“每个知识库一个 collection”的方式，`e_rag_knowledge_base.vector_collection` 是知识库级定位信息，`e_rag_chunk.vector_id` 是 chunk 级定位信息。

### 8.4 字段约束与状态枚举

#### 必须字段

所有 RAG 业务表必须包含以下字段，并保持语义一致：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `create_by` | `varchar(64)` | 创建人 |
| `create_time` | `datetime` | 创建时间 |
| `update_by` | `varchar(64)` | 更新人 |
| `update_time` | `datetime` | 更新时间 |
| `is_delete` | `tinyint(1)` | 是否删除，1：正常，2：删除 |

#### 知识库状态

| 值 | 含义 |
| ---: | --- |
| 1 | 处理中 |
| 2 | 就绪 |
| 3 | 部分就绪 |
| 4 | 失败 |

#### 文件集 temporary 字段

| 值 | 含义 |
| ---: | --- |
| 1 | 临时文件集 |
| 2 | 持久文件集 |

#### 软删除

删除知识库、文件集、文件或 chunk 时，默认只更新：

```sql
UPDATE xxx
SET is_delete = 2,
    update_by = ?,
    update_time = NOW()
WHERE id = ?
  AND is_delete = 1;
```

## 9. 向量库元数据设计

命名知识库本身不直接参与向量检索。

向量检索仍应基于内部 ID：

```text
knowledgeBaseId
```

每个 chunk metadata 中应包含：

```json
{
  "file_set_id": "fs_123",
  "fileSetId": "fs_123",
  "knowledge_base_id": "kb_123",
  "knowledgeBaseId": "kb_123",
  "filename": "refund_policy.md",
  "sourceName": "refund_policy.md",
  "tenant_id": "tenant_001",
  "tenantId": "tenant_001",
  "owner_id": "user_001",
  "ownerId": "user_001"
}
```

`knowledgeBaseName` 可以作为辅助 metadata，但不推荐作为检索主键。

推荐：

```json
{
  "knowledgeBaseName": "zsk1"
}
```

仅用于引用展示和调试。

检索主键必须使用：

```json
{
  "knowledgeBaseId": "kb_123"
}
```

原因：

1. 名称可能支持重命名。
2. 名称可能存在作用域。
3. 内部 ID 更稳定。
4. 向量库 metadata 过滤更适合使用不可变 ID。

## 10. 服务层设计

### 10.1 RagIngestionService 新增能力

#### create_knowledge_base_from_file_set

现有方法继续保留。

需要增强：

1. 创建前检查 `fileSet` 是否 ready 或 partial_ready。
2. 创建前检查名称是否重复。
3. 创建后将 `knowledgeBaseId` 写入 chunk metadata。
4. 创建后持久化 state。
5. 返回 `KnowledgeBaseInfo`。

#### get_knowledge_base_by_name

新增方法：

```python
def get_knowledge_base_by_name(
    self,
    name: str,
    *,
    tenant_id: str | None = None,
    owner_id: str | None = None,
    api_key_id: str | None = None,
) -> KnowledgeBaseInfo | None:
    ...
```

行为：

1. 对 name 进行 trim。
2. 在当前作用域查找匹配知识库。
3. 如果找到多个，按 `updated_at` 倒序取最新。
4. 推荐正式实现中通过唯一约束避免多个。

#### resolve_knowledge_base_names

新增方法：

```python
def resolve_knowledge_base_names(
    self,
    names: list[str],
    *,
    tenant_id: str | None = None,
    owner_id: str | None = None,
    api_key_id: str | None = None,
) -> list[KnowledgeBaseInfo]:
    ...
```

行为：

1. 逐个解析名称。
2. 若任一名称不存在，抛出 `KeyError` 或自定义异常。
3. 结果按输入顺序返回。
4. 对重复知识库 ID 去重。

### 10.2 RagStreamRequest source 解析

现有逻辑：

```python
request.get_sources()
```

当前只解析：

- `knowledgeBaseId`
- `fileSetId`
- `sources`

新增后，不能直接在模型层访问数据库，因此建议：

1. `RagStreamRequest.get_sources()` 保持原逻辑。
2. 在 router 或 service 层增加 named KB 解析。
3. 解析后注入 `request.sources`。
4. 后续仍使用 `build_request_context()`。

流程：

```text
RagStreamRequest
  ↓
get_sources()
  ↓
get_knowledge_base_names()
  ↓
resolve_knowledge_base_names()
  ↓
merge sources
  ↓
build_request_context()
  ↓
RAG MCP tools
  ↓
retriever
```

## 11. Router 设计

### 11.1 /rag/files

新增表单参数：

```python
knowledge_base_name: str | None = Form(alias="knowledgeBaseName")
knowledge_base_description: str | None = Form(alias="knowledgeBaseDescription")
```

处理流程：

```text
接收文件
  ↓
解析 metadata
  ↓
ingest_files()
  ↓
如果 knowledgeBaseName 为空：
    返回原 UploadFileResponse
  ↓
如果 knowledgeBaseName 不为空：
    create_knowledge_base_from_file_set()
  ↓
返回 UploadFileResponse + knowledgeBase
```

注意：

- 如果文件索引失败，不创建知识库。
- 如果 fileSet 状态是 `ready` 或 `partial_ready` 且 indexed_chunks > 0，可以创建。
- 如果知识库名称重复，返回错误。
- 如果创建知识库失败，不应删除已经创建的 fileSet，除非后续明确要求事务化。

### 11.2 /rag/stream

处理流程：

```text
接收 RagStreamRequest
  ↓
解析 knowledgeBaseName / knowledgeBaseNames
  ↓
解析为 knowledgeBaseId sources
  ↓
合并 request.get_sources()
  ↓
如果没有任何 source，返回 missing_sources
  ↓
build_request_context()
  ↓
stream_claude_sdk()
```

### 11.3 /agent-sdk/rag/stream

该接口也应支持相同能力。

因为该接口通常复用同一个 `RagStreamRequest` 和 RAG runner，因此应复用同一套 source 解析函数，避免两个入口行为不一致。

推荐抽出函数：

```python
def resolve_request_sources(request: RagStreamRequest) -> list[RagSource]:
    ...
```

两个 stream 入口都调用它。

## 12. Source 合并与去重规则

### 12.1 输入来源

可能来自：

1. `knowledgeBaseId`
2. `fileSetId`
3. `sources`
4. `knowledgeBaseName`
5. `knowledgeBaseNames`

### 12.2 合并顺序

推荐顺序：

```text
1. 显式 sources
2. knowledgeBaseId
3. fileSetId
4. knowledgeBaseName / knowledgeBaseNames
```

但当前 `get_sources()` 中如果有显式 `sources`，会忽略兼容字段。

为避免破坏兼容，推荐策略：

- 若传入 `sources`，保留 `sources`。
- 同时仍允许额外解析 `knowledgeBaseName` / `knowledgeBaseNames` 并追加。
- `knowledgeBaseId` / `fileSetId` 继续由 `get_sources()` 处理。

### 12.3 去重 key

```text
source.type + ":" + source.id
```

示例：

```text
knowledge_base:kb_123
file_set:fs_123
```

如果重复，以第一次出现为准。

## 13. 权限与隔离

### 13.1 作用域字段

当前模型中已有：

```text
tenantId
ownerId
apiKeyId
```

命名知识库解析时应使用这些字段进行隔离。

### 13.2 名称唯一性

推荐唯一约束：

```text
tenantId + ownerId + name
```

如果 `tenantId` 或 `ownerId` 为空，短期可采用以下策略：

1. 如果都为空，则全局唯一。
2. 如果有 `tenantId`，按 `tenantId + name` 唯一。
3. 如果有 `tenantId + ownerId`，按 `tenantId + ownerId + name` 唯一。

长期建议统一要求创建知识库时必须携带 owner scope。

### 13.3 查询隔离

当请求中携带权限 metadata：

```json
{
  "metadata": {
    "tenantId": "tenant_001",
    "ownerId": "user_001"
  }
}
```

则名称解析必须只查该作用域下的知识库。

如果未携带权限 metadata，则只能解析无作用域或全局知识库。

## 14. 错误码设计

### 14.1 knowledge_base_name_required

当某些未来接口强制要求名称但未传时使用。

本次暂不需要。

### 14.2 knowledge_base_not_found

名称不存在。

```json
{
  "code": "knowledge_base_not_found",
  "message": "Knowledge base name not found: zsk1"
}
```

### 14.3 knowledge_base_name_conflict

同一作用域名称重复。

```json
{
  "code": "knowledge_base_name_conflict",
  "message": "Knowledge base name already exists: zsk1"
}
```

### 14.4 knowledge_base_not_ready

文件集尚未完成索引，不能创建知识库。

```json
{
  "code": "knowledge_base_not_ready",
  "message": "File set is not ready for knowledge base creation"
}
```

### 14.5 missing_sources

没有任何检索来源。

```json
{
  "code": "missing_sources",
  "message": "Provide fileSetId, knowledgeBaseId, knowledgeBaseName, knowledgeBaseNames, or sources."
}
```

## 15. 向后兼容性

本需求必须保证：

### 15.1 原上传接口兼容

原请求：

```http
POST /rag/files
```

只传文件，不传 `knowledgeBaseName`。

行为不变：

- 返回 `fileSetId`。
- 不自动创建知识库。
- 可以继续基于 `fileSetId` 问答。

### 15.2 原 knowledgeBaseId 问答兼容

原请求：

```json
{
  "message": "xxx",
  "knowledgeBaseId": "kb_123"
}
```

行为不变。

### 15.3 原 sources 兼容

原请求：

```json
{
  "message": "xxx",
  "sources": [
    {
      "type": "knowledge_base",
      "id": "kb_123"
    }
  ]
}
```

行为不变。

### 15.4 原数据兼容

已存在的知识库如果有 `name` 字段，则可以被名称解析。

已存在但没有名称的知识库不受影响，只能继续通过 `knowledgeBaseId` 使用。

## 16. 测试计划

### 16.1 单元测试

#### 测试：上传文件后可创建命名知识库

步骤：

1. 调用 ingestion ingest 文件。
2. 调用 create knowledge base，name 为 `zsk1`。
3. 断言返回 `KnowledgeBaseInfo.name == "zsk1"`。
4. 断言 `knowledgeBaseId` 以 `kb_` 开头。
5. 断言 sourceFileSetId 等于上传得到的 fileSetId。

#### 测试：可以按名称解析知识库

步骤：

1. 创建名为 `zsk1` 的知识库。
2. 调用 `resolve_knowledge_base_names(["zsk1"])`。
3. 断言返回的 `knowledgeBaseId` 正确。

#### 测试：按名称检索命中对应知识库

步骤：

1. 创建 `zsk1`，内容为退款政策。
2. 创建 `zsk2`，内容为物流政策。
3. 基于 `zsk1` 解析出的 `knowledgeBaseId` 搜索退款问题。
4. 断言结果只来自 `zsk1`。
5. 基于 `zsk2` 搜索物流问题。
6. 断言结果只来自 `zsk2`。

#### 测试：同作用域重名失败

步骤：

1. tenant `tenant_001` 下创建 `zsk1`。
2. 再次在 tenant `tenant_001` 下创建 `zsk1`。
3. 断言抛出名称冲突错误。

#### 测试：不同作用域允许同名

步骤：

1. tenant `tenant_001` 下创建 `zsk1`。
2. tenant `tenant_002` 下创建 `zsk1`。
3. 断言两个知识库创建成功。
4. 断言两个 `knowledgeBaseId` 不同。

#### 测试：名称不存在

步骤：

1. 不创建 `zsk_unknown`。
2. 调用名称解析。
3. 断言抛出 not found 错误。

#### 测试：服务重启后名称仍可解析

适用于 SQLite state store。

步骤：

1. 使用临时 SQLite 文件创建 ingestion service。
2. 创建 `zsk1`。
3. 重新初始化 ingestion service，加载同一个 SQLite 文件。
4. 解析 `zsk1`。
5. 断言能找到原 `knowledgeBaseId`。

### 16.2 API 测试

#### POST /rag/files 不传 knowledgeBaseName

断言：

- 返回原结构。
- 不包含 `knowledgeBase` 或其为 null。
- 原有测试不需要修改。

#### POST /rag/files 传 knowledgeBaseName

断言：

- 返回 `fileSetId`。
- 返回 `knowledgeBase`。
- `knowledgeBase.name == "zsk1"`。
- `knowledgeBase.sourceFileSetId == fileSetId`。

#### POST /rag/stream 传 knowledgeBaseName

断言：

- 不返回 missing_sources。
- 会解析为对应 `knowledgeBaseId`。
- 检索 scope 正确。

#### POST /agent-sdk/rag/stream 传 knowledgeBaseName

断言：

- 和 `/rag/stream` 行为一致。

## 17. 实现步骤建议

### Phase 1：最小可用

1. 扩展 `RagStreamRequest`：
   - `knowledgeBaseName`
   - `knowledgeBaseNames`

2. 扩展 `UploadFileResponse`：
   - `knowledgeBase`

3. 扩展 `/rag/files`：
   - 新增 `knowledgeBaseName`
   - 新增 `knowledgeBaseDescription`
   - 上传完成后自动创建知识库

4. 扩展 `RagIngestionService`：
   - `get_knowledge_base_by_name`
   - `resolve_knowledge_base_names`
   - 重名检查

5. 扩展 stream source 解析：
   - 名称转 `knowledgeBaseId`
   - 合并 source
   - 去重

6. 添加测试。

### Phase 2：数据库结构化

1. 新增结构化表：
   - `rag_knowledge_bases`
   - `rag_file_sets`
   - `rag_files`
   - 可选 `rag_chunks`

2. 将 JSON snapshot 迁移为结构化存储。

3. 增加唯一索引：

```sql
UNIQUE(tenant_id, owner_id, name)
```

4. 增强列表、删除、重命名接口。

### Phase 3：知识库管理能力

1. 支持重命名：

```http
PATCH /rag/knowledge-bases/{knowledgeBaseId}
```

2. 支持删除：

```http
DELETE /rag/knowledge-bases/{knowledgeBaseId}
```

3. 支持按名称查询：

```http
GET /rag/knowledge-bases?name=zsk1
```

4. 支持前端知识库列表展示。

## 18. Embedding 一致性与偏移修正策略

### 18.1 问题背景

接入真实 embedding provider 后，系统需要避免以下偏差：

- 文档入库阶段使用一个 embedding provider。
- 查询检索阶段使用另一个 embedding provider。
- 历史 SQLite snapshot 中保存的 embedding 维度与当前模型维度不一致。
- 系统未检测上述偏差时，最终表现为“检索不到结果”，但用户无法知道根因。

例如：

```text
历史向量：LocalHashEmbeddingProvider，256 维
当前模型：BGE-M3，1024 维
```

如果不做校验，系统可能静默返回低分或无结果。

### 18.2 修正原则

采用系统控制论的偏移修正策略：

1. **单点真值**
   - 所有模块必须通过统一 embedding factory 获取 embedder。
   - 禁止 ingestion、retriever 等模块各自实例化 embedding provider。

2. **启动偏差检测**
   - 服务启动时调用 embedding provider 做健康检查。
   - 检测当前模型真实返回的向量维度。
   - 输出 provider、model、dimension 等信息。

3. **持久化元信息**
   - SQLite snapshot 中记录 embedding profile。
   - 包括 provider、model、dimension、base_url。
   - 加载历史向量时检查维度是否与当前 embedding provider 一致。

4. **运行时防护**
   - 写入向量时检查新向量维度与已有向量维度是否一致。
   - 检索时如果 query embedding 与 stored embedding 维度不一致，必须告警。
   - 不允许混合不同维度的向量。

### 18.3 当前实现

当前实现新增：

```text
app/services/rag/embedding_factory.py
```

职责：

- 统一创建 embedding provider。
- 暴露 `get_embedder()`。
- 暴露 `health_check()`。
- 记录 `EmbeddingProfile`。

示例：

```python
EmbeddingProfile(
    provider="openai_compatible",
    model="bge-m3:latest",
    dimension=1024,
    base_url="http://zktz.4c888.com:62011/v1",
)
```

`app/main.py` 的 lifespan 启动阶段会执行 embedding health check，并输出当前模型画像。

SQLite snapshot 从 `version: 1` 升级到 `version: 2`，增加：

```json
{
  "embeddingProfile": {
    "provider": "openai_compatible",
    "model": "bge-m3:latest",
    "dimension": 1024,
    "base_url": "http://zktz.4c888.com:62011/v1"
  }
}
```

`LocalVectorStore.upsert_chunks()` 会校验新写入向量与已有向量维度是否一致，防止同一个本地向量库中混入不同维度的 embedding。

## 19. 推荐接口示例

### 19.1 创建 zsk1

```bash
curl -X POST "http://localhost:8000/rag/files" \
  -H "Authorization: Bearer <api-key>" \
  -F "file=@policy.md" \
  -F "knowledgeBaseName=zsk1" \
  -F "knowledgeBaseDescription=售后政策知识库"
```

返回：

```json
{
  "fileSetId": "fs_abcd",
  "status": "ready",
  "files": [
    {
      "fileId": "file_abcd",
      "filename": "policy.md",
      "mimeType": "text/markdown",
      "size": 1280,
      "status": "ready"
    }
  ],
  "knowledgeBase": {
    "knowledgeBaseId": "kb_abcd",
    "name": "zsk1",
    "description": "售后政策知识库",
    "sourceFileSetId": "fs_abcd",
    "status": "ready",
    "createdAt": "2026-05-25T10:00:00Z",
    "updatedAt": "2026-05-25T10:00:00Z",
    "metadata": {}
  }
}
```

### 19.2 基于 zsk1 问答

```bash
curl -X POST "http://localhost:8000/rag/stream" \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "请总结退款政策",
    "knowledgeBaseName": "zsk1"
  }'
```

### 19.3 基于 zsk1 和 zsk2 对比

```bash
curl -X POST "http://localhost:8000/rag/stream" \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "比较两个知识库中的退款周期差异",
    "knowledgeBaseNames": ["zsk1", "zsk2"]
  }'
```

### 19.4 继续使用 knowledgeBaseId

```bash
curl -X POST "http://localhost:8000/rag/stream" \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "请总结退款政策",
    "knowledgeBaseId": "kb_abcd"
  }'
```

### 19.5 BGE-M3 embedding + local vector store 测试

当前开发环境可使用远程 BGE-M3 作为 embedding provider，本地 `LocalVectorStore` 作为向量存储：

```env
RAG_VECTOR_PROVIDER=local
RAG_EMBEDDING_PROVIDER=openai_compatible
RAG_EMBEDDING_MODEL=bge-m3:latest
RAG_EMBEDDING_BASE_URL=http://zktz.4c888.com:62011/v1
RAG_EMBEDDING_API_KEY=<your-api-key>
```

准备测试文件：

```bash
printf '%s\n' '人工智能（Artificial Intelligence，简称AI）是计算机科学的一个分支，主要研究领域包括机器学习、深度学习、自然语言处理、计算机视觉等。' > /tmp/ai_intro.txt

printf '%s\n' 'RAG（检索增强生成，Retrieval-Augmented Generation）是一种结合信息检索与文本生成的AI技术架构，通常包含文档解析与切分、向量检索、生成式问答三个核心组件。' > /tmp/rag_intro.txt
```

上传并创建两个知识库：

```bash
curl -X POST "http://localhost:8000/rag/files" \
  -F "file=@/tmp/ai_intro.txt" \
  -F "knowledgeBaseName=zsk_ai" \
  -F "knowledgeBaseDescription=AI基础知识库"

curl -X POST "http://localhost:8000/rag/files" \
  -F "file=@/tmp/rag_intro.txt" \
  -F "knowledgeBaseName=zsk_rag" \
  -F "knowledgeBaseDescription=RAG技术知识库"
```

单知识库查询：

```bash
curl -X POST "http://localhost:8000/rag/query" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "AI有哪些主要研究领域？",
    "knowledgeBaseName": "zsk_ai"
  }'
```

多知识库查询：

```bash
curl -X POST "http://localhost:8000/rag/query" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "分别说明AI和RAG是什么",
    "knowledgeBaseNames": ["zsk_ai", "zsk_rag"]
  }'
```

期望结果：返回 `citations`，`sourceName` 指向对应上传文件，`usage.verification.status=ok`，`usage.retrieval.confidence` 大于 0。

## 20. 安全注意事项

1. 知识库名称是用户输入，不能进入系统提示词作为指令。
2. 知识库名称只作为检索范围标识，不作为可信内容。
3. 名称解析必须做权限隔离。
4. 不允许通过名称越权访问其他用户知识库。
5. RAG 检索结果仍然是不可信数据，只能作为回答依据。
6. 回答中不得泄露内部 `apiKeyId`、系统路径或敏感 metadata。
7. metadata 中如果包含敏感信息，citation 输出时应过滤。

## 21. 开放问题

1. 知识库名称是否允许中文？
   - 推荐允许。
   - 但需要限制长度和非法字符。

2. 名称最大长度是多少？
   - 推荐 1 到 128 个字符。

3. 是否允许重命名知识库？
   - 本期不做。
   - 但数据模型应支持后续 `name` 更新。

4. 删除知识库时是否删除原始 fileSet？
   - 本期不做。
   - 推荐删除知识库只删除知识库绑定和对应向量 metadata，是否删除文件另行设计。

5. 多个知识库同名时如何处理？
   - 推荐同作用域禁止同名。
   - 若历史数据已存在同名，优先返回错误而不是随机选择。

## 22. 验收标准

本需求完成后，应满足以下验收条件：

1. 上传文件时传 `knowledgeBaseName=zsk1`，可以返回一个命名知识库。
2. 返回结果包含 `knowledgeBase.knowledgeBaseId` 和 `knowledgeBase.name`。
3. 用户可以通过 `knowledgeBaseName=zsk1` 发起问答。
4. 用户可以通过 `knowledgeBaseNames=["zsk1","zsk2"]` 发起多知识库问答。
5. 原有 `fileSetId` 问答不受影响。
6. 原有 `knowledgeBaseId` 问答不受影响。
7. 原有 `sources` 问答不受影响。
8. 服务重启后，已创建的 `zsk1` 仍然可以解析。
9. 同作用域下重复创建 `zsk1` 会返回冲突错误。
10. 不同作用域下可以创建同名知识库。
11. 检索结果不会跨知识库污染。
12. RAG citation 能正确显示来源文件或 chunk。
13. 所有新增测试通过。
14. 现有 RAG MVP 测试通过。
15. 使用 `RAG_EMBEDDING_PROVIDER=openai_compatible` 配置 BGE-M3 后，上传文件可以成功生成 embedding。
16. 查询时使用同一个 embedding provider 生成 query embedding。
17. `/rag/query` 能返回 citation、sourceName、score、confidence。
18. SQLite snapshot 中记录 embedding profile。
19. 切换 embedding 模型导致维度不一致时，系统能输出明确 warning，而不是静默返回无结果。
20. `LocalVectorStore` 不允许混入不同维度的向量。

## 23. 总结

本需求的核心是为“文件生成的知识库”增加用户可读名称，并将该名称持久化存储。

推荐最终流程：

```text
上传文件 + knowledgeBaseName
  ↓
生成 fileSetId
  ↓
解析 / chunk / embedding / index
  ↓
创建 knowledgeBaseId
  ↓
数据库保存 name -> knowledgeBaseId
  ↓
chunk metadata 写入 knowledgeBaseId
  ↓
用户通过 knowledgeBaseName 问答
  ↓
服务端解析 name -> knowledgeBaseId
  ↓
沿用现有 RAG 检索和 Agent 回答链路
```

该设计可以在不破坏现有文档知识库问答的前提下，增强文件知识库的可管理性、可记忆性和可持续使用能力。
