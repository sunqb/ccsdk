"""Kimi (Moonshot) file-extract document parser for RAG ingestion.

Flow: upload file → poll status → retrieve content → cleanup remote file.

API docs:
- Upload: POST /v1/files (purpose=file-extract)
- Content: GET /v1/files/{file_id}/content
- Delete:  DELETE /v1/files/{file_id}
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from .parser import (
    MIME_TYPES,
    SUPPORTED_TEXT_EXTENSIONS,
    LocalDocumentParser,
    ParsedDocument,
)

log = logging.getLogger(__name__)

_NETWORK_RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.NetworkError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)

SUPPORTED_KIMI_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".txt", ".md", ".csv",
    ".epub", ".html", ".htm", ".json", ".log",
    ".jpeg", ".jpg", ".png", ".gif", ".bmp", ".webp",
    ".svg", ".svgz", ".tiff", ".tif", ".ico",
    ".xbm", ".dib", ".pjp", ".pjpeg", ".avif",
    ".apng", ".dot", ".mobi",
    ".go", ".h", ".c", ".cpp", ".cxx", ".cc",
    ".cs", ".java", ".js", ".css", ".jsp", ".php",
    ".py", ".py3", ".asp", ".yaml", ".yml",
    ".ini", ".conf", ".ts", ".tsx",
}

KIMI_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


class KimiDocumentParser:
    """Parse documents via Kimi (Moonshot) file-extract API.

    Flow: upload → poll status → retrieve content → cleanup.
    Uses synchronous httpx.Client, consistent with MinerUDocumentParser.
    """

    supported_extensions = SUPPORTED_KIMI_EXTENSIONS

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
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("KIMI_API_KEY is required for KimiDocumentParser")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.poll_max_interval = poll_max_interval
        self.poll_timeout = poll_timeout
        self.poll_backoff_factor = poll_backoff_factor
        self.fallback_to_local = fallback_to_local
        self.cleanup_remote_file = cleanup_remote_file
        self._client = client
        self._local_fallback = LocalDocumentParser() if fallback_to_local else None

    def parse_bytes(
        self,
        content: bytes,
        *,
        filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        suffix = Path(filename).suffix.lower()
        self._ensure_supported(suffix)
        self._check_size(content, filename)

        try:
            return self._parse_via_kimi(content, filename=filename, metadata=metadata)
        except Exception as exc:
            if self._local_fallback and suffix in LocalDocumentParser.supported_extensions:
                log.warning(
                    "Kimi parsing failed for %s, falling back to local parser: %s",
                    filename,
                    exc,
                )
                return self._local_fallback.parse_bytes(content, filename=filename, metadata=metadata)
            raise

    def _parse_via_kimi(
        self,
        content: bytes,
        *,
        filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        kimi_file_id = self._upload(content, filename)

        try:
            self._poll_until_ready(kimi_file_id)
            text = self._retrieve_content(kimi_file_id)
        except Exception:
            self._try_cleanup(kimi_file_id)
            raise

        if self.cleanup_remote_file:
            self._try_cleanup(kimi_file_id)

        return ParsedDocument(
            filename=filename,
            mime_type=MIME_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream"),
            text=text,
            metadata={
                **(metadata or {}),
                "parser": "kimi",
                "kimiFileId": kimi_file_id,
            },
        )

    def _upload(self, content: bytes, filename: str) -> str:
        mime_type = MIME_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = self._post_upload(
                    files={"file": (filename, content, mime_type)},
                    data={"purpose": "file-extract"},
                )
                break
            except _NETWORK_RETRY_EXCEPTIONS as exc:
                last_exc = exc
                if attempt == 0:
                    log.warning("Retrying Kimi upload for %s after network error: %s", filename, exc)
                    continue
                raise ValueError(f"Kimi upload network error for {filename}") from exc
        else:
            raise ValueError(f"Kimi upload network error for {filename}") from last_exc

        if resp.status_code == 429:
            raise ValueError(f"Kimi rate limited during upload for {filename}")
        resp.raise_for_status()

        body = resp.json()
        file_id = body.get("id")
        if not file_id:
            raise ValueError(f"Kimi upload response missing file id: {body}")

        status = body.get("status", "processing")
        if status == "error":
            raise ValueError(
                f"Kimi parsing failed immediately for {filename}: "
                f"{body.get('status_details', 'unknown')}"
            )

        log.info("Kimi uploaded %s → file_id=%s status=%s", filename, file_id, status)
        return file_id

    def _post_upload(
        self,
        *,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str],
    ) -> httpx.Response:
        if self._client is not None:
            return self._client.post(
                f"{self.base_url}/files",
                headers=self._auth_header(),
                files=files,
                data=data,
            )
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.post(
                f"{self.base_url}/files",
                headers=self._auth_header(),
                files=files,
                data=data,
            )

    def _poll_until_ready(self, file_id: str) -> None:
        interval = self.poll_interval
        deadline = time.monotonic() + self.poll_timeout
        attempts = 0
        max_attempts = 3  # for 429 retry

        while time.monotonic() < deadline:
            try:
                resp = self._get_file_status(file_id)
            except _NETWORK_RETRY_EXCEPTIONS as exc:
                log.warning(
                    "Kimi polling network error file_id=%s: %s; retry in %.1fs",
                    file_id,
                    exc,
                    interval,
                )
                time.sleep(interval)
                interval = min(interval * self.poll_backoff_factor, self.poll_max_interval)
                continue
            if 500 <= resp.status_code < 600:
                log.warning(
                    "Kimi polling transient server error file_id=%s: HTTP %s; retry in %.1fs",
                    file_id,
                    resp.status_code,
                    interval,
                )
                time.sleep(interval)
                interval = min(interval * self.poll_backoff_factor, self.poll_max_interval)
                continue
            if resp.status_code == 429 and attempts < max_attempts:
                attempts += 1
                wait = min(interval * 2, 30.0)
                log.warning("Kimi rate limited polling file_id=%s, retry %d/%d in %.1fs", file_id, attempts, max_attempts, wait)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            body = resp.json()
            status = body.get("status", "processing")
            attempts = 0  # reset on successful response

            # Moonshot file-extract reports a completed file as "ok".
            # Keep "ready" for compatibility with earlier assumptions/tests.
            if status in {"ready", "ok"}:
                log.info("Kimi file_id=%s is ready, status=%s", file_id, status)
                return
            if status == "error":
                raise ValueError(
                    f"Kimi parsing failed for file_id={file_id}: "
                    f"{body.get('status_details', 'unknown')}"
                )

            time.sleep(interval)
            interval = min(interval * self.poll_backoff_factor, self.poll_max_interval)

        raise TimeoutError(
            f"Kimi parsing timed out after {self.poll_timeout}s for file_id={file_id}"
        )

    def _get_file_status(self, file_id: str) -> httpx.Response:
        if self._client is not None:
            return self._client.get(
                f"{self.base_url}/files/{file_id}",
                headers=self._auth_header(),
            )
        with httpx.Client(timeout=30.0) as client:
            return client.get(
                f"{self.base_url}/files/{file_id}",
                headers=self._auth_header(),
            )

    def _retrieve_content(self, file_id: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = self._get_content(file_id)
                if 500 <= resp.status_code < 600 and attempt == 0:
                    log.warning(
                        "Retrying Kimi content retrieval for file_id=%s after HTTP %s",
                        file_id,
                        resp.status_code,
                    )
                    continue
                break
            except _NETWORK_RETRY_EXCEPTIONS as exc:
                last_exc = exc
                if attempt == 0:
                    log.warning("Retrying Kimi content retrieval for file_id=%s: %s", file_id, exc)
                    continue
                raise ValueError(f"Kimi content retrieval failed for file_id={file_id}") from exc
        else:
            raise ValueError(f"Kimi content retrieval failed for file_id={file_id}") from last_exc

        if 500 <= resp.status_code < 600:
            raise ValueError(f"Kimi content retrieval server error for file_id={file_id}: HTTP {resp.status_code}")
        resp.raise_for_status()
        text = resp.text
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            body = resp.json()
            if isinstance(body, dict) and isinstance(body.get("content"), str):
                text = body["content"]
        if not text or not text.strip():
            raise ValueError(f"Kimi returned empty content for file_id={file_id}")

        log.info("Kimi retrieved content for file_id=%s, length=%d", file_id, len(text))
        return text

    def _get_content(self, file_id: str) -> httpx.Response:
        if self._client is not None:
            return self._client.get(
                f"{self.base_url}/files/{file_id}/content",
                headers=self._auth_header(),
            )
        with httpx.Client(timeout=60.0) as client:
            return client.get(
                f"{self.base_url}/files/{file_id}/content",
                headers=self._auth_header(),
            )

    def _try_cleanup(self, file_id: str) -> bool:
        try:
            if self._client is not None:
                resp = self._client.delete(
                    f"{self.base_url}/files/{file_id}",
                    headers=self._auth_header(),
                )
            else:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.delete(
                        f"{self.base_url}/files/{file_id}",
                        headers=self._auth_header(),
                    )
            if resp.status_code < 400:
                log.info("Kimi cleaned up remote file_id=%s", file_id)
            else:
                log.warning("Kimi cleanup failed for file_id=%s: HTTP %s", file_id, resp.status_code)
            return resp.status_code < 400
        except Exception:
            log.warning("Kimi cleanup error for file_id=%s", file_id, exc_info=True)
            return False

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _ensure_supported(self, suffix: str) -> None:
        if suffix not in self.supported_extensions:
            supported = ", ".join(sorted(self.supported_extensions))
            raise ValueError(f"Unsupported Kimi document type: {suffix}. Supported: {supported}")

    @staticmethod
    def _check_size(content: bytes, filename: str) -> None:
        if len(content) > KIMI_MAX_FILE_SIZE:
            raise ValueError(
                f"File {filename} is {len(content)} bytes, "
                f"exceeds Kimi limit of {KIMI_MAX_FILE_SIZE} bytes (100MB)"
            )
