-- RAG 命名知识库数据库表结构。
-- MySQL 8.x
--
-- 说明：
-- 1. 表名统一使用 e_ 前缀。
-- 2. 主键统一使用自增 id。
-- 3. 业务标识统一使用 *_id 命名，以便和 API 层保持一致。
-- 4. 审计字段统一为 create_by、create_time、update_by、update_time、is_delete。
-- 5. is_delete：1 = 正常，2 = 删除。
-- 6. 生成列用于归一化 NULL 作用域，确保 tenant_id/owner_id 为空时唯一键仍可稳定防重。

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================================
-- 1. RAG 知识库表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_knowledge_base` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `knowledge_base_id` varchar(64) NOT NULL COMMENT '知识库业务 ID，例如 kb_xxx',
  `name` varchar(128) NOT NULL COMMENT '知识库名称，例如 zsk1',
  `description` varchar(512) DEFAULT NULL COMMENT '知识库描述',
  `source_file_set_id` varchar(64) NOT NULL COMMENT '来源文件集业务 ID',

  `status` tinyint NOT NULL DEFAULT 1 COMMENT '状态：1 处理中，2 就绪，3 部分就绪，4 失败',

  `tenant_id` varchar(64) DEFAULT NULL COMMENT '租户 ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT '所有者 ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key 标识，禁止保存明文密钥',

  `vector_provider` varchar(64) DEFAULT NULL COMMENT '向量库 provider，例如 local/qdrant/milvus/pgvector',
  `vector_collection` varchar(128) DEFAULT NULL COMMENT '向量库 collection',
  `vector_namespace` varchar(128) DEFAULT NULL COMMENT '向量库 namespace',
  `vector_filter` json DEFAULT NULL COMMENT '向量检索过滤条件',

  `embedding_provider` varchar(64) DEFAULT NULL COMMENT 'Embedding provider，例如 openai_compatible/local',
  `embedding_model` varchar(128) DEFAULT NULL COMMENT 'Embedding 模型，例如 bge-m3:latest',
  `embedding_dimension` int DEFAULT NULL COMMENT 'Embedding 维度，例如 BGE-M3 为 1024',
  `embedding_base_url` varchar(512) DEFAULT NULL COMMENT 'Embedding 服务 base URL，不包含密钥',

  `metadata` json DEFAULT NULL COMMENT '扩展元数据',

  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT '删除标记：1 正常，2 删除',

  `tenant_scope_id` varchar(64)
    GENERATED ALWAYS AS (coalesce(`tenant_id`, '')) STORED COMMENT '归一化租户作用域，用于唯一键',
  `owner_scope_id` varchar(64)
    GENERATED ALWAYS AS (coalesce(`owner_id`, '')) STORED COMMENT '归一化所有者作用域，用于唯一键',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_kb_id` (`knowledge_base_id`) USING BTREE,
  UNIQUE KEY `uk_scope_name` (`tenant_scope_id`, `owner_scope_id`, `name`, `is_delete`) USING BTREE,
  KEY `idx_source_file_set_id` (`source_file_set_id`) USING BTREE,
  KEY `idx_name` (`name`) USING BTREE,
  KEY `idx_scope_name_active` (`name`, `is_delete`) USING BTREE,
  KEY `idx_tenant_owner` (`tenant_id`, `owner_id`) USING BTREE,
  KEY `idx_embedding_model` (`embedding_provider`, `embedding_model`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 知识库表';


-- ============================================================
-- 2. RAG 文件集表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_file_set` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `file_set_id` varchar(64) NOT NULL COMMENT '文件集业务 ID，例如 fs_xxx',
  `conversation_id` varchar(64) DEFAULT NULL COMMENT '会话 ID',

  `status` tinyint NOT NULL DEFAULT 1 COMMENT '状态：1 处理中，2 就绪，3 部分就绪，4 失败',
  `indexed_chunks` int NOT NULL DEFAULT 0 COMMENT '已索引 chunk 数量',
  `total_chunks` int NOT NULL DEFAULT 0 COMMENT '总 chunk 数量',

  `temporary` tinyint NOT NULL DEFAULT 1 COMMENT '临时标记：1 临时，2 持久',
  `knowledge_base_id` varchar(64) DEFAULT NULL COMMENT '关联知识库业务 ID',

  `tenant_id` varchar(64) DEFAULT NULL COMMENT '租户 ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT '所有者 ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key 标识，禁止保存明文密钥',

  `metadata` json DEFAULT NULL COMMENT '扩展元数据',
  `expires_time` datetime DEFAULT NULL COMMENT '临时文件集过期时间',

  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT '删除标记：1 正常，2 删除',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_knowledge_base_id` (`knowledge_base_id`) USING BTREE,
  KEY `idx_conversation_id` (`conversation_id`) USING BTREE,
  KEY `idx_tenant_owner` (`tenant_id`, `owner_id`) USING BTREE,
  KEY `idx_status` (`status`, `is_delete`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 文件集表';


-- ============================================================
-- 3. RAG 文件表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_file` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `file_id` varchar(64) NOT NULL COMMENT '文件业务 ID，例如 file_xxx',
  `file_set_id` varchar(64) NOT NULL COMMENT '文件集业务 ID',

  `filename` varchar(512) NOT NULL COMMENT '原始文件名',
  `mime_type` varchar(128) DEFAULT NULL COMMENT 'MIME 类型',
  `file_size` bigint NOT NULL DEFAULT 0 COMMENT '文件大小，单位字节',

  `storage_type` tinyint NOT NULL DEFAULT 1 COMMENT '存储类型：1 本地，2 对象存储，3 外部 URL',
  `file_path` varchar(1024) DEFAULT NULL COMMENT '原始文件路径或对象存储 key',
  `parsed_file_path` varchar(1024) DEFAULT NULL COMMENT '解析后的文本或 Markdown 文件路径',
  `file_url` varchar(1024) DEFAULT NULL COMMENT '文件访问 URL，可为空',

  `status` tinyint NOT NULL DEFAULT 1 COMMENT '状态：1 处理中，2 就绪，3 失败',
  `error_code` varchar(64) DEFAULT NULL COMMENT '错误码',
  `error_message` varchar(1024) DEFAULT NULL COMMENT '错误信息',

  `metadata` json DEFAULT NULL COMMENT '扩展元数据',

  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT '删除标记：1 正常，2 删除',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_file_id` (`file_id`) USING BTREE,
  KEY `idx_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_status` (`status`, `is_delete`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 文件表';


-- ============================================================
-- 4. RAG Chunk 表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_chunk` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `chunk_id` varchar(128) NOT NULL COMMENT 'Chunk 业务 ID',
  `file_set_id` varchar(64) NOT NULL COMMENT '文件集业务 ID',
  `knowledge_base_id` varchar(64) DEFAULT NULL COMMENT '知识库业务 ID',
  `source_file_id` varchar(64) DEFAULT NULL COMMENT '来源文件业务 ID',

  `vector_provider` varchar(64) DEFAULT NULL COMMENT '向量库 provider，例如 local/qdrant/milvus/pgvector',
  `vector_collection` varchar(128) DEFAULT NULL COMMENT '向量库 collection',
  `vector_namespace` varchar(128) DEFAULT NULL COMMENT '向量库 namespace',
  `vector_id` varchar(128) DEFAULT NULL COMMENT '外部向量库中的向量点 ID',

  `embedding_provider` varchar(64) DEFAULT NULL COMMENT 'Embedding provider，例如 openai_compatible/local',
  `embedding_model` varchar(128) DEFAULT NULL COMMENT 'Embedding 模型，例如 bge-m3:latest',
  `embedding_dimension` int DEFAULT NULL COMMENT 'Embedding 维度',

  `chunk_index` int DEFAULT NULL COMMENT 'Chunk 序号',
  `chunk_text` mediumtext DEFAULT NULL COMMENT 'Chunk 文本内容',
  `token_count` int NOT NULL DEFAULT 0 COMMENT 'Token 数量',

  `metadata` json DEFAULT NULL COMMENT '扩展元数据',

  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT '删除标记：1 正常，2 删除',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_chunk_id` (`chunk_id`) USING BTREE,
  KEY `idx_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_knowledge_base_id` (`knowledge_base_id`) USING BTREE,
  KEY `idx_source_file_id` (`source_file_id`) USING BTREE,
  KEY `idx_vector_id` (`vector_provider`, `vector_collection`, `vector_id`) USING BTREE,
  KEY `idx_embedding_model` (`embedding_provider`, `embedding_model`) USING BTREE,
  KEY `idx_status` (`is_delete`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG Chunk 表';

SET FOREIGN_KEY_CHECKS = 1;
