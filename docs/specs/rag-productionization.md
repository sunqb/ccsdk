 # RAG 产品化规格说明

## 1. 背景

当前项目已经具备 RAG MVP 到增强版的核心能力：

- 文件上传、解析、切分、embedding、索引入库。
- 基于 `fileSetId` 的临时文件问答。
- 基于 `knowledgeBaseId` 的持久知识库问答。
- 基于 `knowledgeBaseName` 的命名知识库管理设计。
- Claude Agent SDK + request-scoped in-process MCP RAG tools。
- `rag_hybrid_search`、`rag_read_chunk`、`rag_get_file_outline`、`rag_list_sources` 等工具接口。
- `EmbeddingProvider` 与 `VectorStore` 抽象。
- 本地 `LocalVectorStore` 与 SQLite snapshot，用于开发和单机验证。
- MinerU 文档解析服务接入方向，用于 PDF / DOCX / 扫描件 / 合同等复杂文档。

现阶段的主要问题不是“是否需要重新选择一个 RAG 框架”，而是如何把已有 RAG 能力产品化、生产化、平台化。

本规格说明围绕以下目标展开：

1. 保留当前自研 RAG 主链路。
2. 通过 Factory / Provider 机制替换底层基础设施。
3. 优先把 `LocalVectorStore` 升级为可切换的生产级向量库实现，第一优先级为 Qdrant。
4. 补齐产品化所需的任务队列、权限、多租户、观测、计费、Admin API、质量评测、生命周期管理等能力。
5. 为后续 Graph RAG、外部知识库注册、企业级私有化部署预留扩展点。

## 2. 产品化目标

### 2.1 核心目标

RAG 产品化版本需要支持：

1. **生产级知识库管理**
   - 创建、更新、查询、删除知识库。
   - 支持 `knowledgeBaseName -> knowledgeBaseId`。
   - 支持临时 fileSet 提升为持久知识库。
   - 支持多知识库联合检索与对比问答。

2. **生产级文档入库**
   - 支持 TXT / Markdown。
   - 支持 PDF / DOCX 等复杂文档通过 MinerU 解析。
   - 支持大文件、批量文件、失败重试、异步任务队列。
   - 支持文件级、chunk 级、任务级状态追踪。

3. **生产级向量存储**
   - 保留 `LocalVectorStore` 用于开发。
   - 新增 `VectorStoreFactory`。
   - 第一阶段实现 `QdrantVectorStore`。
   - 后续扩展 `PgVectorStore`、`MilvusVectorStore`、`ChromaVectorStore`、`WeaviateVectorStore`。

4. **准确可靠的检索问答**
   - 支持向量检索、关键词检索、混合检索。
   - 支持 query rewrite、rerank、context expansion、citation。
   - 证据不足时拒答或提示资料不足。
   - 服务端结构化记录 citations、tool calls、usage、trace。

5. **企业级能力**
   - 多租户权限隔离。
   - API Key / owner / tenant 维度审计。
   - 计费统计。
   - 监控告警。
   - Admin API。
   - 数据保留、清理、删除、重建索引。

### 2.2 非目标

第一阶段产品化不做以下事项：

- 不整体替换为 RAGFlow / LangChain / LlamaIndex / Verba。
- 不强制引入 Graph RAG。
- 不实现完整知识库前端管理后台。
- 不在第一阶段支持所有文档格式。
- 不在第一阶段实现所有向量库 provider。
- 不把外部平台作为唯一知识库后端。

## 3. 总体架构

推荐架构：

