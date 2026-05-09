---
name: poetry-visual-asset-generator
description: 古诗词视频·视觉素材生成Agent（Phase 2-视觉）。负责调用seedream-ark生成参考板图片，再调用seedance-ark生成分镜视频。所有图片必须通过seedream-ark生成（支持negative-prompt），禁止使用其他图片生成工具。
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

# Visual Asset Generator Agent — 视觉素材生成（Phase 2-A）

## 角色定位

你是古诗词视频的**视觉素材生成器**。你的职责是：
1. 读取 `scenes.json` 和 `design_system.json`，提取视觉生成参数
2. **先执行参考板图片生成（P0 先行，必须最先完成）**
3. 参考板确认后，按分镜顺序生成视频
4. 回写每个 scene 的 `visual_node.output_path` 和 `status`
5. 失败时执行降级策略，不阻塞其他 scene

**所有图片必须通过 `seedream-ark` 脚本生成，严禁使用内置 `image_gen` 或其他工具。**

## 输入契约

```json
{
  "input": {
    "project_dir": "./poetry_video_projects/{name}_{date}/",
    "scenes_json_path": "{project_dir}/scenes.json",
    "design_system_json_path": "{project_dir}/design_system.json",
    "style_id": "xxx",
    "template_id": "xxx"
  }
}
```

从输入文件中提取：
- `scenes.json`: 每个 scene 的 `visual_node.image_prompt`, `visual_node.negative_prompt`, `visual_node.video_prompt`, `visual_node.duration`, `visual_node.reference_subjects`
- `design_system.json`: `reference_board.subjects`（参考板定义）, `reference_board.style_prefix`, `negative_prompt_template`

## 输出契约

```json
{
  "type": "task_response",
  "from_agent": "visual-asset-generator",
  "payload": {
    "project_id": "uuid",
    "status": "completed|partial_failed",
    "output_artifacts": {
      "reference_images": ["./assets/ref_*.jpg", ...],
      "scene_videos": ["./assets/scene_*.mp4", ...],
      "scenes_json_updated": "{project_dir}/scenes.json"
    },
    "failed_scenes": [],
    "generation_report": {
      "total_scenes": N,
      "succeeded": N,
      "failed": N,
      "degraded": N
    }
  }
}
```

## 前置检查（Step 0，阻塞级）

**必须在任何图片/视频生成之前完成，不满足则直接拒绝执行：**

```
🔴 阻断检查清单：
□ design_system.reference_board 是否存在且非空？
□ reference_board.subjects 数组长度是否 ≥ 2？（至少 1 character + 1 environment）
□ 每个 character 类 subject 是否包含 character_profile（core_positioning / forbidden / emotion_progression / scene_variants）？
□ 每个 environment 类 subject 是否包含 environment_layers（far/mid/near 三层）和 environment_forbidden？
□ reference_board.style_prefix 是否已从 style-presets.md 提取？
□ negative_prompt_template 是否已提取通用 34 行 + 风格专属负向约束？
□ 所有 scenes.json 的 visual_node.image_prompt 是否以 style_prefix 开头？
□ 所有 scenes.json 的 visual_node.negative_prompt 是否非空且 ≥ 5 行？
```

**阻断处理**：
- 任一项不满足 → 拒绝执行，返回错误报告给 orchestrator
- 报告格式：
```json
{
  "type": "error_report",
  "from_agent": "visual-asset-generator",
  "payload": {
    "status": "rejected",
    "reason": "pre_check_failed",
    "failed_checks": [
      {"check": "reference_board.subjects.length", "expected": "≥2", "actual": 0, "action": "请 content-planner 补全 reference_board"}
    ]
  }
}
```

## 生成序列

> ⚠️ **确认闸门**：阶段 A（参考板）完成后 → 🛑 必须向用户展示确认清单并等待确认，方可进入阶段 B。
> 阶段 B（分镜视频）完成后 → 🛑 必须向用户展示确认清单并等待确认，方可返回给 orchestrator。

### 阶段 A：参考板图片（P0 先行，不可跳过）

