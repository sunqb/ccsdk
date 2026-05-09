# Agent 间通信协议

## 1. 概述

本文档定义古诗词视频生成系统中 6 个 Sub-agent 之间的通信规范，包括消息格式、状态机、数据契约和异常路由规则。

## 2. Agent 清单

| Agent ID | 名称 | Phase | 职责边界 |
|----------|------|-------|---------|
| `orchestrator` | 编排主控 | 全流程 | 状态机管理、依赖编排、异常路由、进度汇报 |
| `content-planner` | 内容策划 | Phase 1 | 诗词解析、智能推荐、生成蓝图JSON |
| `visual-asset-generator` | 视觉素材 | Phase 2 | 生成参考板图片 + 分镜视频 |
| `audio-narrator` | 音频旁白 | Phase 2 | TTS合成 + 时间轴校准 |
| `post-production-composer` | 后期合成 | Phase 3 | 音视频拼合 + 字幕 + 最终输出 |
| `quality-assurance` | 质检 | Phase 3 | 质量验证 + 问题报告 |

## 3. 状态机

```
                   ┌─────────────────────┐
                   │       idle          │
                   └─────────┬───────────┘
                             │ 用户输入诗词
                             ▼
                   ┌─────────────────────┐
                   │     planning        │ ← content-planner (5项选择)
                   └─────────┬───────────┘
                             │ 用户确认方案
                             ▼
                   ┌─────────────────────┐
                   │  planning_design    │ ← content-planner (1.4详细设计+自然语言渲染)
                   └─────────┬───────────┘
                             │ 用户确认设计
                             ▼
                   ┌─────────────────────┐
                   │  generating_ref     │ ← visual-asset-generator (阶段A: 参考板)
                   └─────────┬───────────┘
                             │ 🛑 用户确认参考板
                             ▼
                   ┌─────────────────────┐
                   │  generating_video   │ ← visual-asset-generator (阶段B: 分镜视频)
                   └─────────┬───────────┘
                             │ 🛑 用户确认分镜视频
                             ▼
                   ┌─────────────────────┐
                   │  generating_audio   │ ← audio-narrator (旁白+TTS)
                   └─────────┬───────────┘
                             │ 🛑 用户确认旁白
                             ▼
         ┌────────────────────────────┐
         │        composing           │ ← post-production-composer
         └────────────┬───────────────┘
                      │ 合成完成
                      ▼
         ┌────────────────────────────┐
         │      quality_check         │ ← quality-assurance
         └────────────┬───────────────┘
                      │
              ┌───────┴───────┐
              ▼               ▼
         pass→done      fail→composing(微调) 或 visual/audio(重生成)
```

> 🛑 = 必须等待用户确认，不可自动跳转

## 4. 通用消息格式

所有 Agent 间通信使用以下 JSON 格式：

```json
{
  "message_id": "uuid-v4",
  "timestamp": "ISO8601",
  "from_agent": "agent-id",
  "to_agent": "agent-id",
  "type": "task_request|task_response|status_update|error_report|artifact_ready",

  "payload": {
    "project_id": "uuid-v4",
    "project_dir": "./poetry_video_projects/{name}_{date}/",
    "status": "pending|running|completed|failed|retrying",
    "progress": 0.0,
    "output_artifacts": {},
    "error": null,
    "next_agents": []
  },

  "context": {
    "poem_title": "",
    "poem_author": "",
    "style_id": "",
    "template_id": "",
    "voice_id": ""
  },

  "validation": {
    "passed": true,
    "checks": []
  }
}
```

## 5. 数据契约（Artifact 规范）

### content-planner → 下游

| Artifact | 格式 | 必含字段 |
|----------|------|---------|
| `scenes.json` | 数组 | scene_id, index, module, status, visual_node, audio_node, subtitle_node, timing, metadata, dependencies |
| `narration_segments.json` | 数组 | segment_id, scene_id, text, tts_text, tts_params, estimated_duration, status |
| `design_system.json` | 对象 | version, style_id, visual_identity, color_language, reference_board, quality_gates |
| `timeline.json` | 数组 | scene_id, start, end, duration（Round 1 估算值） |

### visual-asset-generator → 下游

| Artifact | 格式 | 说明 |
|----------|------|------|
| `ref_*.jpg` | 图片文件 | 参考板图片 2-6 张 |
| `scene_*.mp4` | 视频文件 | 分镜视频，数量=scenes数组长度 |
| `scenes.json`（更新） | 同上 | 回写 visual_node.output_path 和 status |

### audio-narrator → 下游

| Artifact | 格式 | 说明 |
|----------|------|------|
| `narration_*.mp3` | 音频文件 | 旁白音频，数量=narration_segments数组长度 |
| `narration_segments.json`（更新） | 同上 | 回写 actual_duration, audio_path, status |
| `timeline.json`（更新） | 同上 | Round 2 实测校准版 |

### post-production-composer → 下游

