"""Unit tests for RAG document parsers."""
from __future__ import annotations

import pytest

import httpx


class TestLocalDocumentParser:
    """Tests for LocalDocumentParser (.txt / .md)."""

    def test_parse_md_document(self) -> None:
        """LocalDocumentParser correctly parses Markdown files."""
        from app.services.rag.parser import LocalDocumentParser

        parser = LocalDocumentParser()
        content = b"\xef\xbb\xbf# Title\n\nBody paragraph"
        doc = parser.parse_bytes(content, filename="doc.md")

        assert doc.mime_type == "text/markdown"
        assert doc.text.startswith("# Title")
        assert "Body paragraph" in doc.text
        assert doc.metadata["extension"] == ".md"
        assert doc.metadata["parser"] == "local"

    def test_parse_txt_document(self) -> None:
        """LocalDocumentParser correctly parses plain text files."""
        from app.services.rag.parser import LocalDocumentParser

        parser = LocalDocumentParser()
        content = "中文内容\n第二行".encode("utf-8")
        doc = parser.parse_bytes(content, filename="note.txt")

        assert doc.mime_type == "text/plain"
        assert doc.text == "中文内容\n第二行"
        assert doc.metadata["extension"] == ".txt"
        assert doc.metadata["parser"] == "local"

    def test_parse_txt_with_bom(self) -> None:
        """UTF-8 BOM is stripped from text content."""
        from app.services.rag.parser import LocalDocumentParser

        parser = LocalDocumentParser()
        content = b"\xef\xbb\xbfHello"
        doc = parser.parse_bytes(content, filename="bom.txt")

        assert doc.text == "Hello"

    def test_parse_rejects_unsupported_extension(self) -> None:
        """Unsupported file types raise ValueError."""
        from app.services.rag.parser import LocalDocumentParser

        parser = LocalDocumentParser()
        with pytest.raises(ValueError, match="Unsupported local document type"):
            parser.parse_bytes(b"data", filename="file.xlsx")

    def test_parse_preserves_newlines(self) -> None:
        """CRLF and CR are normalized to LF."""
        from app.services.rag.parser import LocalDocumentParser

        parser = LocalDocumentParser()
        content = b"Line1\r\nLine2\rLine3\n"
        doc = parser.parse_bytes(content, filename="test.txt")

        assert "\r" not in doc.text
        assert doc.text == "Line1\nLine2\nLine3\n"

    def test_parse_with_extra_metadata(self) -> None:
        """Extra metadata is merged into parsed document metadata."""
        from app.services.rag.parser import LocalDocumentParser

        parser = LocalDocumentParser()
        doc = parser.parse_bytes(
            b"Content",
            filename="doc.md",
            metadata={"tenant_id": "t1", "custom": "value"},
        )

        assert doc.metadata["tenant_id"] == "t1"
        assert doc.metadata["custom"] == "value"
        assert doc.metadata["parser"] == "local"


