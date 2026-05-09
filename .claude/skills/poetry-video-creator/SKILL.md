---
name: poetry-video-creator
description: 古诗词视频创作工作流。将古诗词原文转化为完整视频作品（分镜脚本+参考板+旁白+合成）。触发词：古诗词视频、生成视频、做分镜、写旁白、诗词赏析视频。协调调用 Seedream(图片)、Seedance(视频)、MiniMax-TTS(语音)、FFmpeg(合成) 完成全流程。
---

# ────────────────────────────────────────────────────────
# 路径推算规则（Claude 执行任意命令前均应遵守）
# ────────────────────────────────────────────────────────
# SKILLS_ROOT：技能脚本根目录
#   本 SKILL.md 的绝对路径 → 取父目录(poetry-video-creator) → 再取上级 = SKILLS_ROOT
#   如需强制覆盖：export CLAUDE_SKILLS_ROOT=/your/path
SKILLS_ROOT="${CLAUDE_SKILLS_ROOT:-$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]:-$0}")")/.." && pwd)}"

# OUTPUT_DIR：所有生成文件的输出根目录（绝对路径）
#   优先级：CLAUDE_OUTPUT_DIR 环境变量 > $PWD
#   ⚠️ Claude 执行命令前必须先运行以下命令确认实际路径：
#      OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
#   ⚠️ 所有 --output 和 --image 路径必须使用 $OUTPUT_DIR 下的绝对路径
#   禁止使用 ./xxx 或相对路径，否则文件会落在 Node 进程的 cwd 而非会话目录

# OUTPUT_BASE_URL：生成文件在前端的展示域名（用于生成可访问的 URL）
#   配置方式：export CLAUDE_OUTPUT_BASE_URL=http://118.195.240.72:62031/files/ccsdk
#   规则：末尾不含斜杠；DISPLAY_URL = BASE_URL + 文件相对于 OUTPUT_DIR 的子路径

# ⚠️ 强制输出规范：每次生成文件后，Claude 必须紧接着执行以下 bash 命令来计算并打印展示 URL，
#   然后将打印结果作为 Markdown 输出给用户（图片用 ![]() 语法，视频/音频用 []() 链接）。
#   将 FILE_PATH 替换为实际生成的文件绝对路径后执行：
#
#   FILE_PATH="/actual/generated/file.jpg"
#   OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
#   BASE_URL="${CLAUDE_OUTPUT_BASE_URL:-}"
#   REL="${FILE_PATH#$OUTPUT_DIR}"
#   if [ -n "$BASE_URL" ]; then echo "${BASE_URL}${REL}"; else echo "$FILE_PATH"; fi
#
# 🚫 严格禁止：
#   - 禁止跳过上述 bash 命令、直接在回复里自行拼接或猜测 URL
#   - 禁止使用任何非 CLAUDE_OUTPUT_BASE_URL 来源的域名（含 r2.aityp.com 等）
#
# 命令示例（每次执行前先设置 OUTPUT_DIR）：
# OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
# 图片: node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" --prompt "..." --negative-prompt "..." --output "$OUTPUT_DIR/assets/ref.jpg"
# 视频: node "$SKILLS_ROOT/seedance-ark/scripts/generate_video.js" --prompt "..." --image "$OUTPUT_DIR/assets/ref.jpg" --duration 5 --output "$OUTPUT_DIR/assets/scene.mp4"
# 语音: node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" --text "..." --voice "xxx" --output "$OUTPUT_DIR/assets/narr.mp3"
# 合成: node "$SKILLS_ROOT/ffmpeg-cli/scripts/merge_av.js" --video "$OUTPUT_DIR/assets/v.mp4" --audio "$OUTPUT_DIR/assets/a.mp3" --output "$OUTPUT_DIR/output/final.mp4"

# Poetry Video Creator

## 核心原则

1. **音频时长为基准**：时间轴以 TTS 实际输出 `actual_duration` 为准，视频时长跟随音频
2. **参考板锚定**：先确认 reference_board，所有场景使用 I2V 模式传入参考图
3. **视角一致**：视频 prompt 人物视角必须与参考图一致（正面图→禁止背影描述）
4. **情绪统一**：同一首诗所有旁白使用同一 emotion（默认 calm），禁用 sighs/breath
5. **字幕优先诗句**：视频字幕优先显示诗句原文，支持用户按需调整内容

