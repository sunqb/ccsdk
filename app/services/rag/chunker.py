"""Minimal Markdown-aware text chunker for RAG MVP."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .parser import ParsedDocument

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(slots=True)
class RagChunk:
    """A text chunk ready for indexing."""

    chunk_id: str
    chunk_index: int
    text: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    source_file_id: str | None = None


class TextChunker:
    """Split parsed text into paragraph-preserving chunks."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 120):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be greater than or equal to 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(
        self,
        document: ParsedDocument,
        *,
        source_file_id: str | None = None,
    ) -> list[RagChunk]:
        """Split a parsed document into chunks."""
        blocks = self._split_blocks(document.text)
        chunks: list[RagChunk] = []
        current_blocks: list[str] = []
        current_size = 0
        current_heading_path: list[str] = []
        carried_overlap = False

        for block in blocks:
            block_size = len(block)
            heading_path = self._heading_path_for_block(block, current_heading_path)

            if current_blocks and current_size + block_size + 2 > self.chunk_size:
                parent_text = "\n\n".join(current_blocks)
                chunks.append(
                    self._build_chunk(
                        document=document,
                        text=parent_text,
                        chunk_index=len(chunks),
                        source_file_id=source_file_id,
                        heading_path=current_heading_path,
                        parent_text=parent_text,
                    )
                )
                current_blocks = self._overlap_blocks(current_blocks)
                current_size = len("\n\n".join(current_blocks))
                carried_overlap = bool(current_blocks)

            if block_size > self.chunk_size:
                if carried_overlap:
                    current_blocks = []
                    current_size = 0
                    carried_overlap = False
                elif current_blocks:
                    parent_text = "\n\n".join(current_blocks)
                    chunks.append(
                        self._build_chunk(
                            document=document,
                            text=parent_text,
                            chunk_index=len(chunks),
                            source_file_id=source_file_id,
                            heading_path=current_heading_path,
                            parent_text=parent_text,
                        )
                    )
                    current_blocks = []
                    current_size = 0

                for part in self._split_long_block(block):
                    chunks.append(
                        self._build_chunk(
                            document=document,
                            text=part,
                            chunk_index=len(chunks),
                            source_file_id=source_file_id,
                            heading_path=heading_path,
                            parent_text=block,
                        )
                    )
                current_heading_path = heading_path
                continue

            current_blocks.append(block)
            current_size = len("\n\n".join(current_blocks))
            current_heading_path = heading_path
            carried_overlap = False

        if current_blocks:
            parent_text = "\n\n".join(current_blocks)
            chunks.append(
                self._build_chunk(
                    document=document,
                    text=parent_text,
                    chunk_index=len(chunks),
                    source_file_id=source_file_id,
                    heading_path=current_heading_path,
                    parent_text=parent_text,
                )
            )

        return chunks

    @staticmethod
    def estimate_token_count(text: str) -> int:
        """Estimate token count without a tokenizer."""
        ascii_words = re.findall(r"[A-Za-z0-9_]+", text)
        non_ascii_chars = sum(1 for char in text if ord(char) > 127 and not char.isspace())
        punctuation = len(re.findall(r"[^\w\s]", text, flags=re.UNICODE))
        return max(1, len(ascii_words) + non_ascii_chars + punctuation // 2)

    @staticmethod
    def _split_blocks(text: str) -> list[str]:
        blocks: list[str] = []
        current: list[str] = []

        for line in text.split("\n"):
            stripped = line.rstrip()
            if not stripped:
                if current:
                    blocks.append("\n".join(current).strip())
                    current = []
                continue

            if HEADING_RE.match(stripped) and current:
                blocks.append("\n".join(current).strip())
                current = []

            current.append(stripped)

        if current:
            blocks.append("\n".join(current).strip())

        return [block for block in blocks if block]

    def _split_long_block(self, block: str) -> list[str]:
        parts: list[str] = []
        start = 0
        while start < len(block):
            end = min(start + self.chunk_size, len(block))
            parts.append(block[start:end].strip())
            if end >= len(block):
                break
            start = max(end - self.chunk_overlap, start + 1)
        return [part for part in parts if part]

    def _overlap_blocks(self, blocks: list[str]) -> list[str]:
        if self.chunk_overlap == 0:
            return []

        overlap: list[str] = []
        size = 0
        for block in reversed(blocks):
            block_size = len(block)
            if overlap and size + block_size + 2 > self.chunk_overlap:
                break
            overlap.insert(0, block)
            size = len("\n\n".join(overlap))
            if size >= self.chunk_overlap:
                break
        return overlap

    @staticmethod
    def _heading_path_for_block(block: str, previous: list[str]) -> list[str]:
        first_line = block.split("\n", 1)[0]
        match = HEADING_RE.match(first_line)
        if not match:
            return previous

        level = len(match.group(1))
        title = match.group(2).strip()
        return [*previous[: level - 1], title]

    def _build_chunk(
        self,
        *,
        document: ParsedDocument,
        text: str,
        chunk_index: int,
        source_file_id: str | None,
        heading_path: list[str],
        parent_text: str,
    ) -> RagChunk:
        clean_text = text.strip()
        clean_parent_text = parent_text.strip()
        start_offset = document.text.find(clean_text)
        if start_offset < 0:
            start_offset = None
        end_offset = start_offset + len(clean_text) if start_offset is not None else None
        document_id = str(
            document.metadata.get("documentId")
            or document.metadata.get("document_id")
            or document.metadata.get("fileId")
            or document.filename
        )
        parent_chunk_id = self._make_chunk_id(
            f"{document_id}:parent",
            len(heading_path),
            clean_parent_text or clean_text,
        )
        metadata = {
            **document.metadata,
            "documentId": document_id,
            "filename": document.filename,
            "mime_type": document.mime_type,
            "heading_path": heading_path,
            "headingPath": heading_path,
            "sectionTitle": heading_path[-1] if heading_path else None,
            "parentChunkId": parent_chunk_id,
            "parent_chunk_id": parent_chunk_id,
            "parentChunkText": clean_parent_text,
            "chunkRole": "child",
            "startOffset": start_offset,
            "endOffset": end_offset,
            "contentType": self._content_type(clean_text),
        }
        chunk_id = self._make_chunk_id(document.filename, chunk_index, clean_text)
        return RagChunk(
            chunk_id=chunk_id,
            source_file_id=source_file_id,
            chunk_index=chunk_index,
            text=clean_text,
            token_count=self.estimate_token_count(clean_text),
            metadata=metadata,
        )

    @staticmethod
    def _make_chunk_id(filename: str, chunk_index: int, text: str) -> str:
        digest = hashlib.sha1(f"{filename}:{chunk_index}:{text}".encode()).hexdigest()
        return f"chunk_{digest[:16]}"

    @staticmethod
    def _content_type(text: str) -> str:
        stripped = text.strip()
        if HEADING_RE.match(stripped.split("\n", 1)[0] if stripped else ""):
            return "section"
        if "|" in stripped and "\n" in stripped:
            return "table"
        if "```" in stripped:
            return "code"
        return "text"