```text
Client / SDK / Admin Console
  |
  |-- POST /rag/files
  |-- POST /rag/query
  |-- POST /rag/stream
  |-- POST /agent-sdk/rag/stream
  |-- /rag/knowledge-bases/*
  |-- /rag/admin/*
  v
FastAPI RAG Router
  |
  |-- Auth / Tenant Context
  |-- Request Scope Builder
  |-- Concurrency Guard
  v
RAG Application Services
  |
  |-- RagIngestionService
  |-- RagKnowledgeBaseService
  |-- RagQueryService
  |-- RagAdminService
  |-- RagBillingService
  v
RAG Core
  |
  |-- DocumentParser
  |-- TextChunker
  |-- EmbeddingProvider
  |-- VectorStore
  |-- RagRetriever
  |-- RagToolService
  |-- Citation Builder
  |-- Answer Verifier
  v
Provider Factories
  |
  |-- ParserFactory
  |-- EmbeddingFactory
  |-- VectorStoreFactory
  |-- RerankerFactory
  v
Infrastructure
  |
  |-- MySQL Metadata Store
  |-- Qdrant / pgvector / Milvus / Local
  |-- MinerU Parser Service
  |-- Object Storage
  |-- Queue / Worker
  |-- Metrics / Logs / Traces
```

核心原则：

- Router 只做 HTTP / SSE 编排，不承载复杂业务逻辑。
- Ingestion、KnowledgeBase、Query、Admin、Billing 分层拆分。
- RAG Core 只依赖抽象接口，不依赖具体 provider。
- 具体 provider 由 Factory 根据配置创建。
- 所有检索必须经过 request-scoped source scope 和权限过滤。
- 文档内容永远是不可信输入，只能作为证据，不得作为系统指令执行。

## 4. Provider Factory 设计

### 4.1 为什么需要 Factory

当前项目已经有 `EmbeddingProvider` 抽象和 `embedding_factory.py`。向量库应采用同样模式。

目标：

```text
RAG_VECTOR_PROVIDER=local   -> LocalVectorStore
RAG_VECTOR_PROVIDER=qdrant  -> QdrantVectorStore
RAG_VECTOR_PROVIDER=pgvector -> PgVectorStore
RAG_VECTOR_PROVIDER=milvus  -> MilvusVectorStore
```

这样可以保证：

- 不修改 `RagIngestionService` 即可切换向量库。
- 不重写 embedding、chunking、retrieval 逻辑。
- 不让业务服务感知 Qdrant / pgvector / Milvus 的 SDK 细节。
- 多向量库扩展只新增 provider 实现与 factory 注册项。

### 4.2 推荐模块

第一阶段建议新增：

```text
app/services/rag/vector_store_factory.py
app/services/rag/qdrant_vector_store.py
```

后续可整理为：

```text
app/services/rag/vector_stores/
├── base.py
├── local.py
├── qdrant.py
├── pgvector.py
├── milvus.py
├── chroma.py
└── factory.py
```

### 4.3 VectorStoreFactory 职责

`VectorStoreFactory` 负责：

1. 读取 `settings.rag_vector_provider`。
2. 校验 provider 所需配置。
3. 创建并缓存全局 `VectorStore` 实例。
4. 为外部向量库传入 embedding dimension。
5. 暴露 provider health / capability 信息。
6. 提供测试用 reset 方法。

推荐伪代码：

```python
_VECTOR_STORE_BUILDERS = {
    "local": _build_local_vector_store,
    "qdrant": _build_qdrant_vector_store,
    "pgvector": _build_pgvector_vector_store,
    "milvus": _build_milvus_vector_store,
}


def get_vector_store() -> VectorStore:
    provider = settings.rag_vector_provider
    try:
        builder = _VECTOR_STORE_BUILDERS[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported RAG_VECTOR_PROVIDER: {provider}") from exc
    return builder()
```

### 4.4 是否需要 Abstract Factory

当前阶段不需要 Abstract Factory。

当前只需要创建一个产品：

```text
VectorStore
```

使用普通 Factory + Registry 即可。

未来如果同一个 backend 需要同时创建以下对象：

```text
VectorStore
KeywordStore
DocumentStore
JobStore
AuditStore
```

才考虑演进为 Abstract Factory，例如：