## 依赖技能

| 职责 | 技能 | 关键脚本 |
|------|------|---------|
| 图片生成 | `seedream-ark` | `scripts/generate_image.js` |
| 视频生成 | `seedance-ark` | `scripts/generate_video.js` |
| 语音合成 | `minimax-tts` | `scripts/synthesize.js` |
| 视频编辑 | `ffmpeg-cli` | `scripts/merge_av.js` 等 |

> ⚠️ **强制约束：所有图片必须通过 `seedream-ark` 生成，禁止使用内置 image_gen 或其他图片生成工具！**
> 原因：seedream-ark 支持 `--negative-prompt` 负向提示词，这是控制画风、排除仙侠/现代元素的核心手段，其他工具无法替代。
> 每次生成图片时，必须先 `use_skill seedream-ark` 加载技能，然后调用 `generate_image.js` 并传入 `--negative-prompt`。

## 路径配置

**项目根目录**（SKILLS_ROOT）由本 SKILL.md 文件路径推算。

```
# 各工具路径（相对于 SKILLS_ROOT）：
# 图片: $SKILLS_ROOT/seedream-ark/scripts/generate_image.js
# 视频: $SKILLS_ROOT/seedance-ark/scripts/generate_video.js
# 语音: $SKILLS_ROOT/minimax-tts/scripts/synthesize.js
# 合成: $SKILLS_ROOT/ffmpeg-cli/scripts/*.js
```

> ⚠️ 所有视频/音频编辑通过 ffmpeg-cli 脚本执行，不直接调用 ffmpeg 底层命令。

---

## 工作流程

```
Phase 1: 内容策划
  1.1 诗词解析 → 1.2 智能分析+用户选择(5项含字幕) → 1.3 策划方案 → 1.4 详细设计(+自然语言渲染)
  ↓ 用户确认锁定
Phase 2: 素材生成
  2.1 参考板图片 → 🛑用户确认 →
  2.2 分镜视频   → 🛑用户确认 →
  2.3 旁白音频   → 🛑用户确认 →
  ↓ 全部确认后
Phase 3: 后期合成
  时间轴校准 → 逐镜合成 → 全片合并 → 字幕烧录 → 质量验证
```

> 🛑 = 必须等待用户确认才能继续下一步

---

## Phase 1: 内容策划

### 1.1 诗词解析

识别标题、作者、朝代、诗句、诗词类型（送别/山水/边塞/田园/闺怨/咏物/叙事等）。输出格式：

```json
{ "title": "", "author": "", "dynasty": "", "original_text": [], "line_count": 0, "poem_type": "", "background": "" }
```

### 1.2 智能分析 + 用户选择

根据诗词内容智能分析，**使用 `ask_followup_question` 弹窗**让用户选择4项配置，并给出推荐：

```
分析逻辑：
  1. 根据 poem_type 推荐视觉风格预设（见下方推荐映射）
  2. 根据 poem_type + line_count 推荐分镜模板
  3. 根据 poem_type + 受众推断推荐旁白音色
  4. 根据 line_count + 受众推断推荐时长档位

推荐映射：
  山水田园 → traditional-ink / watercolor
  送别思乡 → watercolor / fantasy-ancient
  边塞豪放 → fantasy-ancient / new-chinese
  闺怨婉约 → watercolor / gongbi
  咏物哲理 → new-chinese / traditional-ink
  叙事长诗 → fantasy-ancient / gongbi
  童趣写景 → ghibli-ink

分镜推荐：
  叙事长诗 → story
  送别思乡 → immersive（或 classic）
  哲理/问答 → explore
  短诗/社交媒体 → short
  默认 → general（新课标通用三段式）
```

弹窗包含5个问题（单选）：
1. **视觉风格预设**：列出6种风格，标注推荐项
2. **分镜模板**：列出6种模板+2种送别子类型（含general通用三段式），标注推荐项
3. **旁白风格+音色**：提供两级选择，默认优先推荐新课标模板（通用型/一字立骨型等13种），无法匹配时降级为年龄风格（child/teen等6种），每种标注推荐音色、标注推荐项
4. **时长控制**：列出各分镜模板的时长上限（见storyboard-templates.md），标注推荐项
5. **字幕显示方式**：选择字幕呈现模式（见下表）

**Q5 字幕显示方式：**