class TestMinerUDocumentParser:
    """Tests for MinerUDocumentParser (HTTP API client)."""

    def _make_parser(self, base_url: str = "https://mineru.example", **kwargs) -> tuple:
        """Create a MinerUDocumentParser with mocked transport."""
        from app.services.rag.parser import MinerUDocumentParser

        return MinerUDocumentParser(base_url=base_url, **kwargs)

    def _sync_parse(self, parser, content: bytes, filename: str, **kwargs):
        """Helper to call parse_bytes synchronously."""
        return parser.parse_bytes(content, filename=filename, **kwargs)

    def test_parse_pdf_via_mineru(self) -> None:
        """MinerU parser sends PDF to API and returns structured Markdown."""
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/parse")
            return httpx.Response(
                200,
                json={
                    "markdown": "# 退款政策\n\n用户在购买后30天内可以申请退款。\n\n## 例外情况\n\n虚拟商品一经使用不可退款。",
                    "page_count": 3,
                    "document_id": "doc_abc123",
                    "version": "2.1.0",
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = self._make_parser(
            base_url="https://mineru.example",
            api_key="test-key",
            timeout_seconds=60,
            client=client,
        )
        pdf_bytes = b"%PDF-1.4 fake pdf content"
        doc = self._sync_parse(parser, pdf_bytes, filename="contract.pdf")

        assert doc.mime_type == "application/pdf"
        assert "# 退款政策" in doc.text
        assert "例外情况" in doc.text
        assert doc.metadata["parser"] == "mineru"
        assert doc.metadata["pageCount"] == 3
        assert doc.metadata["documentId"] == "doc_abc123"
        assert doc.metadata["parserVersion"] == "2.1.0"

    def test_parse_docx_via_mineru(self) -> None:
        """MinerU parser correctly routes .docx files."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"markdown": "# DOCX Content", "page_count": 1},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = self._make_parser(base_url="https://mineru.example", client=client)
        docx_bytes = b"PK\x03\x04 fake docx content"
        doc = self._sync_parse(parser, docx_bytes, filename="policy.docx")

        assert doc.mime_type == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert doc.metadata["parser"] == "mineru"

    def test_parse_rejects_unsupported_extension(self) -> None:
        """Unsupported file types raise ValueError before making API calls."""
        parser = self._make_parser()
        with pytest.raises(ValueError, match="Unsupported MinerU document type"):
            parser.parse_bytes(b"data", filename="file.txt")

    def test_parse_rejects_empty_response(self) -> None:
        """Empty Markdown response raises ValueError."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"markdown": "", "page_count": 0})

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = self._make_parser(base_url="https://mineru.example", client=client)

        with pytest.raises(ValueError, match="empty content"):
            self._sync_parse(parser, b"fake", filename="doc.pdf")

    def test_parse_raises_on_http_error(self) -> None:
        """HTTP errors are converted to ValueError."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "Internal server error"})

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = self._make_parser(base_url="https://mineru.example", client=client)

        with pytest.raises(ValueError, match="HTTP 500"):
            self._sync_parse(parser, b"fake", filename="doc.pdf")

    def test_parse_raises_on_network_error_when_no_fallback(self) -> None:
        """Network errors propagate as ValueError when fallback is disabled."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = self._make_parser(
            base_url="https://mineru.example",
            fallback_to_local=False,
            client=client,
        )

        with pytest.raises(ValueError, match="parsing failed"):
            self._sync_parse(parser, b"fake", filename="doc.pdf")

    def test_parse_falls_back_to_local_on_network_error(self) -> None:
        """When fallback is enabled, network errors trigger local fallback parsing."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = self._make_parser(
            base_url="https://mineru.example",
            fallback_to_local=True,
            client=client,
        )
        parser._parse_pdf_local = lambda content: "Fallback PDF text"

        doc = self._sync_parse(parser, b"%PDF-fake", filename="fallback.pdf")

        assert doc.text == "Fallback PDF text"
        assert doc.metadata["parser"] == "local"
        assert doc.metadata["parserFallbackFrom"] == "mineru"

    def test_parse_merges_extra_metadata(self) -> None:
        """Extra metadata passed to parse_bytes is preserved in output."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"markdown": "# Test", "page_count": 1},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = self._make_parser(base_url="https://mineru.example", client=client)
        doc = self._sync_parse(
            parser,
            b"fake",
            filename="doc.pdf",
            metadata={"tenant_id": "t_123", "conversation_id": "c_abc"},
        )

        assert doc.metadata["tenant_id"] == "t_123"
        assert doc.metadata["conversation_id"] == "c_abc"
        assert doc.metadata["parser"] == "mineru"


class TestHybridDocumentParser:
    """Tests for HybridDocumentParser (routing between Local and MinerU)."""

    def test_routes_txt_to_local(self) -> None:
        """HybridDocumentParser routes .txt files to LocalDocumentParser."""
        from app.services.rag.parser import HybridDocumentParser

        parser = HybridDocumentParser(mineru_base_url="https://mineru.example")
        doc = parser.parse_bytes(b"Plain text content", filename="readme.txt")

        assert doc.mime_type == "text/plain"
        assert doc.metadata["parser"] == "local"

    def test_routes_md_to_local(self) -> None:
        """HybridDocumentParser routes .md files to LocalDocumentParser."""
        from app.services.rag.parser import HybridDocumentParser

        parser = HybridDocumentParser(mineru_base_url="https://mineru.example")
        doc = parser.parse_bytes(b"# Markdown Title", filename="doc.md")

        assert doc.mime_type == "text/markdown"
        assert doc.metadata["parser"] == "local"

    def test_routes_pdf_to_mineru(self) -> None:
        """HybridDocumentParser routes .pdf to MinerUDocumentParser when configured."""
        from app.services.rag.parser import HybridDocumentParser

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"markdown": "# PDF Content", "page_count": 1},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = HybridDocumentParser(
            mineru_base_url="https://mineru.example",
            mineru_api_key="secret",
        )
        parser.mineru._client = client

        doc = parser.parse_bytes(b"%PDF-fake", filename="document.pdf")

        assert doc.metadata["parser"] == "mineru"

    def test_raises_when_mineru_required_but_not_configured(self) -> None:
        """When MinerU is required but not configured, HybridDocumentParser raises."""
        from app.services.rag.parser import HybridDocumentParser

        parser = HybridDocumentParser()  # No MinerU configured
        with pytest.raises(ValueError, match="MinerU is not configured"):
            parser.parse_bytes(b"fake", filename="doc.pdf")

    def test_supported_extensions_combines_both(self) -> None:
        """HybridDocumentParser.supported_extensions includes both Local and MinerU types."""
        from app.services.rag.parser import HybridDocumentParser

        parser = HybridDocumentParser(mineru_base_url="https://mineru.example")
        exts = parser.supported_extensions

        assert ".txt" in exts
        assert ".md" in exts
        assert ".pdf" in exts
        assert ".docx" in exts

    def test_supported_extensions_local_only(self) -> None:
        """When MinerU is not configured, only local extensions are supported."""
        from app.services.rag.parser import HybridDocumentParser

        parser = HybridDocumentParser()
        exts = parser.supported_extensions

        assert ".txt" in exts
        assert ".md" in exts
        assert ".pdf" not in exts
        assert ".docx" not in exts

    def test_rejects_unsupported_format(self) -> None:
        """Unsupported file formats raise ValueError."""
        from app.services.rag.parser import HybridDocumentParser

        parser = HybridDocumentParser(mineru_base_url="https://mineru.example")
        with pytest.raises(ValueError, match="Unsupported document type"):
            parser.parse_bytes(b"data", filename="spreadsheet.xlsx")

    def test_mineru_fallback_setting_passed_through(self) -> None:
        """MinerU fallback setting is propagated to MinerUDocumentParser."""
        from app.services.rag.parser import HybridDocumentParser

        parser = HybridDocumentParser(
            mineru_base_url="https://mineru.example",
            mineru_fallback_to_local=True,
        )
        assert parser.mineru is not None
        assert parser.mineru.fallback_to_local is True

        parser_no_fallback = HybridDocumentParser(
            mineru_base_url="https://mineru.example",
            mineru_fallback_to_local=False,
        )
        assert parser_no_fallback.mineru.fallback_to_local is False


