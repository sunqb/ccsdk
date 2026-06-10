# RAG Kimi 文件解析集成规格说明

## 1. 背景

当前 RAG 文档解析链路支持两种 parser：

| Provider | 说明 | 解析方式 |
|----------|------|---------|
| `local` | 本地解析 .txt/.md/.pdf/.docx | 同步，`parse_bytes` 直接返回 |
| `mineru` | 调用公司 MinerU 服务解析 .pdf/.docx | 同步 HTTP，请求内等待返回 |

现需要接入 **Kimi（Moonshot）文件解析 API**，其特点是：

- **两步异步**：先上传文件 `POST /v1/files` 获得 `file_id`，再调 `GET /v1/files/{file_id}/content` 获取解析结果。
- **格式覆盖广**：支持 pdf/doc/docx/xls/xlsx/ppt/pptx/epub/html/json/csv/png/jpg 等数十种格式。
- **解析质量高**：对中文 PDF / 扫描件有较好的内容抽取能力。
- **有限流**：单用户 1000 文件上限，单文件 100MB，总量 10GB。

本规格说明覆盖：KimiDocumentParser 实现、配置项、错误处理与降级策略。

## 2. Kimi API 概要

### 2.1 上传文件

```
POST https://api.moonshot.cn/v1/files
Authorization: Bearer $KIMI_API_KEY
Content-Type: multipart/form-data

file=@example.pdf
purpose=file-extract
```

响应：

```json
{
  "id": "file-abc123",
  "object": "file",
  "bytes": 123456,
  "created_at": 1717459200,
  "filename": "example.pdf",
  "status": "ready",
  "status_details": ""
}
```

- `status` 可能值为 `ready`（解析完成）、`processing`（解析中）、`error`（解析失败）。
- 上传后 `status` 可能立即为 `ready`，也可能为 `processing`，需要轮询等待。

### 2.2 获取文件内容

```
GET https://api.moonshot.cn/v1/files/{file_id}/content
Authorization: Bearer $KIMI_API_KEY
```

响应：`text/plain`，直接返回提取的纯文本内容。

### 2.3 删除文件（可选）

```
DELETE https://api.moonshot.cn/v1/files/{file_id}
Authorization: Bearer $KIMI_API_KEY
```

## 3. 核心设计决策

### 3.1 保持同步接口

**不改动 `DocumentParser.parse_bytes` 的同步签名**。KimiDocumentParser 内部用同步 `httpx.Client` 调 Kimi API，与 MinerUDocumentParser 风格一致。

理由：
- 改动面最小，不影响 Protocol 签名、`_ingest_single_file` 调用方式、其他 parser 实现。
- 现有 `/rag/files` 的 `asyncMode` 参数已区分同步/异步入库，Kimi 轮询耗时只是"等待时间变长"，不影响架构。
- FastAPI 在 `async def` 路由中调用同步代码时，会自动放到线程池执行，不会阻塞事件循环。

### 3.2 轮询封装在 Parser 内部

`KimiDocumentParser.parse_bytes` 对外仍然是"给文件 → 拿结果"的语义，内部封装 upload → poll → retrieve → cleanup，调用方无感知。

轮询参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `poll_interval` | 2s | 首次轮询间隔 |
| `poll_max_interval` | 10s | 最大轮询间隔（指数退避上限） |
| `poll_timeout` | 300s | 总轮询超时 |
| `poll_backoff_factor` | 1.5 | 退避因子 |

### 3.3 同步模式 vs 异步模式

两种模式均保留，由 `/rag/files` 的 `asyncMode` 参数控制：

| 模式 | 参数 | 行为 | Kimi 场景 |
|------|------|------|----------|
| 同步 | `asyncMode=false`（默认） | 请求内等待，全部完成后返回 | 等待 2-30s 返回就绪结果 |
| 异步 | `asyncMode=true` | 立即返回 jobId，后台执行入库 | 立即返回，前端轮询 status |

### 3.4 任务状态追踪

复用已有 `e_rag_file` 表的 `metadata_json` 字段，不新建表。解析完成后写入：

```json
{
  "parserProvider": "kimi",
  "kimiFileId": "file-abc123",
  "kimiParsedAt": "2026-06-05T10:00:00Z"
}
```

### 3.5 Kimi 侧文件清理

解析成功获取内容后，立即调用 `DELETE /v1/files/{file_id}` 删除 Kimi 侧文件。删除失败只记 warning，不阻断入库。

## 4. KimiDocumentParser 实现