```text
QdrantRagBackendFactory
PgVectorRagBackendFactory
MilvusRagBackendFactory
```

## 5. QdrantVectorStore 设计

### 5.1 定位

Qdrant 是第一优先级生产向量库 provider。

原因：

- 部署轻量。
- Python SDK 成熟。
- payload filter 能力适合 tenant / owner / knowledgeBase / fileSet 过滤。
- 支持 collection 管理。
- 后续可以扩展 dense + sparse hybrid search。

### 5.2 配置

新增配置：

```env
RAG_VECTOR_PROVIDER=qdrant
RAG_QDRANT_URL=http://localhost:6333
RAG_QDRANT_API_KEY=
RAG_QDRANT_COLLECTION=rag_chunks
RAG_QDRANT_TIMEOUT_SECONDS=30
RAG_QDRANT_CREATE_COLLECTION=true
```

### 5.3 Collection 策略

第一阶段推荐：

```text
一个全局 collection：rag_chunks
通过 payload 实现隔离和过滤
```

不建议第一阶段采用“一个知识库一个 collection”。

原因：

- collection 数量膨胀会增加运维复杂度。
- 多知识库联合检索更复杂。
- 通过 payload filter 已经可以满足 tenant / owner / knowledgeBase 过滤。

### 5.4 Payload 字段

每个 Qdrant point 至少包含：

```json
{
  "chunk_id": "chunk_xxx",
  "file_set_id": "fs_xxx",
  "knowledge_base_id": "kb_xxx",
  "source_file_id": "file_xxx",
  "filename": "contract.pdf",
  "tenant_id": "tenant_xxx",
  "owner_id": "owner_xxx",
  "api_key_id": "ak_xxx",
  "chunk_index": 0,
  "chunk_text": "...",
  "headingPath": ["第一章", "付款条款"],
  "sectionTitle": "付款条款",
  "parser": "mineru",
  "embedding_provider": "openai_compatible",
  "embedding_model": "bge-m3:latest",
  "embedding_dimension": 1024
}
```

注意：

- `api_key_id` 只能保存 API Key 标识，不能保存明文密钥。
- `chunk_text` 可保存在 Qdrant payload 中，也可只保存到 MySQL `e_rag_chunk`，Qdrant 只保存引用。第一阶段为了检索返回简单，可以先保存必要文本。
- 长期建议 MySQL 作为 chunk metadata 单点，Qdrant 存储向量和最小检索 payload。

### 5.5 必须实现的方法

`QdrantVectorStore` 必须实现当前 `VectorStore` 契约，包括：

```text
upsert_chunks
vector_search
keyword_search
hybrid_search
read_chunk
list_sources
delete_file_set / cleanup_expired，如当前接口已有则补齐
```

第一阶段允许：

- `vector_search` 使用 Qdrant dense vector search。
- `keyword_search` 暂时沿用 metadata DB / 本地文本匹配 / 简化实现。
- `hybrid_search` 仍在 `RagRetriever` 层融合 vector 与 keyword 结果。

后续再升级为 Qdrant dense + sparse 原生混合检索。

### 5.6 Embedding 维度

Qdrant collection 创建时必须使用 `EmbeddingFactory` 暴露的维度，不允许硬编码。

```text
BGE-M3: 1024
OpenAI text-embedding-3-small: 1536
OpenAI text-embedding-3-large: 3072
```

如果 embedding 模型或维度变化：

- 禁止向已有 collection 混写不同维度向量。
- 需要新建 collection，或触发重建索引。
- `e_rag_knowledge_base.embedding_dimension` 与 `e_rag_chunk.embedding_dimension` 必须记录当时入库维度。

## 6. 元数据与状态存储

### 6.1 MySQL 作为生产元数据单点

当前 SQLite snapshot 适合开发环境，但生产环境需要 MySQL 元数据表作为单点真值。

生产化后的存储职责必须明确分层：