class TestDocumentParserProtocol:
    """Tests verifying that parser classes satisfy the DocumentParser protocol."""

    def test_local_parser_satisfies_protocol(self) -> None:
        """LocalDocumentParser is a valid DocumentParser."""
        from app.services.rag.parser import DocumentParser, LocalDocumentParser

        parser: DocumentParser = LocalDocumentParser()
        assert hasattr(parser, "supported_extensions")
        assert hasattr(parser, "parse_bytes")
        assert callable(parser.parse_bytes)

    def test_mineru_parser_satisfies_protocol(self) -> None:
        """MinerUDocumentParser is a valid DocumentParser."""
        from app.services.rag.parser import DocumentParser, MinerUDocumentParser

        parser: DocumentParser = MinerUDocumentParser(base_url="https://mineru.example")
        assert hasattr(parser, "supported_extensions")
        assert hasattr(parser, "parse_bytes")
        assert callable(parser.parse_bytes)

    def test_hybrid_parser_satisfies_protocol(self) -> None:
        """HybridDocumentParser is a valid DocumentParser."""
        from app.services.rag.parser import DocumentParser, HybridDocumentParser

        parser: DocumentParser = HybridDocumentParser()
        assert hasattr(parser, "supported_extensions")
        assert hasattr(parser, "parse_bytes")
        assert callable(parser.parse_bytes)

    def test_extensions_are_correct_sets(self) -> None:
        """Each parser exposes the correct set of supported extensions."""
        from app.services.rag.parser import (
            HybridDocumentParser,
            LocalDocumentParser,
            MinerUDocumentParser,
        )

        local = LocalDocumentParser()
        assert local.supported_extensions == {".txt", ".md", ".pdf", ".docx"}

        mineru = MinerUDocumentParser(base_url="https://mineru.example")
        assert mineru.supported_extensions == {".pdf", ".docx"}

        hybrid = HybridDocumentParser(mineru_base_url="https://mineru.example")
        assert hybrid.supported_extensions == {".txt", ".md", ".pdf", ".docx"}


