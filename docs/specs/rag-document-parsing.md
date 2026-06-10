# RAG 文档上传解析设计

本文说明 `/rag/files` 上传文件后的解析逻辑。目标是把“文件解析”作为 RAG 入库链路中的独立阶段：生产环境优先使用公司部署的 MinerU 服务解析 PDF / DOCX 等复杂文档，开发环境保留本地纯文本解析能力。

## 1. 上传后的完整链路是什么？

```text
POST /rag/files
  ↓
RagIngestionService.ingest_files
  ↓
DocumentParser.parse_bytes
  ↓
ParsedDocument(text + metadata)
  ↓
TextChunker.chunk_document
  ↓
EmbeddingProvider.embed_documents
  ↓
VectorStore.upsert_chunks
  ↓
fileSet status = ready / partial_ready / failed
```

解析阶段只负责把原始文件转换成结构化文本和元数据，不负责切 chunk、embedding、检索或回答。

## 2. 为什么要引入 MinerU？

当前本地解析器对 `.txt` / `.md` 足够稳定，但 PDF / DOCX 的真实生产文档通常包含目录、页眉页脚、表格、扫描内容、多栏排版和图片说明。本地 `pypdf` / `python-docx` 只能作为开发 fallback，难以保证结构质量。

MinerU 更适合作为生产解析服务：

- 可以把复杂 PDF / DOCX 解析成更接近 Markdown 的结构化文本。
- 标题层级可以自然映射到 `headingPath` / `sectionTitle`。
- 表格、公式、图片说明等内容可以先归一成文本块，再进入统一 chunker。
- 解析能力由公司服务统一维护，应用容器无需绑定大量文档解析依赖。

## 3. 哪些格式走 MinerU，哪些格式走本地解析？

建议按格式和配置共同决定：

| 文件类型 | 默认解析方式 | 说明 |
| --- | --- | --- |
| `.txt` | local | 直接 UTF-8 解码 |
| `.md` | local | 保留 Markdown 标题结构 |
| `.pdf` | MinerU | 生产默认；local 仅作为开发 fallback |
| `.docx` | MinerU | 生产默认；local 仅作为开发 fallback |
| 其他格式 | 暂不支持 | 后续可扩展 `.pptx` / `.xlsx` |

建议配置：

```text
FILE_PARSER_PROVIDER=mineru
MINERU_BASE_URL=https://mineru.internal.example
MINERU_API_KEY=
MINERU_TIMEOUT_SECONDS=120
MINERU_FALLBACK_TO_LOCAL=false
```

`MINERU_FALLBACK_TO_LOCAL=false` 是生产推荐值：解析失败应暴露为单文件失败，避免悄悄退回低质量解析结果。

## 4. Parser 抽象应该如何设计？

建议把当前 `TextDocumentParser` 演进为可插拔 provider：

```python
class DocumentParser(Protocol):
    supported_extensions: set[str]

    def parse_bytes(
        self,
        content: bytes,
        *,
        filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        ...
```

推荐实现：

- `LocalDocumentParser`：负责 `.txt` / `.md`，并可保留本地 PDF / DOCX fallback。
- `MinerUDocumentParser`：负责调用 MinerU 服务，把返回的 Markdown / JSON 转成 `ParsedDocument`。
- `HybridDocumentParser`：根据扩展名和配置路由到 local 或 MinerU。

`RagIngestionService` 只依赖 `DocumentParser` 抽象，不关心底层解析来源。

## 5. MinerU 返回结果如何映射到 `ParsedDocument`？

理想输入是 MinerU 返回 Markdown 文本；如果返回 JSON 结构，也应先归一成 Markdown-like 文本。

```python
ParsedDocument(
    filename="contract.pdf",
    mime_type="application/pdf",
    text="# 第一章 总则\n\n合同有效期为三年。\n\n## 付款条款\n\n...",
    metadata={
        "extension": ".pdf",
        "parser": "mineru",
        "parserVersion": "...",
        "pageCount": 12,
        "documentId": "...",
    },
)
```

关键要求：

