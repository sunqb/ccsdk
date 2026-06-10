-- ============================================================================
-- RAG 纯文件问答（parse-only QA）特性 DDL
--
-- 目标：上传时跳过 chunk / embed / vector store，将“上传文件”和
--       “可复用解析内容缓存”拆表保存；问答时通过 e_rag_file.parsed_content_id
--       join e_rag_parsed_content 后把 parsed_text 作为上下文直接注入 LLM。
--
-- 用法：
--   1) 对生产 MySQL 执行本脚本。
--   2) dev/test 环境可省略本脚本，SQLAlchemy Base.metadata.create_all() 会
--      根据 ORM 模型自动建表（见 app/database.py: ERagParsedContent）。
-- ============================================================================

-- 旧表职责混杂（解析全文 + 上传文件关系），新方案废弃。
DROP TABLE IF EXISTS e_rag_parsed_file;

CREATE TABLE IF NOT EXISTS e_rag_parsed_content (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'id',
  parsed_content_id VARCHAR(64) NOT NULL COMMENT '解析内容业务ID，如 pc_xxx',
  md5 CHAR(32) NOT NULL COMMENT '文件内容MD5',
  file_size BIGINT DEFAULT 0 COMMENT '文件大小，单位字节',
  parser VARCHAR(32) NOT NULL COMMENT '解析器：local / mineru / kimi',
  parser_version VARCHAR(64) DEFAULT NULL COMMENT '解析器版本',
  parser_config_hash VARCHAR(64) DEFAULT NULL COMMENT '解析配置hash',
  mime_type VARCHAR(128) COMMENT 'MIME类型',
  parsed_text LONGTEXT COMMENT '解析后文本',
  status SMALLINT DEFAULT 1 COMMENT '状态，1：处理中，2：就绪，3：失败',
  error_code VARCHAR(64) COMMENT '错误码',
  error_message VARCHAR(1024) COMMENT '错误信息',
  metadata JSON COMMENT '扩展元数据',
  create_by VARCHAR(64),
  create_time DATETIME,
  update_by VARCHAR(64),
  update_time DATETIME,
  is_delete SMALLINT DEFAULT 1 COMMENT '是否删除，1：正常，2：删除',
  parser_version_scope VARCHAR(64)
    GENERATED ALWAYS AS (COALESCE(parser_version, '')) STORED,
  parser_config_hash_scope VARCHAR(64)
    GENERATED ALWAYS AS (COALESCE(parser_config_hash, '')) STORED,
  UNIQUE KEY uk_parsed_content_id (parsed_content_id),
  UNIQUE KEY uk_parse_cache_key (
    md5,
    file_size,
    parser,
    parser_version_scope,
    parser_config_hash_scope,
    is_delete
  ),
  INDEX idx_md5 (md5),
  INDEX idx_parser (parser)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG解析内容缓存表';

-- MySQL 5.7 / 部分 8.0 小版本不支持 ALTER TABLE ... ADD COLUMN IF NOT EXISTS，
-- 这里用 information_schema + 动态 SQL 保持脚本可重复执行。
DELIMITER $$

DROP PROCEDURE IF EXISTS rag_add_column_if_missing $$
CREATE PROCEDURE rag_add_column_if_missing(
  IN p_table_name VARCHAR(64),
  IN p_column_name VARCHAR(64),
  IN p_column_ddl TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = p_table_name
      AND COLUMN_NAME = p_column_name
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE `', p_table_name, '` ADD COLUMN ', p_column_ddl);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DROP PROCEDURE IF EXISTS rag_add_index_if_missing $$
CREATE PROCEDURE rag_add_index_if_missing(
  IN p_table_name VARCHAR(64),
  IN p_index_name VARCHAR(64),
  IN p_index_ddl TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = p_table_name
      AND INDEX_NAME = p_index_name
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE `', p_table_name, '` ADD ', p_index_ddl);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DELIMITER ;

CALL rag_add_column_if_missing(
  'e_rag_file_set',
  'parse_only',
  'parse_only SMALLINT DEFAULT 1 COMMENT ''是否仅解析不入库RAG，1：否（默认，走RAG），2：是（纯文件问答）'''
);

CALL rag_add_column_if_missing(
  'e_rag_file',
  'parsed_content_id',
  'parsed_content_id VARCHAR(64) NULL COMMENT ''parseOnly解析内容ID'''
);

CALL rag_add_index_if_missing(
  'e_rag_file',
  'idx_parsed_content_id',
  'INDEX idx_parsed_content_id (parsed_content_id)'
);

DROP PROCEDURE IF EXISTS rag_add_column_if_missing;
DROP PROCEDURE IF EXISTS rag_add_index_if_missing;