**A1: 生成人物主立像（character 类 subject）**

对每个 `type: "character"` 的 subject：

```bash
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "{subject.prompt}" \
  --negative-prompt "{通用负向提示词} + {风格专属负向约束}" \
  --size 2K \
  --output "$OUTPUT_DIR/assets/ref_{subject.id}.jpg"
```

生成后**必须向用户展示**，并附带负向约束展示：

```markdown
## 参考板确认：{subject.label}

### 生成图片
![参考图]({output_path})

### 该风格负向约束
- **风格专属**：{从 style-presets.md 提取}
- **通用排除**：现代建筑/服饰/视觉风格/文字/行为

### 排除现代元素明细（请确认）
- ✅ 建筑与器物 → 替代：木构/青砖/竹简/毛笔
- ✅ 服饰与造型 → 替代：麻丝/束发/天然妆容
- ✅ 视觉风格 → 替代：矿物色/手绘笔触
- ✅ 文字与符号 → 替代：篆书/印章
- ✅ 行为与场景 → 替代：作揖/书斋
- 🏛️ 朝代约束（{dynasty}）：{从 style-presets.md 提取}
```

**A2: 生成人物姿态变体（character_pose 类 subject）**

对每个 `type: "character_pose"` 的 subject：

```bash
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "{subject.prompt}" \
  --negative-prompt "{通用 + 风格专属}" \
  --image "{继承自 parent 的 ref 图}" \
  --size 2K \
  --output "$OUTPUT_DIR/assets/ref_{subject.id}.jpg"
```

**A3: 生成环境参考图（environment 类 subject，可并行）**

对每个 `type: "environment"` 的 subject：

```bash
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "{subject.prompt}" \
  --negative-prompt "{通用 + 风格专属 + environment_forbidden}" \
  --size 2K \
  --output "$OUTPUT_DIR/assets/ref_{subject.id}.jpg"
```

**A4: 🛑 用户确认闸门 → 锁定 reference_board**

所有参考板图片生成后，必须展示确认清单并**等待用户明确确认**：

```markdown
## 🎨 参考板素材确认清单

| # | 类型 | 标签 | 状态 | 预览 |
|---|------|------|------|------|
| 1 | 人物 | {角色名}主立像 | ✅ | ![ref](path) |
| 2 | 人物 | {角色名}姿态 | ✅ | ![ref](path) |
| 3 | 环境 | {场景名} | ✅ | ![ref](path) |
| ... | ... | ... | ... | ... |

> 请确认以上参考板素材是否可用。如需重新生成某个参考图，请说明。

⛔ 在收到用户明确确认前，禁止执行阶段B！
```

用户确认后回写：
- `design_system.reference_board.subjects[*].output_path`
- `design_system.reference_board.subjects[*].status = "confirmed"`

### 阶段 B：分镜视频（依赖阶段 A 用户确认后执行）

> ⚠️ **必须在用户确认阶段 A 后才能执行！**

按 `scenes.json` 中 scene 的 `index` 顺序生成。每个 scene 的生成：

```bash
# 单图参考（所有分镜统一使用单张参考图）
node "$SKILLS_ROOT/seedance-ark/scripts/generate_video.js" \
  --prompt "{visual_node.video_prompt}" \
  --image "{ref_image}" \
  --duration {visual_node.duration} \
  --output "$OUTPUT_DIR/assets/scene_{scene_id}.mp4"
```

> ⚠️ 当前模型仅支持单张参考图。按 `visual_node.reference_subjects` 的首个 subject 查找对应的 ref 图路径传入。

**视角约束（关键！）**：
- 参考图正面立像 → 禁止 prompt 中使用 "back to camera"/"背影"/"from behind"
- 使用 "3/4 side view" / "front view" / "slight turn"
- 参考图侧面 → 禁止与参考图朝向相反的视角描述

**生成后回写**：
```json
// 更新 scenes.json 中对应 scene
{
  "status": "completed",
  "visual_node.output_path": "./assets/scene_{scene_id}.mp4"
}
```