| Artifact | 格式 | 说明 |
|----------|------|------|
| `output/final_video.mp4` | 视频文件 | 带字幕的最终成品 |

### quality-assurance → 下游

| Artifact | 格式 | 说明 |
|----------|------|------|
| `qa_report.json` | 对象 | pass/fail + issues列表 + 修复建议 |

## 6. 异常路由规则

```
Agent 失败 → orchestrator 接收 error_report
  ├── 可重试错误 → 同 Agent 重试（最多 3 次）
  ├── 需降级错误 → 切换到降级策略继续
  └── 致命错误 → 终止流程，报告用户

各 Agent 降级链路：
  visual-asset-generator: retry×3 → 简化prompt → 减少参考图 → 仅环境I2V → Ken Burns静态图 → 标记failed
  audio-narrator: retry×2 → 去掉emotion → 切换voice_id → 标记failed
  content-planner: 校验不通过 → 自动精简 → 重新校验 → 最多3次
  post-production-composer: retry×2 → 跳过失败scene → 合并剩余
  quality-assurance: 偏差>1s → 标记重新生成；偏差0.5-1s → 标记微调
```

## 7. 进度上报规范

orchestrator 定期向用户汇报进度，格式：

```
🎬 古诗词视频生成进度
━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1 内容策划    ████████████ 100%  方案已确认
Phase 2 视觉素材    ██████░░░░░░  50%  2/4 分镜已生成
Phase 2 音频旁白    ████████████ 100%  旁白已完成
Phase 3 后期合成    ░░░░░░░░░░░░   0%  等待素材
Phase 3 质量验证    ░░░░░░░░░░░░   0%
```

## 8. Agent 数据迁移指南

当已有项目数据来自旧版生成流程，需要迁移到新 Agent 协议时，按本章操作。

### 8.1 迁移触发条件

检查以下信号，任一命中即需迁移：

```
□ scenes.json 中 visual_node.output_path 为 null
□ narration_segments.json 中 emotion 不统一（同一首诗混用多种 emotion）
□ design_system.json 缺少 reference_board 字段
□ design_system.json 缺少 negative_prompt_template 或行数 < 10
□ timeline.json 中仍有 "round": 1 标记
□ timeline.json 中 durations 全为估算值（无 actual_duration 回写）
```

### 8.2 迁移步骤（按优先级）

**P0（必须修复，否则下游 Agent 拒绝执行）：**

| 步骤 | 目标文件 | 操作 | 说明 |
|------|---------|------|------|
| M1 | `narration_segments.json` | 统一 emotion 为 `calm` | 所有 segment 的 `tts_params.emotion` 改为 `"calm"` |
| M2 | `narration_segments.json` | 移除禁用标记 | 删除 tts_text 中的 `(chuckle)` `(breath)` `(gasps)` `(sighs)` |
| M3 | `narration_segments.json` | 更换标准 voice_id | 非标准音色 → 查阅 §5.2 标准音色表映射 |
| M4 | `design_system.json` | 补全 reference_board | 至少 2 subjects（1 character + 1 environment），含完整 profile |
| M5 | `design_system.json` | 补全 negative_prompt_template | 通用 34 行 + 风格专属负向约束 |
| M6 | `scenes.json` | 重新选 template | 分镜数与时长匹配：short≤3镜/20s, classic≤7镜/105s |

**P1（建议修复，提升质量）：**

| 步骤 | 目标文件 | 操作 | 说明 |
|------|---------|------|------|
| M7 | `timeline.json` | 标记为 Round 1 | 添加 `"round": 1` 字段，表示尚未实测校准 |
| M8 | `design_system.json` | 补全 style_prefix | 从 style-presets.md 提取对应风格的 prefix |
| M9 | `scenes.json` | 补全 visual_node.reference_subjects | 关联到 reference_board 中对应的 subject ID |
| M10 | `scenes.json` | 补全 poem_type/dynasty/background | Phase 0 解析元信息 |

### 8.3 迁移后的校验清单

迁移完成后，逐 Agent 验证：

```
content-planner:
  □ 校验清单 14 项全部通过
  □ 模板与分镜数匹配
  □ reference_board 结构完整

audio-narrator:
  □ emotion 全诗统一
  □ 无禁用标记
  □ voice_id 在标准表中

visual-asset-generator:
  □ Step 0 前置检查 8 项全部通过
  □ negative_prompt_template 完整

post-production-composer:
  □ 素材完整性预检 5 项全部通过
```

### 8.4 迁移示例：江城子·密州出猎

| 修复项 | 旧值 | 新值 |
|--------|------|------|
| template | short | classic（6镜 ≈ 60s 适配） |
| emotion | calm/surprised 混用 | calm（统一） |
| voice_id | male-qn-jingying | Chinese_radio_host_male_vv1 |
| reference_board | 缺失 | 补 1 character + 2 environment |
| negative_prompt | 1行 | 34行通用 + fantasy-ancient 专属 |
| dynasty | — | 宋 |
| poem_type | — | 豪放 |
```

