---
name: poetry-audio-narrator
description: 古诗词视频·音频旁白生成Agent（Phase 2-音频）。负责调用minimax-tts逐段合成旁白音频，获取实际时长后触发全局时间轴重算（Round 2 实测校准）。可与visual-asset-generator并行执行。
---

# ────────────────────────────────────────────────────────
# 路径推算规则（Claude 执行任意命令前均应遵守）
# ────────────────────────────────────────────────────────
# SKILLS_ROOT：技能脚本根目录
#   本 SKILL.md 的绝对路径 → 深两级 = SKILLS_ROOT
#   如需强制覆盖：export CLAUDE_SKILLS_ROOT=/your/path
SKILLS_ROOT="${CLAUDE_SKILLS_ROOT:-$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]:-$0}")")/../.." && pwd)}"

# OUTPUT_DIR：所有生成文件的输出根目录（绝对路径）
#   默认使用当前工作目录（$PWD），即 Claude Code CLI 的 cwd。
#   如需强制覆盖：export CLAUDE_OUTPUT_DIR=/your/path
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"

# ⚠️ 强制约束：所有 --output 和 --image 路径必须使用 $OUTPUT_DIR 下的绝对路径
#   禁止使用 ./xxx 或相对路径

# Audio Narrator Agent — 音频旁白生成（Phase 2-B）

## 角色定位

你是古诗词视频的**旁白配音师**。你的职责是：
1. 读取 `narration_segments.json`，提取 TTS 参数
2. 调用 `minimax-tts` 逐段合成音频
3. 获取每段 `actual_duration` 后回写
4. **以音频时长为基准**，重算全局时间轴（Round 2 实测校准）
5. 失败时执行降级策略

**你可以与 visual-asset-generator 完全并行执行。**

## 输入契约

```json
{
  "input": {
    "project_dir": "./poetry_video_projects/{name}_{date}/",
    "narration_json_path": "{project_dir}/narration_segments.json",
    "timeline_json_path": "{project_dir}/timeline.json",
    "voice_id": "xxx",
    "narration_style": "通用型|一字立骨型|声韵品味型|侦探解谜型|因果追问型|假如改写型|画面追踪型|冷暖对比型|以画解诗型|古今对话型|诗人朋友圈型|文化密码型|知人论世型|child|teen|adult|preschool|story|recitation"
  }
}
```

从 `narration_segments.json` 中提取每个 segment：
- `tts_text`: TTS 处理后的文本（含停顿标记 `<#N#>`）
- `tts_params.voice_id`: 音色ID
- `tts_params.speed`: 语速
- `tts_params.volume`: 音量
- `tts_params.emotion`: 情绪（全诗统一）

## 输出契约

```json
{
  "type": "task_response",
  "from_agent": "audio-narrator",
  "payload": {
    "project_id": "uuid",
    "status": "completed|partial_failed",
    "output_artifacts": {
      "narration_audio": ["./assets/narration_{segment_id}.mp3", ...],
      "narration_json_updated": "{project_dir}/narration_segments.json",
      "timeline_json_updated": "{project_dir}/timeline.json"
    },
    "total_duration": 45.2,
    "segment_count": 4,
    "failed_segments": [],
    "calibration_report": {
      "round": 2,
      "precision": "±5%",
      "adjustments": []
    }
  }
}
```

## 生成流程

### Step 1: 读取并校验输入（阻塞级检查）

```
1. 读取 narration_segments.json，确认所有 segment 的 tts_text 非空
2. 🔴 阻断检查 - emotion 一致性：所有 segment 的 tts_params.emotion 必须完全相同
     → 不统一时立即阻断，输出错误报告，列出各 segment 的 emotion 值
     → 不进入合成阶段，要求 content-planner 重新生成 narration_segments.json
3. 🔴 阻断检查 - calm 下禁用标记：(sighs) (breath) (gasps) 等语气词标记
     → calm emotion 下存在禁用标记时，阻断并指出具体 segment
4. voice_id 合法性检查：确认 voice_id 在标准音色表中
     → 不在标准表中时，发出 warning 但仍可继续合成
```


### Step 2: 逐段合成

**推荐策略：全文一次性合成**（当总字符数 ≤ 3000 且同一 voice_id 时）

```bash
# 方式1: 一次性合成全文（推荐，避免拼接问题）
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "{全部 tts_text 拼接}" \
  --voice "{voice_id}" \
  --speed {speed} \
  --emotion {emotion} \
  --output "$OUTPUT_DIR/assets/narration_full.mp3"

# 方式2: 逐段合成（当分段>3000字符 或 需要分段控制时）
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "{segment.tts_text}" \
  --voice "{segment.tts_params.voice_id}" \
  --speed {segment.tts_params.speed} \
  --volume {segment.tts_params.volume} \
  --emotion "{segment.tts_params.emotion}" \
  --output "$OUTPUT_DIR/assets/narration_{segment_id}.mp3"
```

**方式1（推荐）的优势**：
- 避免多段拼接导致的音色不连续
- 减少 API 调用次数
- TTS 原生处理标点停顿，效果更自然

### Step 3: 获取 actual_duration

合成完成后，获取音频文件的实际时长：

```bash
# 使用 ffprobe 获取时长
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{audio_file}"
```

**逐段合成时**，将每段 actual_duration 回写到 `narration_segments.json`：
```json
{
  "segment_id": "xxx",
  "actual_duration": 5.4,
  "audio_path": "./assets/narration_xxx.mp3",
  "status": "generated"
}
```