| 选项 | 说明 | 字幕内容示例 | 适用场景 |
|------|------|------------|---------|
| `verse-only` | 仅诗句原文（默认推荐） | "床前明月光" | 纯赏析、诵读 |
| `verse-title` | 诗句 + 标题概述 | "静夜思\n床前明月光" | 教学场景 |
| `verse-bilingual` | 诗句 + 英文翻译 | "床前明月光\nMoonlight before my bed" | 海外传播 |
| `minimal` | 极简模式（仅首句） | "静夜思 — 李白" | 短视频/沉浸式 |

> 详见 [references/style-presets.md](references/style-presets.md)

### 1.3 内容策划方案

用户选定后，输出内容策划方案让用户确认：

```markdown
# 内容策划方案：{诗词标题}

## 诗词内容
- **原文**：{逐句列出}
- **作者**：{朝代}·{作者}
- **来源**：{出处/诗集}
- **背景**：{创作背景简述}
- **诗词类型**：{送别/山水/边塞/...}

## 视觉风格预设
- **已选模板**：{style_id} — {风格名称}
- **核心描述**：{从style-presets.md提取}
- **色彩基调**：{从style-presets.md提取}

## 分镜模板
- **已选模板**：{template_id} — {模板名称}
- **分镜结构**：S1(景别+运动|氛围) → S2(...) → ... → Sn(...)
- **特殊规则**：{如送别类需标注"含离去者分镜"}

## 旁白风格模板
- **已选风格**：{风格ID} — {风格名称}（课标模板或年龄风格，参考narration_styles.md）
- **已选音色**：{voice_id}
- **节奏**：{3-4段，从narration_styles.md提取对应模板段落结构}
- **基准语速**：200-220字/分钟（preschool略慢，recitation按类型调整）
- **旁白字数上限**：{从narration_styles.md联动表提取}

## 时长控制
- **目标分镜模板**：{template_id}（上限{XX}s）
- **预估总时长**：{XX-XX秒}

## 字幕显示方式
- **已选模式**：{subtitle_mode} — {说明}
```

用户确认后进入1.4详细设计。

### 1.4 详细设计

基于策划方案，生成3份核心设计文件。

> ⚠️ **设计内容渲染规则**：生成为JSON文件后，**必须在对话中额外渲染为自然语言描述的文案脚本**，方便用户直观审阅。不能只输出JSON原文。

**渲染格式要求**：

生成 `scenes.json`、`narration_segments.json`、`design_system.json` 三个JSON文件后，**必须在对话中额外渲染自然语言文案脚本**，格式如下：

---

## 分镜脚本（自然语言版）

按分镜顺序逐镜描述：

> **S0 · 封面**（类型:cover，时长:5s）
> 景别：远景 | 运动：固定 | 氛围：空灵
> 画面：烟波浩渺的江面上，一叶孤舟渐行渐远，远处青山隐在薄雾中
> 字幕：「{标题} — {作者}·{朝代}」

> **S1 · 起句**（类型:verse，时长:10s）
> 景别：中景 | 运动：推 | 氛围：惆怅
> 画面：江岸边柳枝摇曳，诗人立于岸边，目送远方
> 旁白：{旁白文案}
> 字幕：「{诗句原文}」

> **S2 · 承句**...（依此类推）

> **SN · 收束**（类型:outro，时长:5s）
> 景别：极远景 | 运动：拉 | 氛围：静谧
> 画面：画面渐远，只留空镜山水，浮现终场文字
> 字幕：「感谢观赏」

**分镜统计**：共 X 镜，预估总时长 XXs

---

## 旁白脚本（自然语言版）

逐段展示旁白文案（非TTS标记原文），附带说话节奏说明：

> **旁白段落 1 — 引入**（约 Xs）
> 语气：平静 | 语速：标准 | 停顿：句间 0.4s
> 「{旁白文本——自然语言，不含TTS标记}」
>
> **旁白段落 2 — 解读首联**（约 Xs）
> 语气：好奇 | 语速：稍快 | 停顿：句间 0.3s
> 「{旁白文本}」
>
> ...（逐段展示）
>
> **旁白总字数**：XX字 | **预估总时长**：XXs

---

## 设计语言说明（自然语言版）