- `text` 必须是后续 chunker 可直接处理的纯文本或 Markdown。
- 标题尽量使用 `#` / `##` / `###` 表达层级，方便生成 `headingPath`。
- 页码、来源、图片 OCR 信息等放在 `metadata`，不要混入系统提示词。

## 6. 如何服务 Parent-Child Chunk？

当前 `TextChunker` 会从 Markdown 标题推导：

- `headingPath`
- `sectionTitle`
- `parentChunkId`
- `parentChunkText`
- `chunkRole=child`

因此 MinerU 的核心价值不是直接生成 chunk，而是提供更高质量的结构化文本。只要 MinerU 输出稳定的标题层级，现有 chunker 就能继续生成 parent-child metadata。

示例：

```markdown
# 退款政策

用户在购买后 30 天内可以申请退款。

## 例外情况

虚拟商品一经使用不可退款。
```

期望 chunk metadata：

```json
{
  "parser": "mineru",
  "headingPath": ["退款政策", "例外情况"],
  "sectionTitle": "例外情况",
  "parentChunkId": "chunk_xxx",
  "chunkRole": "child"
}
```

## 7. 解析失败如何处理？

解析失败应保持现有 fileSet 状态语义：

- 单文件失败，其他文件成功：`partial_ready`
- 全部文件失败：`failed`
- 全部文件成功：`ready`

失败原因应写入文件级状态，便于前端展示和运维排查：

```json
{
  "filename": "contract.pdf",
  "status": "failed",
  "errorCode": "parse_failed",
  "errorMessage": "MinerU request timed out after 120s"
}
```

生产环境不建议静默 fallback。若开启 fallback，也必须在 metadata 中标记：

```json
{
  "parser": "local",
  "parserFallbackFrom": "mineru"
}
```

## 8. 超时、并发和重试策略是什么？

建议策略：

- 单文件 MinerU 解析超时：默认 120 秒，可通过 `MINERU_TIMEOUT_SECONDS` 配置。
- 上传接口仍受 `RAG_MAX_CONCURRENT_INGESTIONS` 控制。
- MinerU 失败只重试网络类错误，最多 1 次；业务类解析失败不重试。
- 大文件解析可后续切到异步任务队列；当前保持进程内任务模型。

## 9. 安全边界是什么？

- 文档内容是不可信输入，只能作为 RAG 证据，不得作为系统指令执行。
- Parser 不返回 API Key、内部路径、服务端异常栈等敏感信息。
- MinerU 返回的 Markdown 只进入 chunk / embedding / retrieval，不拼接到系统 prompt。
- `metadata` 中的路径、租户、用户信息必须遵守现有 source scope 和权限过滤。

## 10. 如何测试？

单元测试：

- `.txt` / `.md` 继续覆盖 local parser。
- MinerU parser 使用 mock HTTP 响应，验证 PDF / DOCX 转成 `ParsedDocument`。
- 验证 MinerU Markdown 标题能生成 `headingPath`、`parentChunkId`。
- 验证 MinerU 超时 / 失败会让单文件进入 `parse_failed`。

集成测试：

1. 上传真实 PDF / DOCX。
2. 轮询 `/rag/files/{fileSetId}/status` 到 `ready`。
3. 调 `/rag/query` 确认 `usage.retrieval.matchedChunks > 0`。
4. 检查 `citations[].metadata.parser == "mineru"`。
5. 检查 `citations[].metadata.headingPath` / `parentChunkId`。
6. 调 `/agent-sdk/rag/stream` 做端到端问答。

## 11. 分阶段落地建议

第一阶段：只新增 parser provider 抽象和 MinerU mock 测试，不改 chunk / retrieval。

第二阶段：接入真实 MinerU HTTP API，支持 `.pdf` / `.docx` 生产解析。

第三阶段：补充解析质量观测指标，例如解析耗时、页数、表格数量、OCR 使用情况、解析失败率。

第四阶段：根据 MinerU 的 JSON 结构进一步优化 chunker，例如按页码、标题、表格块生成更稳定的 parent-child 结构。
