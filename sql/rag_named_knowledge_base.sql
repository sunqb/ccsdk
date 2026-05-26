-- RAG named knowledge base database schema.
-- MySQL 8.x
--
-- Notes:
-- 1. Table names use the e_ prefix.
-- 2. Primary keys use auto-increment id.
-- 3. Business identifiers use *_id names to align with the API layer.
-- 4. Audit fields: create_by, create_time, update_by, update_time, is_delete.
-- 5. is_delete: 1 = active, 2 = deleted.
-- 6. Generated scope columns normalize NULL values so MySQL unique keys can
--    reliably prevent duplicate names when tenant_id/owner_id are NULL.

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================================
-- 1. RAG knowledge base table
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_knowledge_base` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `knowledge_base_id` varchar(64) NOT NULL COMMENT 'Knowledge base business ID, e.g. kb_xxx',
  `name` varchar(128) NOT NULL COMMENT 'Knowledge base name, e.g. zsk1',
  `description` varchar(512) DEFAULT NULL COMMENT 'Knowledge base description',
  `source_file_set_id` varchar(64) NOT NULL COMMENT 'Source file set business ID',

  `status` tinyint NOT NULL DEFAULT 1 COMMENT 'Status: 1 processing, 2 ready, 3 partial ready, 4 failed',

  `tenant_id` varchar(64) DEFAULT NULL COMMENT 'Tenant ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT 'Owner ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key ID; never store plaintext API keys here',

  `vector_provider` varchar(64) DEFAULT NULL COMMENT 'Vector provider, e.g. local/qdrant/milvus/pgvector',
  `vector_collection` varchar(128) DEFAULT NULL COMMENT 'Vector collection',
  `vector_namespace` varchar(128) DEFAULT NULL COMMENT 'Vector namespace',
  `vector_filter` json DEFAULT NULL COMMENT 'Vector retrieval filter',

  `embedding_provider` varchar(64) DEFAULT NULL COMMENT 'Embedding provider, e.g. openai_compatible/local',
  `embedding_model` varchar(128) DEFAULT NULL COMMENT 'Embedding model, e.g. bge-m3:latest',
  `embedding_dimension` int DEFAULT NULL COMMENT 'Embedding dimension, e.g. BGE-M3 is 1024',
  `embedding_base_url` varchar(512) DEFAULT NULL COMMENT 'Embedding service base URL, without secret',

  `metadata` json DEFAULT NULL COMMENT 'Extended metadata',

  `create_by` varchar(64) DEFAULT NULL COMMENT 'Created by',
  `create_time` datetime DEFAULT NULL COMMENT 'Created time',
  `update_by` varchar(64) DEFAULT NULL COMMENT 'Updated by',
  `update_time` datetime DEFAULT NULL COMMENT 'Updated time',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT 'Delete flag: 1 active, 2 deleted',

  `tenant_scope_id` varchar(64)
    GENERATED ALWAYS AS (coalesce(`tenant_id`, '')) STORED COMMENT 'Normalized tenant scope for unique keys',
  `owner_scope_id` varchar(64)
    GENERATED ALWAYS AS (coalesce(`owner_id`, '')) STORED COMMENT 'Normalized owner scope for unique keys',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_kb_id` (`knowledge_base_id`) USING BTREE,
  UNIQUE KEY `uk_scope_name` (`tenant_scope_id`, `owner_scope_id`, `name`, `is_delete`) USING BTREE,
  KEY `idx_source_file_set_id` (`source_file_set_id`) USING BTREE,
  KEY `idx_name` (`name`) USING BTREE,
  KEY `idx_scope_name_active` (`name`, `is_delete`) USING BTREE,
  KEY `idx_tenant_owner` (`tenant_id`, `owner_id`) USING BTREE,
  KEY `idx_embedding_model` (`embedding_provider`, `embedding_model`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG knowledge base table';


-- ============================================================
-- 2. RAG file set table
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_file_set` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `file_set_id` varchar(64) NOT NULL COMMENT 'File set business ID, e.g. fs_xxx',
  `conversation_id` varchar(64) DEFAULT NULL COMMENT 'Conversation ID',

  `status` tinyint NOT NULL DEFAULT 1 COMMENT 'Status: 1 processing, 2 ready, 3 partial ready, 4 failed',
  `indexed_chunks` int NOT NULL DEFAULT 0 COMMENT 'Indexed chunk count',
  `total_chunks` int NOT NULL DEFAULT 0 COMMENT 'Total chunk count',

  `temporary` tinyint NOT NULL DEFAULT 1 COMMENT 'Temporary flag: 1 temporary, 2 persistent',
  `knowledge_base_id` varchar(64) DEFAULT NULL COMMENT 'Related knowledge base business ID',

  `tenant_id` varchar(64) DEFAULT NULL COMMENT 'Tenant ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT 'Owner ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key ID; never store plaintext API keys here',

  `metadata` json DEFAULT NULL COMMENT 'Extended metadata',
  `expires_time` datetime DEFAULT NULL COMMENT 'Temporary file set expiration time',

  `create_by` varchar(64) DEFAULT NULL COMMENT 'Created by',
  `create_time` datetime DEFAULT NULL COMMENT 'Created time',
  `update_by` varchar(64) DEFAULT NULL COMMENT 'Updated by',
  `update_time` datetime DEFAULT NULL COMMENT 'Updated time',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT 'Delete flag: 1 active, 2 deleted',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_knowledge_base_id` (`knowledge_base_id`) USING BTREE,
  KEY `idx_conversation_id` (`conversation_id`) USING BTREE,
  KEY `idx_tenant_owner` (`tenant_id`, `owner_id`) USING BTREE,
  KEY `idx_status` (`status`, `is_delete`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG file set table';


-- ============================================================
-- 3. RAG file table
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_file` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `file_id` varchar(64) NOT NULL COMMENT 'File business ID, e.g. file_xxx',
  `file_set_id` varchar(64) NOT NULL COMMENT 'File set business ID',

  `filename` varchar(512) NOT NULL COMMENT 'Original filename',
  `mime_type` varchar(128) DEFAULT NULL COMMENT 'MIME type',
  `file_size` bigint NOT NULL DEFAULT 0 COMMENT 'File size in bytes',

  `storage_type` tinyint NOT NULL DEFAULT 1 COMMENT 'Storage type: 1 local, 2 object storage, 3 external URL',
  `file_path` varchar(1024) DEFAULT NULL COMMENT 'Original file path or object key',
  `parsed_file_path` varchar(1024) DEFAULT NULL COMMENT 'Parsed text/Markdown file path',
  `file_url` varchar(1024) DEFAULT NULL COMMENT 'File access URL, optional',

  `status` tinyint NOT NULL DEFAULT 1 COMMENT 'Status: 1 processing, 2 ready, 3 failed',
  `error_code` varchar(64) DEFAULT NULL COMMENT 'Error code',
  `error_message` varchar(1024) DEFAULT NULL COMMENT 'Error message',

  `metadata` json DEFAULT NULL COMMENT 'Extended metadata',

  `create_by` varchar(64) DEFAULT NULL COMMENT 'Created by',
  `create_time` datetime DEFAULT NULL COMMENT 'Created time',
  `update_by` varchar(64) DEFAULT NULL COMMENT 'Updated by',
  `update_time` datetime DEFAULT NULL COMMENT 'Updated time',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT 'Delete flag: 1 active, 2 deleted',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_file_id` (`file_id`) USING BTREE,
  KEY `idx_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_status` (`status`, `is_delete`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG file table';


-- ============================================================
-- 4. RAG chunk table
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_chunk` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `chunk_id` varchar(128) NOT NULL COMMENT 'Chunk business ID',
  `file_set_id` varchar(64) NOT NULL COMMENT 'File set business ID',
  `knowledge_base_id` varchar(64) DEFAULT NULL COMMENT 'Knowledge base business ID',
  `source_file_id` varchar(64) DEFAULT NULL COMMENT 'Source file business ID',

  `vector_provider` varchar(64) DEFAULT NULL COMMENT 'Vector provider, e.g. local/qdrant/milvus/pgvector',
  `vector_collection` varchar(128) DEFAULT NULL COMMENT 'Vector collection',
  `vector_namespace` varchar(128) DEFAULT NULL COMMENT 'Vector namespace',
  `vector_id` varchar(128) DEFAULT NULL COMMENT 'Vector point ID in external vector store',

  `embedding_provider` varchar(64) DEFAULT NULL COMMENT 'Embedding provider, e.g. openai_compatible/local',
  `embedding_model` varchar(128) DEFAULT NULL COMMENT 'Embedding model, e.g. bge-m3:latest',
  `embedding_dimension` int DEFAULT NULL COMMENT 'Embedding dimension',

  `chunk_index` int DEFAULT NULL COMMENT 'Chunk index',
  `chunk_text` mediumtext DEFAULT NULL COMMENT 'Chunk text',
  `token_count` int NOT NULL DEFAULT 0 COMMENT 'Token count',

  `metadata` json DEFAULT NULL COMMENT 'Extended metadata',

  `create_by` varchar(64) DEFAULT NULL COMMENT 'Created by',
  `create_time` datetime DEFAULT NULL COMMENT 'Created time',
  `update_by` varchar(64) DEFAULT NULL COMMENT 'Updated by',
  `update_time` datetime DEFAULT NULL COMMENT 'Updated time',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT 'Delete flag: 1 active, 2 deleted',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_chunk_id` (`chunk_id`) USING BTREE,
  KEY `idx_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_knowledge_base_id` (`knowledge_base_id`) USING BTREE,
  KEY `idx_source_file_id` (`source_file_id`) USING BTREE,
  KEY `idx_vector_id` (`vector_provider`, `vector_collection`, `vector_id`) USING BTREE,
  KEY `idx_embedding_model` (`embedding_provider`, `embedding_model`) USING BTREE,
  KEY `idx_status` (`is_delete`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG chunk table';

SET FOREIGN_KEY_CHECKS = 1;