> **视觉风格**：{style_name}（{style_id}）
> 风格描述：{一句话风格描述}
> 
> **色彩基调**：
> - 主色调：{primary_colors}
> - 辅色调：{secondary_colors}
>
> **参考板清单**：
> 1. 👤 人物·{角色名} — {core_positioning}
>    - 禁止：{forbidden_elements}
>    - 本诗形象：{current_poem_variant}
> 2. 🌿 环境·{场景名} — {atmosphere}
>    - 空间层次：远景{far} | 中景{mid} | 近景{near}
>    - 禁止：{environment_forbidden}
> ...（每个subject逐项列出）
>
> **构图规则**：{composition_rules，逐条列出}
>
> **字幕模式**：{subtitle_mode} — {说明}

---

JSON 文件的完整字段规范见：

**a) 分镜脚本** `scenes.json` — **详见 [references/storyboard-templates.md](references/storyboard-templates.md)**

按用户选定的模板生成，遵循特殊类型规则：
- **送别类**：必须包含"离去者"分镜
- **叙事类**：按叙事弧线推进，需多个角色 reference_subject

**b) 旁白脚本** `narration_segments.json` — **详见 [references/data-structures.md](references/data-structures.md)**

旁白风格模板详见 [references/narration_styles.md](references/narration_styles.md)，含通用型+11种课标模板+6种年龄风格，默认使用通用型

关键规则：
- **同一首诗所有段落使用同一 emotion**（默认 `calm`，最稳定）
- **calm 情绪下禁用** `(sighs)` `(breath)` `(gasps)` — 会被解读为叹气声
- 每句旁白必须有信息增量，禁止纯情绪填充
- 语速标准：200-220字/分钟

**c) 设计语言** `design_system.json` — **详见 [references/data-structures.md](references/data-structures.md)**

参考板 = 人物类(1-3个) + 环境类(1-3个)，总计2-6个 subject。详见 [references/character_spec.md](references/character_spec.md)。

---

## Phase 2: 素材生成

> ⚠️ **重要：每步完成后必须等待用户确认，才能进入下一步！**

```
Phase 2 执行顺序：
  2.1 参考板图片 → 🛑 用户确认 → 
  2.2 分镜视频   → 🛑 用户确认 → 
  2.3 旁白音频   → 🛑 用户确认 → 
  Phase 3 后期合成
```

### 2.1 参考板图片（P0，最先执行）

```
A1: 生成 character 类（主立像）→ 展示给用户确认（含负向约束明细）
A2: 生成 character_pose 类（基于主立像多图融合，保五官一致）
A3: 生成 environment 类（可并行）
A4: 🛑 用户逐一确认风格一致性 → 锁定 reference_board → 等待用户明确"确认参考板素材可用"
```

**⚠️ 参考板确认时必须展示负向约束：**

生成每张参考板图片后，向用户展示时**同时展示该风格的关键负向约束**和**排除现代元素明细表**（见 [references/style-presets.md](references/style-presets.md)），让用户确认哪些约束需要保留、哪些需要放松或补充。展示格式：

```markdown
## 参考板确认：{subject.label}

### 生成图片
![参考图]({output_path})

### 该风格负向约束
- **风格专属**：{从style-presets.md提取该风格的关键负向约束}
- **通用排除**：见下方明细，请确认是否需要调整

### 排除现代元素明细（请确认）
- ✅ 建筑与器物：钢筋混凝土/玻璃幕墙/手机/汽车等 → 替代：木构/竹简/马车
- ✅ 服饰与造型：牛仔/短发/美瞳等 → 替代：麻丝/束发/天然妆容
- ✅ 视觉风格：荧光色/CG塑料感等 → 替代：矿物色/手绘笔触
- ✅ 文字与符号：英文/二维码等 → 替代：篆书/印章
- ✅ 行为与场景：握手/咖啡厅等 → 替代：作揖/书斋
- 🏛️ 朝代约束（{dynasty}）：{从style-presets.md提取}

> 如有需要放松的约束（如允许英文注释），请告知。
```

> ⚠️ **确认闸门**：2.1 所有参考板图片生成完毕后，必须向用户展示「参考板素材确认清单」并**等待用户明确确认**，不可自动进入 2.2。

