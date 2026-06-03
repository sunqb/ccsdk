-- RAG 生产元数据扩展表。
-- MySQL 8.x
--
-- 用途：
-- 1. 补充 sql/rag_named_knowledge_base.sql 中未覆盖的生产级元数据表。
-- 2. 明确 MySQL 是 RAG 元数据单点真值。
-- 3. 支持入库任务追踪、检索可观测性、用量统计、审计日志和 provider 健康检查。
--
-- 说明：
-- - is_delete：1 = 正常，2 = 删除。
-- - api_key_id 只保存 API Key 标识，禁止保存明文密钥。
-- - 生成列用于归一化 NULL 作用域，保证唯一键稳定生效。

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================================
-- 1. RAG 入库任务表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_ingestion_job` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `job_id` varchar(64) NOT NULL COMMENT '入库任务业务 ID，例如 job_xxx',
  `file_set_id` varchar(64) NOT NULL COMMENT '关联文件集业务 ID，例如 fs_xxx',
  `knowledge_base_id` varchar(64) DEFAULT NULL COMMENT '关联知识库业务 ID，可为空',

  `tenant_id` varchar(64) DEFAULT NULL COMMENT '租户 ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT '所有者 ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key 标识，禁止保存明文密钥',

  `status` varchar(32) NOT NULL DEFAULT 'pending' COMMENT '任务状态：pending/running/succeeded/partial_failed/failed/cancelled',
  `stage` varchar(32) DEFAULT NULL COMMENT '当前阶段：uploaded/parsing/chunking/embedding/indexing/finalizing',
  `progress_percent` int NOT NULL DEFAULT 0 COMMENT '进度百分比，范围 0 到 100',

  `retry_count` int NOT NULL DEFAULT 0 COMMENT '当前重试次数',
  `max_retries` int NOT NULL DEFAULT 0 COMMENT '最大重试次数',
  `error_code` varchar(64) DEFAULT NULL COMMENT '结构化错误码',
  `error_message` varchar(2048) DEFAULT NULL COMMENT '错误信息',

  `started_time` datetime DEFAULT NULL COMMENT '任务开始时间',
  `finished_time` datetime DEFAULT NULL COMMENT '任务结束时间',
  `metadata` json DEFAULT NULL COMMENT '扩展元数据',

  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT '删除标记：1 正常，2 删除',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_job_id` (`job_id`) USING BTREE,
  KEY `idx_file_set_id` (`file_set_id`) USING BTREE,
  KEY `idx_knowledge_base_id` (`knowledge_base_id`) USING BTREE,
  KEY `idx_scope_status` (`tenant_id`, `owner_id`, `status`, `is_delete`) USING BTREE,
  KEY `idx_status_stage` (`status`, `stage`, `is_delete`) USING BTREE,
  KEY `idx_create_time` (`create_time`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 入库任务表';


-- ============================================================
-- 2. RAG 查询日志表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_query_log` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `query_id` varchar(64) NOT NULL COMMENT '查询业务 ID，例如 query_xxx',
  `request_id` varchar(64) DEFAULT NULL COMMENT 'API 或 SSE 层请求 ID',
  `conversation_id` varchar(64) DEFAULT NULL COMMENT '会话 ID',

  `tenant_id` varchar(64) DEFAULT NULL COMMENT '租户 ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT '所有者 ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key 标识，禁止保存明文密钥',

  `message` mediumtext COMMENT '用户原始问题',
  `source_scope_json` json DEFAULT NULL COMMENT '解析后的来源范围和权限元数据',
  `retrieval_top_k` int DEFAULT NULL COMMENT '请求的检索 top_k',
  `retrieve_top_k` int DEFAULT NULL COMMENT '候选召回池大小',
  `final_top_k` int DEFAULT NULL COMMENT '最终证据数量',
  `matched_chunks` json DEFAULT NULL COMMENT '命中的 chunk ID 和分数',
  `citation_count` int NOT NULL DEFAULT 0 COMMENT '引用数量',

  `confidence` decimal(8,6) DEFAULT NULL COMMENT '检索或回答置信度',
  `abstained` tinyint NOT NULL DEFAULT 2 COMMENT '是否拒答：1 是，2 否',
  `abstention_reason` varchar(128) DEFAULT NULL COMMENT '拒答原因',

  `latency_ms` int DEFAULT NULL COMMENT '端到端耗时，单位毫秒',
  `prompt_tokens` int NOT NULL DEFAULT 0 COMMENT '提示词 token 数',
  `completion_tokens` int NOT NULL DEFAULT 0 COMMENT '回答 token 数',
  `embedding_tokens` int NOT NULL DEFAULT 0 COMMENT 'Embedding token 数',
  `model` varchar(128) DEFAULT NULL COMMENT '回答模型',

  `metadata` json DEFAULT NULL COMMENT '扩展元数据',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT '删除标记：1 正常，2 删除',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_query_id` (`query_id`) USING BTREE,
  KEY `idx_request_id` (`request_id`) USING BTREE,
  KEY `idx_conversation_id` (`conversation_id`) USING BTREE,
  KEY `idx_scope_time` (`tenant_id`, `owner_id`, `create_time`) USING BTREE,
  KEY `idx_api_key_time` (`api_key_id`, `create_time`) USING BTREE,
  KEY `idx_abstained` (`abstained`, `create_time`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 查询日志表';


-- ============================================================
-- 3. RAG 工具调用日志表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_tool_call_log` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `tool_call_id` varchar(64) NOT NULL COMMENT '工具调用业务 ID，例如 toolcall_xxx',
  `query_id` varchar(64) DEFAULT NULL COMMENT '关联查询 ID',
  `request_id` varchar(64) DEFAULT NULL COMMENT '关联请求 ID',

  `tenant_id` varchar(64) DEFAULT NULL COMMENT '租户 ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT '所有者 ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key 标识，禁止保存明文密钥',

  `tool_name` varchar(128) NOT NULL COMMENT 'RAG 工具名称',
  `tool_args_json` json DEFAULT NULL COMMENT '工具参数 JSON',
  `result_count` int NOT NULL DEFAULT 0 COMMENT '工具返回结果数量',
  `latency_ms` int DEFAULT NULL COMMENT '工具调用耗时，单位毫秒',
  `error_code` varchar(64) DEFAULT NULL COMMENT '结构化错误码',
  `error_message` varchar(2048) DEFAULT NULL COMMENT '错误信息',
  `metadata` json DEFAULT NULL COMMENT '扩展元数据',

  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT '删除标记：1 正常，2 删除',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_tool_call_id` (`tool_call_id`) USING BTREE,
  KEY `idx_query_id` (`query_id`) USING BTREE,
  KEY `idx_request_id` (`request_id`) USING BTREE,
  KEY `idx_tool_name_time` (`tool_name`, `create_time`) USING BTREE,
  KEY `idx_scope_time` (`tenant_id`, `owner_id`, `create_time`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 工具调用日志表';


-- ============================================================
-- 4. RAG 每日用量表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_usage_daily` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `stat_date` date NOT NULL COMMENT '统计日期',
  `tenant_id` varchar(64) DEFAULT NULL COMMENT '租户 ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT '所有者 ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key 标识，禁止保存明文密钥',

  `uploaded_files` int NOT NULL DEFAULT 0 COMMENT '上传文件数',
  `uploaded_bytes` bigint NOT NULL DEFAULT 0 COMMENT '上传字节数',
  `parsed_pages` int NOT NULL DEFAULT 0 COMMENT '解析页数',
  `chunks_created` int NOT NULL DEFAULT 0 COMMENT '创建 chunk 数量',
  `embedding_tokens` bigint NOT NULL DEFAULT 0 COMMENT 'Embedding token 数',
  `query_count` int NOT NULL DEFAULT 0 COMMENT '查询次数',
  `retrieval_count` int NOT NULL DEFAULT 0 COMMENT '检索次数',
  `prompt_tokens` bigint NOT NULL DEFAULT 0 COMMENT '提示词 token 数',
  `completion_tokens` bigint NOT NULL DEFAULT 0 COMMENT '回答 token 数',
  `storage_bytes` bigint NOT NULL DEFAULT 0 COMMENT '预估存储字节数',

  `metadata` json DEFAULT NULL COMMENT '扩展元数据',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT '删除标记：1 正常，2 删除',

  `tenant_scope_id` varchar(64)
    GENERATED ALWAYS AS (coalesce(`tenant_id`, '')) STORED COMMENT '归一化租户作用域，用于唯一键',
  `owner_scope_id` varchar(64)
    GENERATED ALWAYS AS (coalesce(`owner_id`, '')) STORED COMMENT '归一化所有者作用域，用于唯一键',
  `api_key_scope_id` varchar(64)
    GENERATED ALWAYS AS (coalesce(`api_key_id`, '')) STORED COMMENT '归一化 API Key 作用域，用于唯一键',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_usage_scope_day` (`stat_date`, `tenant_scope_id`, `owner_scope_id`, `api_key_scope_id`, `is_delete`) USING BTREE,
  KEY `idx_scope_date` (`tenant_id`, `owner_id`, `stat_date`) USING BTREE,
  KEY `idx_api_key_date` (`api_key_id`, `stat_date`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 每日用量表';


-- ============================================================
-- 5. RAG audit log table
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_audit_log` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT 'id',

  `audit_id` varchar(64) NOT NULL COMMENT 'Audit business ID, e.g. audit_xxx',
  `tenant_id` varchar(64) DEFAULT NULL COMMENT 'Tenant ID',
  `owner_id` varchar(64) DEFAULT NULL COMMENT 'Owner ID',
  `api_key_id` varchar(64) DEFAULT NULL COMMENT 'API Key ID; never store plaintext API keys here',

  `actor_id` varchar(64) DEFAULT NULL COMMENT 'Actor user/service ID',
  `actor_type` varchar(32) DEFAULT NULL COMMENT 'user/api_key/system/worker',
  `action` varchar(128) NOT NULL COMMENT 'Action name, e.g. create_knowledge_base/delete/reindex/cleanup',
  `resource_type` varchar(64) DEFAULT NULL COMMENT 'Resource type',
  `resource_id` varchar(128) DEFAULT NULL COMMENT 'Resource business ID',
  `request_id` varchar(64) DEFAULT NULL COMMENT 'Request ID',
  `detail_json` json DEFAULT NULL COMMENT 'Action details',
  `ip_address` varchar(64) DEFAULT NULL COMMENT 'Client IP address',
  `user_agent` varchar(512) DEFAULT NULL COMMENT 'Client user agent',
  `result` varchar(32) DEFAULT NULL COMMENT 'success/failure',
  `error_code` varchar(64) DEFAULT NULL COMMENT 'Structured error code',
  `error_message` varchar(2048) DEFAULT NULL COMMENT 'Error message',

  `create_time` datetime DEFAULT NULL COMMENT 'Created time',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT 'Delete flag: 1 active, 2 deleted',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_audit_id` (`audit_id`) USING BTREE,
  KEY `idx_scope_time` (`tenant_id`, `owner_id`, `create_time`) USING BTREE,
  KEY `idx_resource` (`resource_type`, `resource_id`) USING BTREE,
  KEY `idx_action_time` (`action`, `create_time`) USING BTREE,
  KEY `idx_request_id` (`request_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG audit log table';


-- ============================================================
-- 6. RAG provider health table
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_rag_provider_health` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'id',

  `provider_id` varchar(128) NOT NULL COMMENT 'Provider health ID, e.g. vector:qdrant:rag_chunks',
  `provider_type` varchar(64) NOT NULL COMMENT 'vector/embedding/parser/reranker/mysql',
  `provider_name` varchar(64) NOT NULL COMMENT 'Provider name, e.g. qdrant/openai_compatible/mineru',
  `endpoint` varchar(512) DEFAULT NULL COMMENT 'Provider endpoint without secret',
  `collection` varchar(128) DEFAULT NULL COMMENT 'Vector collection or namespace, optional',
  `status` varchar(32) NOT NULL DEFAULT 'unknown' COMMENT 'healthy/degraded/unhealthy/unknown',
  `latency_ms` int DEFAULT NULL COMMENT 'Health check latency in milliseconds',
  `capabilities_json` json DEFAULT NULL COMMENT 'Provider capabilities',
  `error_code` varchar(64) DEFAULT NULL COMMENT 'Structured error code',
  `error_message` varchar(2048) DEFAULT NULL COMMENT 'Error message',
  `checked_time` datetime DEFAULT NULL COMMENT 'Health checked time',
  `metadata` json DEFAULT NULL COMMENT 'Extended metadata',

  `create_time` datetime DEFAULT NULL COMMENT 'Created time',
  `update_time` datetime DEFAULT NULL COMMENT 'Updated time',
  `is_delete` tinyint NOT NULL DEFAULT 1 COMMENT 'Delete flag: 1 active, 2 deleted',

  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_provider_id` (`provider_id`, `is_delete`) USING BTREE,
  KEY `idx_provider` (`provider_type`, `provider_name`, `status`) USING BTREE,
  KEY `idx_checked_time` (`checked_time`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG provider health table';

SET FOREIGN_KEY_CHECKS = 1;