### 4.1 类结构

```python
class KimiDocumentParser:
    """Parse documents via Kimi (Moonshot) file-extract API.

    Flow: upload → poll status → retrieve content → cleanup.
    """

    supported_extensions = {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".ppt", ".pptx", ".txt", ".md", ".csv",
        ".epub", ".html", ".json", ".log",
        ".jpeg", ".jpg", ".png", ".gif", ".bmp", ".webp",
        ".svg", ".tiff", ".tif", ".ico", ".avif",
        ".mobi", ".dot", ".go", ".h", ".c", ".cpp",
        ".java", ".js", ".css", ".py", ".ts", ".tsx",
        ".yaml", ".yml", ".ini", ".conf", ".json",
    }

    def __init__(
        self,
        *,
        base_url: str = "https://api.moonshot.cn/v1",
        api_key: str,
        timeout_seconds: float = 120.0,
        poll_interval: float = 2.0,
        poll_max_interval: float = 10.0,
        poll_timeout: float = 300.0,
        poll_backoff_factor: float = 1.5,
        fallback_to_local: bool = False,
        cleanup_remote_file: bool = True,
    ) -> None: ...
```

### 4.2 核心流程

```python
def parse_bytes(
    self,
    content: bytes,
    *,
    filename: str,
    metadata: dict[str, Any] | None = None,
) -> ParsedDocument:
    # 1. 上传文件到 Kimi
    kimi_file_id = self._upload(content, filename)

    # 2. 轮询等待解析完成
    self._poll_until_ready(kimi_file_id)

    # 3. 获取解析内容
    text = self._retrieve_content(kimi_file_id)

    # 4. 清理 Kimi 侧文件
    if self.cleanup_remote_file:
        self._delete_remote_file(kimi_file_id)

    return ParsedDocument(
        filename=filename,
        mime_type=_guess_mime(filename),
        text=text,
        metadata={
            **(metadata or {}),
            "parser": "kimi",
            "kimiFileId": kimi_file_id,
        },
    )
```

### 4.3 上传实现

```python
def _upload(self, content: bytes, filename: str) -> str:
    with httpx.Client(timeout=self.timeout_seconds) as client:
        response = client.post(
            f"{self.base_url}/files",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": (filename, content, "application/octet-stream")},
            data={"purpose": "file-extract"},
        )
        response.raise_for_status()
        body = response.json()
        file_id = body["id"]
        status = body.get("status", "processing")

        if status == "error":
            raise ValueError(
                f"Kimi parsing failed immediately: {body.get('status_details', 'unknown')}"
            )
        return file_id
```

### 4.4 轮询实现

```python
def _poll_until_ready(self, file_id: str) -> None:
    interval = self.poll_interval
    deadline = time.monotonic() + self.poll_timeout

    while time.monotonic() < deadline:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.base_url}/files/{file_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            body = response.json()
            status = body.get("status", "processing")

        if status == "ready":
            return
        if status == "error":
            raise ValueError(
                f"Kimi parsing failed: {body.get('status_details', 'unknown')}"
            )

        time.sleep(interval)
        interval = min(interval * self.poll_backoff_factor, self.poll_max_interval)

    raise TimeoutError(f"Kimi parsing timed out after {self.poll_timeout}s for file {file_id}")
```

### 4.5 获取内容

```python
def _retrieve_content(self, file_id: str) -> str:
    with httpx.Client(timeout=60.0) as client:
        response = client.get(
            f"{self.base_url}/files/{file_id}/content",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        response.raise_for_status()
        return response.text
```

### 4.6 清理远程文件

```python
def _delete_remote_file(self, file_id: str) -> bool:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.delete(
                f"{self.base_url}/files/{file_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            return response.status_code < 400
    except Exception:
        return False
```

## 5. 集成方式

### 5.1 HybridDocumentParser 增加路由

当前 `HybridDocumentParser` 的路由逻辑：.txt/.md → local，.pdf/.docx → MinerU。增加 kimi 分支后：

```python
# _build_parser in ingestion.py
if provider == "kimi":
    kimi = KimiDocumentParser(
        api_key=settings.kimi_api_key,
        base_url=settings.kimi_base_url,
        poll_timeout=settings.kimi_poll_timeout,
        fallback_to_local=settings.kimi_fallback_to_local,
        cleanup_remote_file=settings.kimi_cleanup_remote_file,
    )
    return HybridDocumentParser(
        mineru_base_url=None,  # 不启用 MinerU
        mineru_api_key=None,
    )
    # HybridDocumentParser 内部会根据 self.mineru 是否为 None 决定路由
    # .txt/.md → local, 其他 → kimi
```