「参考板素材确认清单」格式：
```markdown
## 🎨 参考板素材确认清单

已完成以下参考板素材生成：

| # | 类型 | 标签 | 状态 | 预览 |
|---|------|------|------|------|
| 1 | 人物 | {角色名}主立像 | ✅ | ![ref](path) |
| 2 | 人物 | {角色名}姿态 | ✅ | ![ref](path) |
| 3 | 环境 | {场景名} | ✅ | ![ref](path) |
| ... | ... | ... | ... | ... |

> 请确认以上参考板素材是否可用。如需重新生成某个参考图，请说明。确认后进入 2.2 分镜视频生成。
```

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
# 主立像（含负向提示词）
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "..." \
  --negative-prompt "xianxia style, fantasy cultivation, MMO game style, internet celebrity face, V-shaped face, glowing particles, modern clothing, neon lights, ..." \
  --size 2K --output "$OUTPUT_DIR/assets/ref_portrait.jpg"
# 姿态变体（多图融合）
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "..." \
  --negative-prompt "..." \
  --image "$OUTPUT_DIR/assets/ref_portrait.jpg" --size 2K --output "$OUTPUT_DIR/assets/ref_pose.jpg"
# 环境图
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "..." \
  --negative-prompt "..." \
  --size 2K --output "$OUTPUT_DIR/assets/ref_env.jpg"
```

### 2.2 分镜视频（依赖2.1用户确认后执行）

> ⚠️ **必须在用户确认 2.1 参考板素材后才能执行！**

按 scenes.json 顺序逐镜生成视频：

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
# 单图参考（所有分镜统一使用单张参考图生成视频）
node "$SKILLS_ROOT/seedance-ark/scripts/generate_video.js" --prompt "..." --image "$OUTPUT_DIR/assets/ref_image.jpg" --duration 8 --output "$OUTPUT_DIR/assets/scene.mp4"
```

> ⚠️ 当前模型仅支持单张参考图，所有分镜统一使用 `--image` 传入一张图。

**⚠️ 视角约束**：参考图是正面立像时，prompt 禁止用 "back to camera"/"背影"/"from behind"等描述。

> ⚠️ **确认闸门**：2.2 所有分镜视频生成完毕后，必须向用户展示「分镜视频确认清单」并**等待用户明确确认**，不可自动进入 2.3。

「分镜视频确认清单」格式：
```markdown
## 🎬 分镜视频确认清单

已完成以下分镜视频生成：

| 分镜 | 类型 | 时长 | 状态 | 备注 |
|------|------|------|------|------|
| S0 封面 | cover | 5s | ✅ | {描述} |
| S1 {名称} | verse | {X}s | ✅ | {描述} |
| S2 {名称} | verse | {X}s | ⚠️ 降级 | {降级原因} |
| ... | ... | ... | ... | ... |

**总结**：{N}/{Total} 成功，{N} 降级，{N} 失败

> 请确认以上分镜视频是否可用。如需重新生成某个分镜，请说明。确认后进入 2.3 旁白音频生成。
```

### 2.3 旁白音频（可与2.1并行启动，但完成后也须确认）

旁白音频可与 2.1 参考板**并行启动**以节约时间，但完成后同样需要用户确认。

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" --text "..." --voice "Chinese_radio_host_male_vv1" --speed 0.95 --emotion calm --output "$OUTPUT_DIR/assets/narr.mp3"
```

推荐一次性生成完整旁白（全文≤3000字符且同一voice_id），避免拼接问题。

TTS后回写 `actual_duration` → 触发全局时间轴重算。

> ⚠️ **确认闸门**：2.3 旁白音频生成完毕 + 时间轴重算后，必须向用户展示「旁白音频确认清单」并**等待用户明确确认**。

「旁白音频确认清单」格式：
```markdown
## 🎙️ 旁白音频确认清单

| 段落 | 文本摘要 | 预估 | 实测 | 偏差 | 状态 |
|------|---------|------|------|------|------|
| 段1 | {摘要} | 12.0s | 11.8s | -0.2s | ✅ |
| 段2 | {摘要} | 15.0s | 15.3s | +0.3s | ✅ |
| ... | ... | ... | ... | ... | ... |

**总时长**：预估 XXs → 实测 XXs（偏差 ±XXs）