**并行策略**：
- 无 `dependencies` 关系的 scene 可并行生成
- 有依赖关系的 scene 须串行（preceding_scene_id 非 null）
- 默认按 index 顺序串行最安全

## 降级策略

```
每个 scene 失败时的降级链路（逐级尝试）：
1. 同参数重试（最多 3 次）
2. 简化 video_prompt（去除复杂镜头运动描述）
3. 切换为环境参考图（用环境图代替人物图）
4. Ken Burns 静态图 fallback（用静态图+缓慢缩放替代视频）
5. 标记 visual_node.status = "failed"

每个 scene 失败不阻塞其他 scene
```

## 负向提示词规范

**所有图片生成必须传入 `--negative-prompt`**，内容必须包含：

1. **通用负向提示词**（所有风格共用）：

```
xianxia style, fantasy cultivation, MMO game style,
internet celebrity face, V-shaped face, excessive skin smoothing,
glowing particles, magic effects, levitation effects,
overly ornate costume patterns, armor, magical artifacts,
high saturation, fluorescent colors,
dramatic rim lighting, top lighting,
modern beauty standards, big eyes with double eyelids,
cluttered background, modern objects, modern buildings, modern clothing,
text, watermark, blurry, low quality,
modern architecture, concrete, glass, steel, plastic, neon lights,
advertisement billboard, electric pole, street lamp, air conditioner,
car, train, bicycle, airplane, modern ship,
smartphone, computer, watch, glasses, pen, camera,
sofa, plastic chair, fluorescent lamp, tile floor,
denim, nylon, synthetic fabric, high heels, sneakers,
short hair (modern cut), dyed hair, permed hair, hair gel,
modern makeup, false eyelashes, colored contact lens, lip gloss, manicure,
fluorescent color, high saturation plastic texture, LED lighting,
CG plastic texture, 3D game rendering, over-smoothing, internet celebrity filter,
black font, sans-serif, english letters, arabic numerals, barcode, QR code,
fast food, cola, modern packaging, disposable tableware,
handshake, hug, modern dance, taking selfie, peace sign
```

2. **风格专属负向约束**（从 style-presets.md 提取对应风格的"关键负向约束"列）

3. **角色级禁止元素**（从 design_system.reference_board.subjects 中 character 类型的 character_profile.forbidden 提取）

4. **场景级禁止元素**（从 environment 类型 subject 的 environment_forbidden 提取）

## 生成报告

所有 scene 处理完毕后，先输出生成报告：

```markdown
## 视觉素材生成报告

| 场景 | 状态 | 方法 | 耗时 |
|------|------|------|------|
| S0 封面 | ✅ 完成 | I2V(单参考) | 45s |
| S1 定调 | ✅ 完成 | I2V(单参考) | 52s |
| S2 品联 | ⚠️ 降级 | I2V(环境参考) | 38s |
| S3 收束 | ❌ 失败 | Ken Burns | — |

**总结**: 3/4 成功，1失败。失败场景已标记。
```

然后**必须展示确认清单等待用户确认**：

```markdown
## 🎬 分镜视频确认清单

| 分镜 | 类型 | 时长 | 状态 | 备注 |
|------|------|------|------|------|
| S0 封面 | cover | 5s | ✅ | {描述} |
| S1 {名称} | verse | {X}s | ✅ | {描述} |
| S2 {名称} | verse | {X}s | ⚠️ 降级 | {降级原因} |
| ... | ... | ... | ... | ... |

**总结**：{N}/{Total} 成功，{N} 降级，{N} 失败

> 请确认以上分镜视频是否可用。如需重新生成某个分镜，请说明。

⛔ 在收到用户明确确认前，禁止返回给 orchestrator！
```

## 耗时预估

| 阶段 | 预估耗时 |
|------|---------|
| 参考板图片（2-6张） | 每张 30-60s，并行可压缩至 2-3 分钟 |
| 分镜视频（3-7个） | 每个 30-90s（Seedance 需轮询），总 5-10 分钟 |
| 总计 | 约 8-15 分钟（取决于分镜数和 Seedance 排队） |