class TestMinerUApiKeyHandling:
    """Tests for MinerU API key authentication."""

    def test_bearer_token_sent_when_api_key_provided(self) -> None:
        """API key is sent as Bearer token in Authorization header."""
        captured_auth: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_auth["authorization"] = request.headers.get("authorization", "")
            return httpx.Response(
                200,
                json={"markdown": "# Test", "page_count": 1},
            )

        from app.services.rag.parser import MinerUDocumentParser

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = MinerUDocumentParser(
            base_url="https://mineru.example",
            api_key="my-secret-key",
            client=client,
        )
        parser.parse_bytes(b"fake", filename="doc.pdf")

        assert captured_auth["authorization"] == "Bearer my-secret-key"

    def test_no_auth_header_when_api_key_empty(self) -> None:
        """No Authorization header is sent when API key is empty."""
        captured_auth: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_auth["authorization"] = request.headers.get("authorization")
            return httpx.Response(
                200,
                json={"markdown": "# Test", "page_count": 1},
            )

        from app.services.rag.parser import MinerUDocumentParser

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = MinerUDocumentParser(
            base_url="https://mineru.example",
            api_key="",
            client=client,
        )
        parser.parse_bytes(b"fake", filename="doc.pdf")

        assert captured_auth["authorization"] is None


class TestMinerUResponseVariants:
    """Tests for various MinerU response formats."""

    def test_response_with_text_field(self) -> None:
        """MinerU response using 'text' field is handled correctly."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"text": "# 使用text字段\n\n这是正文内容。", "page_count": 2},
            )

        from app.services.rag.parser import MinerUDocumentParser

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = MinerUDocumentParser(base_url="https://mineru.example", client=client)
        doc = parser.parse_bytes(b"fake", filename="doc.pdf")

        assert "# 使用text字段" in doc.text
        assert doc.metadata["pageCount"] == 2

    def test_response_with_content_field(self) -> None:
        """MinerU response using 'content' field is handled correctly."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"content": "# 使用content字段\n\n这是正文内容。", "documentId": "id_xyz"},
            )

        from app.services.rag.parser import MinerUDocumentParser

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = MinerUDocumentParser(base_url="https://mineru.example", client=client)
        doc = parser.parse_bytes(b"fake", filename="doc.pdf")

        assert "# 使用content字段" in doc.text
        assert doc.metadata["documentId"] == "id_xyz"

    def test_response_with_camelcase_fields(self) -> None:
        """MinerU response with camelCase fields (pageCount, documentId) is handled."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "markdown": "# Markdown",
                    "pageCount": 5,
                    "documentId": "doc_555",
                    "version": "3.0.0",
                },
            )

        from app.services.rag.parser import MinerUDocumentParser

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = MinerUDocumentParser(base_url="https://mineru.example", client=client)
        doc = parser.parse_bytes(b"fake", filename="doc.pdf")

        assert doc.metadata["pageCount"] == 5
        assert doc.metadata["documentId"] == "doc_555"
        assert doc.metadata["parserVersion"] == "3.0.0"

    def test_plain_string_response_treated_as_content(self) -> None:
        """MinerU returns plain string instead of JSON object - handled gracefully."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="# Plain string response\n\nContent here.")

        from app.services.rag.parser import MinerUDocumentParser

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        parser = MinerUDocumentParser(base_url="https://mineru.example", client=client)
        doc = parser.parse_bytes(b"fake", filename="doc.pdf")

        assert doc.text == "# Plain string response\n\nContent here."
        assert doc.metadata["parser"] == "mineru"