> 请确认旁白音频是否可用。确认后进入 Phase 3 后期合成。
```

### 重试与降级

### 重试与降级

```
视频失败: 同参数重试→简化prompt→切换参考图→静态图Ken Burns→标记failed
图片失败: 同参数重试→简化prompt→T2I放弃融合→标记failed
TTS失败: 同参数重试→去掉emotion→切换voice_id→标记failed
任何scene失败不阻塞其他scene
```

---

## Phase 3: 后期合成

**详见 [references/composition-guide.md](references/composition-guide.md)**

### 3.1 时间轴校准

音频时长为基准。TTS实际时长回写后重算全局时间轴。偏差>0.5s→视频微调速；>1s→重新生成。

### 3.2 逐镜合成

- 慢放视频匹配音频时长：`setpts=(audio_dur/video_dur)*PTS`
- 合并视频+音频：OP1（音频为基准）
- 字幕烧录：优先显示诗句原文，可按需调整

### 3.3 字幕配置

根据用户在 Phase 1 选择的 `subtitle_mode`，应用对应字幕策略：

| 模式 | 字幕内容生成规则 | 示例 |
|------|----------------|------|
| `verse-only` | 每个 scene 显示对应诗句原文 | "床前明月光" |
| `verse-title` | S0 显示标题+作者，其余 scene 显示诗句 | "静夜思 — 李白" / "疑是地上霜" |
| `verse-bilingual` | 上行中文诗句 + 下行英文翻译 | "床前明月光\nMoonlight before my bed" |
| `minimal` | 仅 S0 显示标题，其余无字幕 | "静夜思 — 李白"（仅开头） |

每个场景的 `subtitle_node.config` 支持可配置参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `fontsize` | 40 | 字体大小 |
| `fontcolor` | "white" | 字体颜色 |
| `borderw` | 2 | 描边宽度 |
| `position` | "bottom" | 位置预设: bottom/center/top/custom |
| `offset_x` | "(w-text_w)/2" | X偏移 |
| `offset_y` | "h*0.85" | Y偏移 |
| `fontfile` | "/tmp/STHeiti.ttc" | 字体路径 |
| `subtitle_mode` | "{用户选择}" | verse-only/verse-title/verse-bilingual/minimal |

### 3.4 合成注意事项

- **字体路径**：ffmpeg drawtext 不支持含空格路径，必须先复制到 `/tmp/STHeiti.ttc`
- **字幕内容**：优先诗句原文，可按需调整
- **最终拼接**：concat滤镜 → movflags +faststart

---

## 输出文件结构

```
project/
├── scenes.json              # 分镜脚本
├── narration_segments.json  # 旁白脚本
├── design_system.json       # 设计语言（含reference_board）
├── subtitle_config.json     # 字幕显示配置（subtitle_mode）
├── assets/
│   ├── ref_*.jpg            # 参考板图片（2-6张）
│   ├── scene_*.mp4          # 分镜视频
│   └── narration_*.mp3      # 旁白音频
└── output/
    └── final_video.mp4      # 最终成品
```

## 注意事项

1. **技能委托**：不直接调用 ffmpeg 底层命令，通过 ffmpeg-cli 脚本
2. **图片必须用 seedream-ark**：禁止使用 image_gen 或其他内置图片生成工具，必须通过 `seedream-ark/scripts/generate_image.js` 并传入 `--negative-prompt`
3. **音频时长为基准**：视频时长跟随音频
3. **参考板先行**：视频生成依赖参考板图片确认
4. **全I2V**：所有场景使用 I2V 模式传入参考图
5. **单图参考**：所有分镜统一使用单张参考图生成视频
6. **视角一致**：正面参考图→不用背影prompt
7. **情绪统一**：同诗同 emotion（默认 calm），calm下禁用 sighs/breath/gasps
8. **字幕优先诗句**：优先显示诗句原文，支持用户按需调整
9. **字体无空格**：drawtext 用 /tmp/STHeiti.ttc
10. **异步处理**：Seedance 视频需轮询等待
11. **重试降级**：最多5次重试（同参数→简化prompt→换参考图→静态）
12. **备份中间产物**：便于调整和回滚

---

## 生成校验清单

生成视频前自动检查（详见 [references/narration_styles.md](references/narration_styles.md) 和 [references/storyboard-templates.md](references/storyboard-templates.md)）：

```
□ 总时长是否超过模板上限？
□ 旁白字数是否超过联动表上限？
□ 每句旁白是否有信息增量（非纯情绪）？
□ 分镜数是否超过上限（general≤3, classic≤7, immersive≤5, story≤5, explore≤5, short≤3）？
□ 送别类是否区分实景/虚境？
□ immersive是否≥1镜无旁白？
□ 是否出现禁止词（"啊""多么""非常"等填充词）？
```

全部通过才生成，否则自动精简。
