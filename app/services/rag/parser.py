"""Document parser for RAG ingestion."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(slots=True)
class ParsedDocument:
    """Parsed text document with lightweight metadata."""

    filename: str
    mime_type: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class TextDocumentParser:
    """Parse supported documents into plain text for RAG indexing."""

    supported_extensions = SUPPORTED_TEXT_EXTENSIONS

    def parse_path(
        self,
        path: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        """Parse a supported document from disk."""
        file_path = Path(path)
        self._ensure_supported(file_path.name)
        content = file_path.read_bytes()
        parsed_metadata = {
            "path": str(file_path),
            "size": len(content),
            **(metadata or {}),
        }
        return self.parse_bytes(content, filename=file_path.name, metadata=parsed_metadata)

    def parse_bytes(
        self,
        content: bytes,
        *,
        filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        """Parse a supported document from bytes."""
        self._ensure_supported(filename)
        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            text = self._parse_pdf(content)
        elif suffix == ".docx":
            text = self._parse_docx(content)
        else:
            text = self._decode_text(content)
        return ParsedDocument(
            filename=filename,
            mime_type=MIME_TYPES.get(suffix, "text/plain"),
            text=self._normalize_newlines(text),
            metadata={"extension": suffix, **(metadata or {})},
        )

    def _ensure_supported(self, filename: str) -> None:
        suffix = Path(filename).suffix.lower()
        if suffix not in self.supported_extensions:
            supported = ", ".join(sorted(self.supported_extensions))
            raise ValueError(f"Unsupported RAG document type: {suffix}. Supported: {supported}")

    @staticmethod
    def _decode_text(content: bytes) -> str:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return content.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_pdf(content: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF parsing requires optional dependency 'pypdf'") from exc

        try:
            reader = PdfReader(BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:  # noqa: BLE001 - normalize parser-specific failures
            raise ValueError(f"Unable to parse PDF document: {exc}") from exc

        text = "\n\n".join(page.strip() for page in pages if page.strip())
        if not text:
            raise ValueError("No text content found in PDF document")
        return text

    @staticmethod
    def _parse_docx(content: bytes) -> str:
        try:
            from docx import Document
        except ImportError as exc:
            raise ValueError("DOCX parsing requires optional dependency 'python-docx'") from exc

        try:
            document = Document(BytesIO(content))
        except Exception as exc:  # noqa: BLE001 - normalize parser-specific failures
            raise ValueError(f"Unable to parse DOCX document: {exc}") from exc

        blocks = [paragraph.text.strip() for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    blocks.append(" | ".join(cells))

        text = "\n\n".join(block for block in blocks if block)
        if not text:
            raise ValueError("No text content found in DOCX document")
        return text

    @staticmethod
    def _normalize_newlines(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n")