更简洁的方案：直接扩展 `HybridDocumentParser.__init__` 增加 `kimi` 参数，路由优先级：

```
.txt/.md → local（始终本地解析）
.pdf/.docx 等 → kimi（如已配置）→ mineru（如已配置）→ local fallback
```

### 5.2 _build_parser 增加 kimi 分支

```python
def _build_parser(self) -> DocumentParser:
    provider = settings.file_parser_provider
    if provider == "kimi":
        return HybridDocumentParser(
            kimi_base_url=settings.kimi_base_url,
            kimi_api_key=settings.kimi_api_key,
            kimi_timeout_seconds=settings.kimi_timeout_seconds,
            kimi_poll_timeout=settings.kimi_poll_timeout,
            kimi_fallback_to_local=settings.kimi_fallback_to_local,
            kimi_cleanup_remote_file=settings.kimi_cleanup_remote_file,
        )
    if provider == "mineru":
        return HybridDocumentParser(
            mineru_base_url=settings.mineru_base_url,
            # ...
        )
    if provider == "local":
        return LocalDocumentParser()
    raise ValueError(f"Unsupported FILE_PARSER_PROVIDER: {provider}")
```

## 6. 配置项

### 6.1 环境变量

```env
# Kimi 文件解析配置
KIMI_API_KEY=                         # Kimi API Key（必填）
KIMI_BASE_URL=https://api.moonshot.cn/v1  # API Base URL
KIMI_TIMEOUT_SECONDS=120              # 上传 HTTP 超时
KIMI_POLL_TIMEOUT=300                 # 轮询总超时（秒）
KIMI_POLL_INTERVAL=2                  # 首次轮询间隔（秒）
KIMI_POLL_MAX_INTERVAL=10             # 最大轮询间隔（秒）
KIMI_POLL_BACKOFF_FACTOR=1.5          # 轮询退避因子
KIMI_FALLBACK_TO_LOCAL=false          # 解析失败时是否回退到本地
KIMI_CLEANUP_REMOTE_FILE=true         # 解析后是否自动删除 Kimi 侧文件
```

### 6.2 使用方式

```env
FILE_PARSER_PROVIDER=kimi
KIMI_API_KEY=sk-xxx
```

## 7. 错误处理与降级

| 场景 | 处理方式 |
|------|---------|
| Kimi API Key 未配置 | `_build_parser` 抛出 ValueError，启动时即暴露 |
| 上传失败（网络错误） | 重试 1 次；仍失败则如果 `KIMI_FALLBACK_TO_LOCAL=true` 走本地解析，否则标记文件失败 |
| 上传成功但 status=error | 抛出 ValueError，走降级或标记文件失败 |
| 轮询超时 | 抛出 TimeoutError，走降级或标记文件失败 |
| 获取内容失败 | 重试 1 次；仍失败走降级或标记文件失败 |
| 删除远程文件失败 | 仅记 warning，不阻断 |
| 格式不支持 | 如果 `KIMI_FALLBACK_TO_LOCAL=true` 且本地支持则走本地，否则抛 ValueError |
| Kimi 限流（429） | 指数退避重试，最多 3 次；仍失败走降级 |
| 单文件超过 100MB | 上传前预检，直接拒绝 |

## 8. 改动范围汇总

| 文件 | 改动 |
|------|------|
| `app/services/rag/kimi_parser.py` | **新增**：KimiDocumentParser 实现 |
| `app/services/rag/parser.py` | HybridDocumentParser 增加 kimi 路由 |
| `app/services/rag/ingestion.py` | `_build_parser` 增加 `kimi` 分支 |
| `app/config.py` | 新增 Kimi 配置字段 |
| `app/services/rag/__init__.py` | 导出 KimiDocumentParser |
| `.env.example` | 新增 Kimi 配置模板 |
| `.env` | 新增 Kimi 配置（实际值） |

总计 7 个文件，其中 1 个新增。**不改动 DocumentParser Protocol 签名，不改动 _ingest_single_file 调用方式。**

## 9. 不在本次范围

- Parser 工厂模式重构（后续独立任务）。
- Kimi 侧残留文件定时清理任务。
- Kimi 解析费用统计（当前限时免费）。
- 前端 Parser Provider 切换 UI。
- `DocumentParser.parse_bytes` 改 async（后续与 MinerU 一起改）。