```text
MySQL = RAG metadata 单点真值
Qdrant = 生产向量数据库
SQLite = local 模式下的本地向量/状态 fallback，不再承担生产 metadata
```

具体约束：

- 所有生产级 `fileSet`、文件、chunk、knowledgeBase、ingestion job、query/tool/usage/audit metadata 均以 MySQL 为准。
- Qdrant 只保存向量和检索所需的最小 payload；第一阶段可保留 `chunk_text` 方便检索返回，但长期 chunk metadata 仍以 MySQL 为准。
- SQLite snapshot 仅用于 `RAG_VECTOR_PROVIDER=local` 的开发、单机验证和本地向量/状态 fallback。
- 当 `RAG_VECTOR_PROVIDER=qdrant` 或其他生产向量库时，不允许依赖 SQLite 作为生产 metadata 存储。

已有 SQL 设计包括：

- `e_rag_knowledge_base`
- `e_rag_file_set`
- `e_rag_file`
- `e_rag_chunk`

产品化还需要补充：

- `e_rag_ingestion_job`
- `e_rag_query_log`
- `e_rag_tool_call_log`
- `e_rag_usage_daily`
- `e_rag_audit_log`
- `e_rag_provider_health`

### 6.2 建议新增表：ingestion job

用于异步入库任务：

```text
e_rag_ingestion_job
- job_id
- file_set_id
- knowledge_base_id
- tenant_id
- owner_id
- api_key_id
- status: pending/running/succeeded/partial_failed/failed/cancelled
- stage: uploaded/parsing/chunking/embedding/indexing/finalizing
- progress_percent
- retry_count
- max_retries
- error_code
- error_message
- started_time
- finished_time
- create_time
- update_time
```

### 6.3 建议新增表：query log

用于质量追踪、审计与计费：

```text
e_rag_query_log
- query_id
- conversation_id
- tenant_id
- owner_id
- api_key_id
- message
- source_scope_json
- retrieval_top_k
- matched_chunks
- citation_count
- confidence
- abstained
- latency_ms
- prompt_tokens
- completion_tokens
- embedding_tokens
- model
- create_time
```

### 6.4 建议新增表：tool call log

用于 Agentic RAG 可观测性：

```text
e_rag_tool_call_log
- tool_call_id
- query_id
- tool_name
- tool_args_json
- result_count
- latency_ms
- error_code
- error_message
- create_time
```

### 6.5 建议新增表：usage daily

用于计费与配额：

```text
e_rag_usage_daily
- stat_date
- tenant_id
- owner_id
- api_key_id
- uploaded_files
- uploaded_bytes
- parsed_pages
- chunks_created
- embedding_tokens
- query_count
- retrieval_count
- prompt_tokens
- completion_tokens
- storage_bytes
- create_time
- update_time
```

## 7. 文档解析产品化

### 7.1 Parser 策略

生产环境推荐：

```env
RAG_PARSER_PROVIDER=mineru
MINERU_BASE_URL=https://mineru.internal.example
MINERU_API_KEY=
MINERU_TIMEOUT_SECONDS=120
MINERU_FALLBACK_TO_LOCAL=false
```

解析路由：

| 文件类型 | 默认解析方式 | 说明 |
| --- | --- | --- |
| `.txt` | local | 直接解码 |
| `.md` | local | 保留 Markdown 标题 |
| `.pdf` | MinerU | 生产推荐 |
| `.docx` | MinerU | 生产推荐 |
| `.pptx` | 后续扩展 | 可通过 MinerU 或专用 parser |
| `.xlsx` | 后续扩展 | 需要表格结构化策略 |

### 7.2 解析质量指标

需要采集：

- 解析耗时。
- 文件页数。
- OCR 是否启用。
- 表格数量。
- 图片数量。
- 输出字符数。
- chunk 数量。
- 解析失败率。
- fallback 次数。

### 7.3 安全边界