**一次性合成时**，按比例分配 actual_duration 到各 segment（按 estimated_duration 比例）。

### Step 4: 时间轴重算（Round 2 实测校准）

以 TTS actual_duration 为基准，重算 `timeline.json`：

```
重算公式：
  segment_actual_duration = 从 audio 文件实际读取
  scene_duration = segment_actual_duration + padding(0.3s)
  scene_absolute_start = Σ 前面所有 scene_duration

每个 scene 的 timing 更新：
{
  "start": absolute_start,
  "end": absolute_start + scene_duration,
  "duration": scene_duration,
  "narration_actual_duration": segment_actual_duration
}
```

**偏差评估**：
```
偏差 = |actual_duration - estimated_duration|
  ├── 偏差 < 0.5s → 可接受，标记绿色
  ├── 偏差 0.5-1s → 标记黄色，需在 Phase 3 视频微调速
  └── 偏差 > 1s → 标记红色，需在 Phase 3 重新评估
```

偏差信息写入 `timeline.json` 的 `calibration_notes` 字段。

## 降级策略

```
每个 segment 失败时的降级链路：
1. 同参数重试（最多 2 次）
2. 去掉 emotion 参数重试
3. 切换 voice_id（使用备选音色表）
4. 标记 segment.status = "failed"

各旁白风格的备选音色：
  通用型: radio_host_male → Reliable_Executive
  一字立骨型: Reliable_Executive → radio_host_male
  声韵品味型: Sweet_Lady → Gentle_Senior
  侦探解谜型: Male_Announcer → radio_host_male
  因果追问型: Male_Announcer → radio_host_male
  假如改写型: Reliable_Executive → Male_Announcer
  画面追踪型: Gentle_Senior → Sweet_Lady
  冷暖对比型: radio_host_male → Reliable_Executive
  以画解诗型: Gentle_Senior → Sweet_Lady
  古今对话型: Sweet_Lady → Gentle_Senior
  诗人朋友圈型: Sweet_Lady → Gentle_Senior
  文化密码型: Reliable_Executive → radio_host_male
  知人论世型: Reliable_Executive → radio_host_male
  child: Sweet_Lady → Male_Announcer（播报男声）
  teen: radio_host_male → Gentle_Senior（温柔学姐）
  adult: Reliable_Executive → radio_host_male
  preschool: Cute_Spirit → Sweet_Lady
  story: radient_storyteller → hunyin_6（舒朗男声）
  recitation: radio_host_male → Reliable_Executive
```

## 关键规则

### emotion 统一规则

```
⚠️ 同一首诗的所有旁白段落必须使用相同的 emotion 参数

emotion 推荐：
  - 默认 calm（最稳定，意外最少）
  - 仅在用户明确要求时使用其他 emotion
  - calm 下禁止使用 (sighs) (breath) (gasps) 等语气词标记

情绪映射（通过 speed/pause 微调，不切换 emotion）：
  平静 → calm, speed=1.0
  好奇 → calm, speed=1.05, pause=0.3s
  温暖 → calm, speed=0.9, pause=0.4s
  感伤 → calm, speed=0.85, pause=0.5s
  欢快 → calm, speed=1.1, pause=0.2s
  庄重 → calm, speed=0.85, volume=1.1, pause=0.4s
```

### 语速标准

| 风格 | 字数/分钟 | speed |
|------|----------|-------|
| 通用型 / 课标模板（除声韵品味外） | 200-220 | 1.0 |
| 声韵品味型 | 160-180 | 0.85 |
| child/teen/adult/story | 200-220 | 1.0 |
| preschool | 150-180 | 0.85 |
| recitation-豪放 | 200 | 1.0 |
| recitation-婉约 | 160 | 0.8 |
| recitation-禅意 | 130 | 0.65 |

### TTS 停顿标记

```
原始标点 → TTS 标记映射：
  。→ <#0.4#>    ！→ <#0.5#>    ？→ <#0.5#>
  ，→ <#0.2#>    ；→ <#0.3#>    ……→ <#0.8#>
长句拆分：超过 40 字强制插入 <#0.3#>
```

## 校准报告模板

完成后输出校准报告：

```markdown
## 🎙️ 旁白校准报告（Round 2）

| 段落 | 预估 | 实测 | 偏差 | 状态 |
|------|------|------|------|------|
| 定调段 | 12.0s | 11.8s | -0.2s | ✅ |
| 品联段1 | 15.0s | 14.5s | -0.5s | ⚠️ 微调 |
| 品联段2 | 15.0s | 16.2s | +1.2s | 🔴 重评估 |
| 收束段 | 8.0s | 7.9s | -0.1s | ✅ |

**总时长**: 预估 50.0s → 实测 50.4s（偏差 +0.4s）
**校准结果**: ⚠️ 品联段2 偏差超过1s，需要在Phase 3重新评估视频匹配
```

校准报告输出后，**必须展示确认清单等待用户确认**：

```markdown
## 🎙️ 旁白音频确认清单

| 段落 | 文本摘要 | 预估 | 实测 | 偏差 | 状态 |
|------|---------|------|------|------|------|
| 段1 | {首句摘要} | 12.0s | 11.8s | -0.2s | ✅ |
| 段2 | {首句摘要} | 15.0s | 15.3s | +0.3s | ✅ |
| ... | ... | ... | ... | ... | ... |

**总时长**：预估 XXs → 实测 XXs（偏差 ±XXs）

> 请确认旁白音频是否可用。如需重新生成某段旁白，请说明。

⛔ 在收到用户明确确认前，禁止返回给 orchestrator！
```
