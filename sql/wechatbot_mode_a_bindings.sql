-- WeChatBot Mode A SaaS 绑定表。
-- MySQL 8.x
--
-- 这些表复用 DB_DSN 指向的同一个 MySQL 数据库。
-- 微信 user_id 明文不落库，仅保存 sha256(user_id)[:16]
-- 到 user_id_hash / used_by_user_id_hash。

SET NAMES utf8mb4;

-- ============================================================
-- 1. 微信用户绑定表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_wechatbot_user_binding` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT 'id',
  `bot_instance_id` varchar(128) NOT NULL COMMENT '机器人实例ID，Mode A 默认为 default',
  `user_id_hash` varchar(64) NOT NULL COMMENT '微信 user_id 的 sha256 哈希前16位，不保存明文 user_id',
  `tenant_id` varchar(128) NOT NULL COMMENT 'SaaS 租户ID',
  `app_user_id` varchar(128) NOT NULL COMMENT 'SaaS 应用用户ID',
  `default_mode` varchar(32) DEFAULT NULL COMMENT '默认路由模式，可选 agent/rag',
  `rag_scope_json` json DEFAULT NULL COMMENT '用户级 RAG 作用域 JSON',
  `status` smallint NOT NULL DEFAULT 1 COMMENT '状态，1：启用，2：解绑/禁用',
  `bind_source` varchar(32) NOT NULL DEFAULT 'token' COMMENT '绑定来源，如 token/admin/import/env_mirror',
  `last_seen_time` datetime DEFAULT NULL COMMENT '最近收到该微信用户消息时间',
  `unbound_time` datetime DEFAULT NULL COMMENT '软解绑时间',
  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime NOT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime NOT NULL COMMENT '更新时间',
  `is_delete` smallint NOT NULL DEFAULT 1 COMMENT '是否删除，1：正常，2：删除',

  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_wechat_binding` (`bot_instance_id`, `user_id_hash`) USING BTREE,
  KEY `idx_tenant_app_user` (`tenant_id`, `app_user_id`) USING BTREE,
  KEY `idx_user_hash` (`user_id_hash`) USING BTREE,
  KEY `idx_status_last_seen` (`status`, `last_seen_time`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信机器人用户与 SaaS 身份绑定表';


-- ============================================================
-- 2. 微信绑定码表
-- ============================================================

CREATE TABLE IF NOT EXISTS `e_wechatbot_bind_token` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT 'id',
  `token_hash` varchar(128) NOT NULL COMMENT '绑定码大写归一化后的 sha256 哈希，不保存明文绑定码',
  `token_preview` varchar(16) NOT NULL COMMENT '绑定码预览，用于管理端展示，如后6位',
  `tenant_id` varchar(128) NOT NULL COMMENT 'SaaS 租户ID',
  `app_user_id` varchar(128) NOT NULL COMMENT 'SaaS 应用用户ID',
  `bot_instance_id` varchar(128) NOT NULL COMMENT '机器人实例ID',
  `default_mode` varchar(32) DEFAULT NULL COMMENT '默认路由模式，可选 agent/rag',
  `rag_scope_json` json DEFAULT NULL COMMENT '绑定成功后写入用户绑定记录的 RAG 作用域 JSON',
  `expires_time` datetime NOT NULL COMMENT '绑定码过期时间',
  `used_time` datetime DEFAULT NULL COMMENT '绑定码使用时间',
  `revoked_time` datetime DEFAULT NULL COMMENT '绑定码撤销时间',
  `used_by_user_id_hash` varchar(64) DEFAULT NULL COMMENT '使用该绑定码的微信 user_id 哈希前16位',
  `create_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `create_time` datetime NOT NULL COMMENT '创建时间',
  `update_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `update_time` datetime NOT NULL COMMENT '更新时间',
  `is_delete` smallint NOT NULL DEFAULT 1 COMMENT '是否删除，1：正常，2：删除',

  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_token_hash` (`token_hash`) USING BTREE,
  KEY `idx_tenant_app_user` (`tenant_id`, `app_user_id`) USING BTREE,
  KEY `idx_bot_expires_time` (`bot_instance_id`, `expires_time`) USING BTREE,
  KEY `idx_token_state` (`used_time`, `revoked_time`, `expires_time`) USING BTREE,
  KEY `idx_used_by_user_hash` (`used_by_user_id_hash`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信机器人一次性绑定码表';