- 文档内容是不可信输入。
- Parser 输出不得包含内部路径、密钥、异常栈。
- Parser metadata 中的租户和用户信息必须由服务端认证上下文写入，不信任客户端传入。
- MinerU 输出只进入 chunk / embedding / retrieval，不直接拼接为系统指令。

## 8. 异步入库任务

### 8.1 为什么需要异步

当前 `RagIngestionService.ingest_files` 是请求内 inline ingestion。生产环境存在问题：

- 大文件解析耗时长。
- PDF / DOCX / OCR 不稳定。
- embedding 调用可能超时或限流。
- Qdrant / 外部向量库可能短暂不可用。
- HTTP 请求不适合承载长任务。

### 8.2 推荐任务状态机

```text
pending
  ↓
uploaded
  ↓
parsing
  ↓
chunking
  ↓
embedding
  ↓
indexing
  ↓
finalizing
  ↓
ready / partial_ready / failed / cancelled
```

### 8.3 API 行为

上传接口应尽快返回：

```json
{
  "fileSetId": "fs_xxx",
  "jobId": "job_xxx",
  "status": "pending"
}
```

客户端通过以下接口轮询：

```http
GET /rag/files/{fileSetId}/status
GET /rag/jobs/{jobId}
```

### 8.4 Retry 策略

建议：

- 网络错误：可重试。
- 解析服务 5xx：可重试。
- embedding 服务限流：指数退避重试。
- 文件格式不支持：不可重试。
- 内容为空：不可重试。
- 向量维度不匹配：不可重试，需要重建索引或切换 collection。

## 9. 检索与回答质量

### 9.1 检索链路

推荐保留当前 Agentic RAG 模式：

```text
用户问题
  ↓
RagAgentRunner.stream_claude_sdk
  ↓
Claude Agent SDK + request-scoped MCP
  ↓
rag_hybrid_search / rag_read_chunk / rag_get_file_outline / rag_list_sources
  ↓
RagToolService 强制 source scope + permission filter
  ↓
RagRetriever 检索、rerank、citation
  ↓
模型基于证据回答
```

### 9.2 质量增强能力

产品化需要具备：

- Query rewrite。
- Multi-query retrieval。
- Dense vector search。
- Keyword search。
- Hybrid merge。
- Rerank。
- Context window expansion。
- Citation builder。
- Answer verifier。
- Abstention policy。
- Multi-file conflict detection。

### 9.3 引用要求

每个 citation 至少包含：

```json
{
  "chunkId": "chunk_xxx",
  "fileSetId": "fs_xxx",
  "knowledgeBaseId": "kb_xxx",
  "knowledgeBaseName": "zsk1",
  "sourceFileId": "file_xxx",
  "filename": "contract.pdf",
  "chunkIndex": 12,
  "score": 0.82,
  "searchType": "hybrid",
  "metadata": {
    "headingPath": ["第一章", "付款条款"],
    "sectionTitle": "付款条款",
    "parser": "mineru",
    "page": 3
  }
}
```

### 9.4 拒答策略

当满足以下任一条件时，应拒答或提示资料不足：

- 没有命中 chunk。
- 命中分数低于阈值。
- citation 无法支持最终结论。
- 用户问题超出 source scope。
- 权限过滤后无可用资料。
- 多来源存在冲突且无法判断。

## 10. 多租户与权限

### 10.1 强制原则

生产环境必须从认证上下文派生：

```text
tenant_id
owner_id
api_key_id
role / scopes
```

不能信任客户端 `metadata` 中传入的租户字段。

### 10.2 Source Scope

所有检索请求必须被转换为服务端 source scope：

```json
{
  "tenantId": "tenant_xxx",
  "ownerId": "owner_xxx",
  "sources": [
    {"type": "knowledge_base", "id": "kb_xxx"},
    {"type": "file_set", "id": "fs_xxx"}
  ]
}
```

