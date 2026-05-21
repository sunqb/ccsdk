"""RAG service helpers."""

from .agent_runner import RagAgentRunner, RagAgentRunnerConfig, rag_agent_runner
from .chunker import RagChunk, TextChunker
from .embeddings import (
    EmbeddingProvider,
    LocalHashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from .ingestion import (
    FileSetRecord,
    IngestFile,
    KnowledgeBaseRecord,
    RagIngestionService,
    rag_ingestion_service,
)
from .mcp import RAG_MCP_ALLOWED_TOOLS, create_rag_mcp_server
from .parser import ParsedDocument, TextDocumentParser
from .production import RagConcurrencyGuard, build_provider_info
from .answer_verifier import RagAnswerVerifier, RagVerificationResult, rag_answer_verifier
from .evaluation import DEFAULT_EVAL_CASES, evaluate_retrieval_cases
from .observability import RecordingRagToolService
from .pipeline import (
    abstention_reason_labels,
    build_request_context,
    new_retrieval_trace,
    structured_abstention_answer,
)
from .reranker import RerankerProvider, build_reranker
from .retriever import RagRetriever, RetrievalTrace, rag_retriever
from .state_store import SQLiteRagStateStore
from .tool_executor import RagToolExecutor, rag_tool_executor
from .tools import RagToolService, rag_tool_service
from .vector_store import LocalVectorStore, SearchResult, VectorStore

__all__ = [
    "EmbeddingProvider",
    "FileSetRecord",
    "IngestFile",
    "KnowledgeBaseRecord",
    "LocalHashEmbeddingProvider",
    "LocalVectorStore",
    "OpenAICompatibleEmbeddingProvider",
    "RAG_MCP_ALLOWED_TOOLS",
    "ParsedDocument",
    "RagChunk",
    "RagAgentRunner",
    "RagAgentRunnerConfig",
    "RagAnswerVerifier",
    "RagConcurrencyGuard",
    "RagIngestionService",
    "RagRetriever",
    "RagToolExecutor",
    "RagToolService",
    "RagVerificationResult",
    "RecordingRagToolService",
    "RerankerProvider",
    "RetrievalTrace",
    "DEFAULT_EVAL_CASES",
    "SearchResult",
    "SQLiteRagStateStore",
    "TextChunker",
    "TextDocumentParser",
    "VectorStore",
    "abstention_reason_labels",
    "build_provider_info",
    "build_request_context",
    "build_reranker",
    "evaluate_retrieval_cases",
    "new_retrieval_trace",
    "structured_abstention_answer",
    "create_rag_mcp_server",
    "rag_answer_verifier",
    "rag_agent_runner",
    "rag_ingestion_service",
    "rag_retriever",
    "rag_tool_executor",
    "rag_tool_service",
]