检索时必须同时应用：

- tenant filter。
- owner filter。
- api key / role filter。
- source filter。
- `is_delete = active` filter。

### 10.3 命名知识库唯一性

`knowledgeBaseName` 唯一范围：

```text
tenant_id + owner_id + name + is_delete
```

如果后续需要不同 API Key 下允许同名，可调整为：

```text
tenant_id + owner_id + api_key_id + name + is_delete
```

## 11. API 产品化设计

### 11.1 知识库 API

建议补齐：

```http
POST   /rag/knowledge-bases
GET    /rag/knowledge-bases
GET    /rag/knowledge-bases/{knowledgeBaseId}
PATCH  /rag/knowledge-bases/{knowledgeBaseId}
DELETE /rag/knowledge-bases/{knowledgeBaseId}
POST   /rag/knowledge-bases/{knowledgeBaseId}/reindex
POST   /rag/knowledge-bases/{knowledgeBaseId}/rename
```

### 11.2 文件 API

```http
POST   /rag/files
GET    /rag/files/{fileSetId}/status
GET    /rag/files/{fileSetId}
DELETE /rag/files/{fileSetId}
POST   /rag/files/{fileSetId}/promote
```

### 11.3 任务 API

```http
GET    /rag/jobs/{jobId}
POST   /rag/jobs/{jobId}/cancel
POST   /rag/jobs/{jobId}/retry
```

### 11.4 查询 API

```http
POST   /rag/query
POST   /rag/stream
POST   /agent-sdk/rag/stream
```

### 11.5 Admin API

```http
GET    /rag/admin/provider-info
GET    /rag/admin/stats
GET    /rag/admin/jobs
GET    /rag/admin/health
GET    /rag/admin/query-logs
GET    /rag/admin/audit-logs
POST   /rag/admin/cleanup
POST   /rag/admin/orphan-cleanup
POST   /rag/admin/rebuild-index
```

## 12. 计费与配额

### 12.1 计费维度

建议采集：

- 上传文件数。
- 上传字节数。
- 解析页数。
- OCR 页数。
- chunk 数量。
- embedding token 数。
- embedding 请求次数。
- query 次数。
- retrieval 次数。
- Agent token 数。
- 存储字节数。
- 向量数量。
- 知识库数量。

### 12.2 配额维度

建议支持：

- 单租户最大知识库数。
- 单知识库最大文件数。
- 单文件最大大小。
- 单日最大上传量。
- 单日最大 query 数。
- 单日最大 embedding token。
- 单租户最大向量数量。
- 并发 ingestion 限制。
- 并发 query 限制。

## 13. 监控、日志与告警

### 13.1 Metrics

至少需要：

- ingestion job count by status。
- parse latency。
- embedding latency。
- vector upsert latency。
- query latency。
- retrieval latency。
- matched chunk count。
- abstention rate。
- citation count。
- error rate by stage。
- provider health。

### 13.2 Structured Logs

日志必须包含：

```text
request_id
tenant_id
owner_id
api_key_id
file_set_id
knowledge_base_id
job_id
query_id
provider
stage
latency_ms
error_code
```

### 13.3 Alerts

建议告警：

- MinerU 失败率过高。
- Embedding 服务错误率过高。
- Qdrant 不可用。
- 入库任务积压。
- query p95 延迟过高。
- 拒答率异常升高。
- citation 为空比例异常升高。

## 14. 数据生命周期

### 14.1 临时 fileSet

临时 fileSet 应支持 TTL：

```env
RAG_TEMP_FILE_TTL_HOURS=24
```

过期清理需要同时删除：

- metadata DB 记录。
- object storage 原文件。
- parsed markdown。
- chunk metadata。
- vector store points。

### 14.2 持久知识库

持久知识库删除建议采用软删除：

```text
is_delete = 2
```

后台异步任务清理底层向量与对象存储，避免同步删除超时。

### 14.3 Reindex

以下场景需要 reindex：

- embedding 模型变化。
- embedding dimension 变化。
- chunker 参数变化。
- parser 版本变化。
- 文档内容更新。
- 向量库迁移。

## 15. 安全与合规

产品化必须覆盖：

- API Key 明文禁止落库。
- 用户文档内容加密存储，至少支持对象存储服务端加密。
- 文件下载 URL 使用短期签名 URL。
- 敏感日志脱敏。
- metadata 不得泄露内部路径。
- 文档 prompt injection 防护。
- source scope 越权测试。
- Admin API 权限隔离。
- 删除知识库时支持数据清理审计。

## 16. 外部方案定位

当前项目不建议整体替换为外部 RAG 平台。推荐定位如下：

| 方案 | 推荐定位 | 是否作为主架构 |
| --- | --- | --- |
| OpenViking / 火山生态 | 可作为托管向量库或 Agent memory backend | 否 |
| RAGFlow | 可参考文档解析和知识库平台设计；若需要独立 RAG 产品可评估 | 否 |
| LangChain | 可参考 loader / splitter / retriever；不替代当前 Agent SDK + MCP 链路 | 否 |
| Qdrant | 第一优先级生产 VectorStore provider | 是，作为存储层 |
| Chroma | 本地 demo / 原型 | 否 |
| LLMWare | 可评估企业私有化方案，但当前自研更可控 | 否 |
| Verba / Weaviate | 已有 Weaviate 生态时考虑 | 否 |
| LlamaIndex | 后续 Graph RAG / 高级索引增强层 | 否 |

## 17. 分阶段落地计划

### Phase P0：规格与边界确认

目标：

- 明确产品化范围。
- 明确第一生产向量库为 Qdrant。
- 明确 MySQL metadata store 为生产单点真值。
- 明确 MinerU 为生产复杂文档解析 provider。

产出：

- 本规格文档。
- Qdrant provider 子规格。
- 异步 ingestion job 子规格。

### Phase P1：VectorStoreFactory + Qdrant

任务：

1. 新增 `vector_store_factory.py`。
2. 当前 `LocalVectorStore` 改由 factory 创建。
3. 新增 `QdrantVectorStore`。
4. 新增 Qdrant 配置项。
5. `build_provider_info` 中将 qdrant 从 placeholder 升级为真实 capability。
6. 增加 provider factory 单元测试。
7. 增加 Qdrant integration test，可通过环境变量启用。

验收：

- `RAG_VECTOR_PROVIDER=local` 行为不变。
- `RAG_VECTOR_PROVIDER=qdrant` 可完成上传、索引、查询、citation。
- 不修改 embedding / chunking / Agent MCP 主链路。

### Phase P2：MySQL Metadata Store 产品化

任务：

1. 以 `e_rag_knowledge_base`、`e_rag_file_set`、`e_rag_file`、`e_rag_chunk` 为核心元数据表。
2. 新增 ingestion job / query log / usage / audit 表。
3. 将 SQLite snapshot 降级为开发模式实现。
4. 生产环境使用 MySQL store。

验收：

- 多 worker 下状态一致。
- knowledgeBaseName 唯一约束生效。
- chunk 与 vector point 可相互追踪。

### Phase P3：异步入库队列

任务：

1. 上传接口返回 jobId。
2. Worker 执行 parse / chunk / embed / index。
3. 实现 retry / cancel / status。
4. 支持 partial_ready。

验收：

- 大文件上传不阻塞 HTTP。
- 任务失败可观测、可重试。
- 单文件失败不影响其他文件完成。

### Phase P4：权限、审计、计费

任务：

1. 从认证上下文派生 tenant / owner / api_key。
2. 所有查询强制 source scope。
3. 写入 query log / tool call log / audit log。
4. 聚合 usage daily。
5. 补充 Admin API。

验收：

- 越权访问测试通过。
- 按 tenant / apiKey 可查用量。
- Admin API 有权限保护。

### Phase P5：质量评测与运维闭环

任务：

1. 建立标准评测集。
2. 统计命中率、引用准确率、拒答率、幻觉率。
3. 增加监控指标和告警。
4. 支持重建索引和 orphan cleanup。

验收：

- 每次检索策略变更可量化对比。
- 线上问题可通过 query_id 追踪完整链路。

### Phase P6：高级能力

可选：

- Graph RAG。
- 外部知识库注册。
- 多模态检索。
- 表格结构化问答。
- Agent memory backend。
- 知识库版本管理。

## 18. 验收标准

产品化第一版完成后，应满足：

1. `RAG_VECTOR_PROVIDER=local` 开发模式继续可用。
2. `RAG_VECTOR_PROVIDER=qdrant` 生产模式可完成端到端 RAG。
3. 支持 `knowledgeBaseName` 创建、解析、查询。
4. 支持 PDF / DOCX 通过 MinerU 解析入库。
5. 支持 MySQL 元数据持久化。
6. 支持 ingestion job 状态查询。
7. 支持多租户权限过滤。
8. 支持 query log、tool call log、usage 统计。
9. 支持 Admin provider-info、stats、cleanup、job inspection。
10. 支持引用来源和证据不足拒答。
11. 支持基础监控指标和错误告警。
12. 不破坏现有 `/rag/query`、`/rag/stream`、`/agent-sdk/rag/stream` 行为。

## 19. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| Qdrant collection 维度与 embedding 维度不一致 | 入库失败或检索错误 | Factory 初始化时校验维度；模型变化必须 reindex |
| 客户端伪造 tenant metadata | 越权访问 | 租户信息只从认证上下文派生 |
| PDF 解析质量不稳定 | 检索召回差 | MinerU 指标观测；保留解析结果和 parserVersion |
| 大文件入库超时 | 用户体验差 | 异步队列 + job 状态查询 |
| 混合检索实现复杂 | 上线延期 | 第一阶段 Qdrant 只做 dense search，hybrid 继续在 Retriever 层融合 |
| SQLite snapshot 与生产 MySQL 分叉 | 数据不一致 | 明确 SQLite 仅开发使用，生产 MySQL 为单点真值 |
| citation 不准确 | 用户不信任 | citation builder 服务端结构化生成，增加评测集 |
| 删除知识库残留向量 | 存储泄露和成本增加 | orphan cleanup + audit log |

## 20. 推荐优先级

最高优先级：

1. `VectorStoreFactory`。
2. `QdrantVectorStore`。
3. MySQL metadata store 对齐已有 SQL。
4. 异步 ingestion job。
5. 强制多租户 source scope。

第二优先级：

1. Query log / tool call log。
2. Usage daily。
3. Admin job inspection / retry / cleanup。
4. MinerU 解析指标。
5. Qdrant integration tests。

第三优先级：

1. pgvector / Milvus provider。
2. Qdrant sparse vector hybrid。
3. Graph RAG。
4. 外部知识库注册。
5. 知识库版本管理。

## 21. 最终建议

当前项目已经具备 RAG 产品化的正确基础：

- Agentic RAG 路线明确。
- MCP 工具边界清晰。
- Embedding 与 VectorStore 已解耦。
- 命名知识库设计已经贴近产品使用方式。
- MinerU 文档解析方向合理。

下一步不应切换到完整外部 RAG 平台，而应按以下路径推进：

```text
当前自研 RAG 架构
  + VectorStoreFactory
  + QdrantVectorStore
  + MySQL Metadata Store
  + MinerU Parser
  + Async Ingestion Queue
  + Tenant Permission Filter
  + Query/Tool/Usage Logs
  + Admin API
```

这条路线能够最大化复用现有代码，同时补齐生产环境真正缺失的可靠性、可观测性、权限隔离和运维能力。
