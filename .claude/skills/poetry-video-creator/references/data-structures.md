# 数据结构规范

## scenes.json

每个 Scene 为最小独立单元，包含视觉、音频、字幕三个节点：

```json
[
  {
    "scene_id": "uuid-v4",
    "index": 0,
    "module": "cover|intro|verse|analysis|outro|transition",
    "status": "draft|confirmed|generating|completed|failed",

    "visual_node": {
      "type": "image|video",
      "method": "i2v",
      "image_prompt": "AI图片生成英文Prompt（含style_prefix）",
      "negative_prompt": "通用负向提示词 + 风格专属负向约束（见style-presets.md）",
      "video_prompt": "AI视频生成英文Prompt（含style_prefix）",
      "reference_subjects": ["scholar-portrait", "spring-garden"],
      "reference_images": ["./assets/ref_scholar_portrait.jpg", "./assets/ref_spring_garden.jpg"],
      "ratio": "16:9",
      "duration": 5.0,
      "output_path": null,
      "skill": "seedance-ark",
      "error": null
    },

    "audio_node": {
      "segments": [
        {
          "segment_id": "uuid-v4",
          "text": "旁白原始文本",
          "tts_text": "TTS处理后的文本（含停顿标记、语气词）",
          "emotion": "calm|surprised|happy|sad",
          "tts_params": {
            "voice_id": "Chinese_radio_host_male_vv1",
            "speed": 1.0,
            "volume": 1.0,
            "pitch": 0
          },
          "estimated_duration": 4.8,
          "actual_duration": null,
          "audio_path": null
        }
      ],
      "skill": "minimax-tts",
      "error": null
    },

    "subtitle_node": {
      "text": "字幕文本（仅诗句原文）",
      "style": "title|verse|default",
      "config": {
        "fontsize": 40,
        "fontcolor": "white",
        "borderw": 2,
        "bordercolor": "black",
        "position": "bottom",
        "offset_x": "(w-text_w)/2",
        "offset_y": "h*0.85"
      },
      "timing_source": "auto:verse_line_0|auto:title|auto:narration"
    },

    "timing": {
      "start": 0.0,
      "end": 5.0,
      "duration": 5.0,
      "narration_estimated_duration": 4.5,
      "transition_in": "fade|cut|dissolve",
      "transition_out": "cut|fade|dissolve"
    },

    "transition_design": {
      "from_previous": "从前一镜头的衔接方式（如：从送者目光方向切出→叠化至江面）",
      "emotional_arc": "与前镜的情绪递进（如：怅然→空寂）",
      "visual_bridge": "视觉桥梁元素（如：孤帆/目光/水天）"
    },

    "metadata": {
      "shot_type": "特写|近景|中景|全景|远景|极远景",
      "camera_move": "固定|推|拉|摇|移|跟|升|降|环绕",
      "atmosphere": "空灵|辽阔|惆怅|深情|孤寂|深远|静谧|苍茫|壮阔|温暖|欢快",
      "scene_desc": "场景描述（中文）",
      "character_action": "人物动作描述",
      "character_ratio": "人物占画面比例（如：≤30%送者镜头 / ≤5%行者镜头 / 0%空镜）",
      "spatial_depth": "空间层次描述（如：人物清晰→楼台渐虚→烟柳朦胧→水天空白）",
      "ambient_sound": "江水波浪|风声|鸟鸣|蝉鸣|雨声|钟声|无"
    },

    "dependencies": {
      "design_system_version": 1,
      "reference_subjects": ["scholar-portrait", "spring-garden"],
      "preceding_scene_id": null
    }
  }
]
```

### prompt 规范

- **image_prompt 规范：**
- 英文撰写，逗号分隔关键词
- 结构：style_prefix → 主体 → 动作 → 环境 → 光影 → 画质
- 必须以 `design_system.reference_board.style_prefix` 开头
- 必须包含 `design_system.visual_identity.style_keywords` 中的至少2个
- `reference_subjects` 中引用的 subject 的 `immutable_attributes` 必须体现在 prompt 中
- **negative_prompt 必须包含**：通用负向提示词 + 该风格的专属负向约束（见 style-presets.md）

**video_prompt 规范：**
- 结构：style_prefix → [场景描述] → [主体动作] → [镜头运动] → [氛围/情绪]
- 必须以 `style_prefix` 开头
- `reference_subjects` 指定的参考图通过 `--image` 参数传入 Seedance

**video_prompt 视角约束（关键！）：**
```
参考图是正面立像时：
  ✅ 允许: "3/4 side view facing right", "front view", "slight turn"
  ❌ 禁止: "back to camera", "from behind", "背影", "背对", "rear view"

参考图是侧面立像时：
  ✅ 允许: "side profile facing left/right", "3/4 view"
  ❌ 禁止: 与参考图朝向相反的视角描述

原因：Seedance I2V 会尝试将参考图的面部映射到视频帧，
  如果 prompt 要求"背影"但参考图是正面 → 模型生成混合视角，导致头部造型不一致
```

---

## narration_segments.json

```json
[
  {
    "segment_id": "uuid-v4",
    "scene_id": "uuid-v4",
    "project_id": "uuid-v4",
    "segment_index": 0,
    "text": "旁白原始文本",
    "tts_text": "TTS处理后的文本",
    "emotion_label": "平静",
    "tts_params": {
      "voice_id": "Chinese_radio_host_male_vv1",
      "speed": 1.05,
      "volume": 1.0,
      "pitch": 0,
      "emotion": "surprised"
    },
    "control_markers": {
      "inner_pause": 0.3,
      "end_pause": 0.4,
      "particles": []
    },
    "estimated_duration": 5.2,
    "actual_duration": null,
    "audio_path": null,
    "status": "draft|confirmed|generated|failed"
  }
]
```

### 情绪映射表

> 同一首诗所有段落使用同一 emotion（默认 calm），通过语速(speed)和停顿(pause)微调情绪变化。

| storyboard情绪标签 | minimax emotion | speed偏移 | volume偏移 | 句内停顿 | 段末停顿 | 典型场景 |
|-------------------|-----------------|----------|-----------|---------|---------|---------|
| 平静 | `calm` | 0 | 0 | 0.3s | 0.5s | 旁述、背景介绍 |
| 好奇 | `surprised` | +0.05 | 0 | 0.3s | 0.4s | 提问、发现细节 |
| 惊喜 | `happy` | +0.1 | +0.1 | 0.2s | 0.4s | 突然发现、意外之美 |
| 温暖 | `calm` | -0.1 | 0 | 0.4s | 0.6s | 结尾感悟、余韵 |
| 感伤 | `sad` | -0.15 | -0.1 | 0.5s | 0.8s | 送别、怀古 |
| 欢快 | `happy` | +0.1 | +0.1 | 0.2s | 0.3s | 儿童场景、春景 |
| 庄重 | `calm` | -0.15 | +0.1 | 0.4s | 0.6s | 咏史、壮景 |
| 豪迈 | `surprised` | +0.15 | +0.2 | 0.2s | 0.4s | 豪放词、战诗 |
| 余韵 | `calm` | -0.2 | -0.1 | 0.5s | 1.0s | 收尾、留白 |

### TTS 语气词与情绪一致性规则

```
⚠️ 同一首诗的所有旁白段落必须使用相同的 emotion 参数，避免音色割裂

语气词禁用规则：
  - 当 emotion=calm 时，禁止使用 (sighs) (breath) (gasps) 等感叹词标记
    原因：calm 情绪下这些标记被模型解读为叹气/喘息声，产生不自然的声音
  - (chuckle) 仅在 emotion=happy 时使用
  - (emm) 仅在 emotion=surprised 时使用
  - 安全做法：如不确定效果，先不加语气词，生成后听检再决定

emotion 一致性规则：
  - 同一首诗所有 narration_segments 必须使用同一 emotion
  - 推荐默认：calm（最稳定，意外最少）
  - 仅在用户明确要求时使用其他 emotion
  - 如需情绪变化，通过语速(speed)和停顿(pause)微调，而非切换 emotion
```

### 语速标准

```
统一语速：200-220字/分钟（基础 speed=1.0 约 3.3-3.7字/秒）
preschool：略慢 150-180字/分钟（speed=0.85）
recitation：按诗词类型调整
  - 豪放/边塞：200字/分钟（speed=1.0）
  - 婉约/闺怨：160字/分钟（speed=0.8）
  - 田园/写景：160字/分钟（speed=0.8）
  - 哲理/禅意：130字/分钟（speed=0.65）
```

### 旁白文本→TTS文本处理管线

```
原始文本 (text)
  ↓ 1. 发音词典预处理（可选）
  ↓ 2. 标点→停顿映射:
        。→ <#0.4#>   ！→ <#0.5#>   ？→ <#0.5#>
        ，→ <#0.2#>   ；→ <#0.3#>   ……→ <#0.8#>
  ↓ 3. 语气词注入（遵循禁用规则）
  ↓ 4. 长句拆分（超过40字强制插入 <#0.3#>）
  ↓
TTS文本 (tts_text)
```

---

## design_system.json

```json
{
  "version": 1,
  "project_id": "uuid-v4",
  "is_current": true,
  "style_id": "ghibli-ink",
  "style_name": "吉卜力水墨",

  "visual_identity": {
    "style_statement": "吉卜力式水墨动画，宋代文人画意境，清新温润的日常感",
    "style_keywords": ["anime style", "Studio Ghibli inspired", "Chinese ink-wash aesthetic", "soft warm lighting"],
    "reference": "宫崎骏动画 + 宋代水墨小品"
  },

  "color_language": {
    "primary": ["#E8F5E9", "#E3F2FD"],
    "secondary": ["#FFF8E1", "#5D4037"],
    "mood_mapping": { "见 style-presets.md 色彩情绪映射" }
  },

  "negative_prompt_template": "通用负向提示词（见style-presets.md） + 该风格专属约束",

  "reference_board": {
    "style_prefix": "anime style, Studio Ghibli inspired, Chinese ink-wash aesthetic, soft warm lighting, masterpiece, best quality, highly detailed",
    "subjects": [
      {
        "id": "scholar-portrait",
        "type": "character",
        "label": "文人·立像",
        "prompt": "{style_prefix}, a slender Chinese scholar from Southern Song Dynasty in light grey robe with dark sash, large expressive anime eyes, gentle smile, three strands of long beard",
        "output_path": "./assets/ref_scholar_portrait.jpg",
        "immutable_attributes": ["素色交领长袍（浅灰或米白）", "巾帽", "清瘦面容+长须", "大眼睛+表情丰富"],
        "mutable_attributes": [],
        "character_profile": {
          "core_positioning": "一句话核心定位（是X而非Y）",
          "forbidden": ["角色级禁止元素，与风格级负向约束互补"],
          "scene_interaction": {
            "元素A": "处理方式（如：仅以栏杆暗示，不抢主体）",
            "元素B": "处理方式（如：完全不出现，强化孤独感）"
          },
          "emotion_progression": [
            { "stage": "首帧", "expression": "初始情绪", "prompt_fragment": "英文表情描述" },
            { "stage": "中帧", "expression": "情绪变化", "prompt_fragment": "英文表情描述" },
            { "stage": "末帧", "expression": "最终情绪", "prompt_fragment": "英文表情描述" }
          ]
        },
        "scene_variants": {
          "current_poem": "当前诗词中该角色的形象微调描述",
          "other_poems": {}
        }
      },
      {
        "id": "scholar-reading",
        "type": "character_pose",
        "label": "文人·读书",
        "prompt": "{style_prefix}, Chinese scholar in light grey robe sitting by window reading scroll, gentle focused expression, three strands of long beard, ink and brush nearby",
        "output_path": "./assets/ref_scholar_reading.jpg",
        "inherit_from": "scholar-portrait",
        "mutable_attributes": ["坐姿", "手持书卷"]
      },
      {
        "id": "spring-garden",
        "type": "environment",
        "label": "春日庭院",
        "prompt": "{style_prefix}, Chinese traditional garden with blooming cherry trees, small stone bridge over clear stream, soft morning light, peaceful atmosphere",
        "output_path": "./assets/ref_spring_garden.jpg",
        "immutable_attributes": [],
        "mutable_attributes": ["季节/时段", "天气"],
        "environment_layers": {
          "far": "远景层描述（占画面比例、色调、关键元素）",
          "mid": "中景层描述（主体环境、色彩、虚实）",
          "near": "近景层描述（前景点缀、暗示、留空）"
        },
        "atmosphere": {
          "lighting": "光线描述（如：春日午后柔和漫射光，无强烈阴影）",
          "air": "空气感（如：薄雾轻烟，朦胧如烟）",
          "dynamics": "动态元素（如：花瓣飘飞、柳丝轻扬、水波微漾）",
          "ambient_sound": "声音暗示（供音频参考，如：江水轻拍、远舟欸乃）"
        },
        "character_relation": {
          "character_ratio": "人物占比上限（如：≤30%）",
          "gaze_direction": "视线引导（如：人物目光→孤帆→水天尽头）",
          "color_contrast": "色彩对比逻辑（如：人淡景浓，以静衬动）",
          "spatial_depth": "空间层次（如：人物清晰→楼台渐虚→烟柳朦胧→水天空白）"
        },
        "style_adaptation": {
          "ghibli-ink": "该风格下的环境调整",
          "traditional-ink": "该风格下的环境调整",
          "watercolor": "该风格下的环境调整",
          "gongbi": "该风格下的环境调整",
          "new-chinese": "该风格下的环境调整",
          "fantasy-ancient": "该风格下的环境调整"
        },
        "environment_forbidden": ["环境级禁止元素，如：禁止秋冬萧瑟/禁止江面多船/禁止夕阳西下"]
      }
    ]
  },

  "composition_rules": [
    "角色占画面1/3-1/2（送者镜头），≤5%（行者镜头），0%（空镜）",
    "自然元素（水/树/花）每镜至少占40%",
    "人景色彩对比：人淡景浓/人暖景冷/人静景动，按诗境选择",
    "空间层次：人物清晰→中景渐虚→远景朦胧→极远景留白",
    "视线引导：人物目光指向画面纵深方向，引导观众视线",
    "转场优先用叠化/溶解，硬切仅用于情绪转折",
    "镜头衔接遵循情绪递进：实→虚、满→空、近→远"
  ],

  "quality_gates": {
    "consistency_check": "角色外貌是否符合 immutable_attributes",
    "style_check": "image_prompt是否包含 style_prefix 和 style_keywords 中的至少2个",
    "mood_check": "色调是否匹配 mood_mapping 中对应情绪",
    "reference_coverage": "每个scene是否引用了合适的 reference_subjects"
  }
}
```

### reference_board subjects 数量原则

- 人物类 1-3 个（主立像 + 关键姿态变体）
- 环境类 1-3 个（主要场景）
- 总计 2-6 个
- 叙事性强的诗词需要更多人物姿态变体，写景抒情的诗词需要更多环境参考

### 设计语言变更确认流程

```
用户修改分镜 → 检测是否涉及 immutable_attributes 或 reference_board
  ├── 不涉及 → 直接更新
  └── 涉及 → 确认后更新 design_system.json + version+1 + 影响范围内 scene 标记待重新生成
```

---

## 时间轴校准

**核心原则：音频时长为基准（Ground Truth），视频时长跟随音频。**

### 三轮校准协议

```
Round 1 - 创意估算（Phase 1）
  公式: estimated_dur = char_count / base_chars_per_sec + emotion_speed_offset + pause_total
  精度: ±20%

Round 2 - TTS实测校准（Phase 2，音频生成后）
  动作: 逐段TTS → 获取actual_duration → 回写 → 全局时间轴重算
  精度: ±5%

Round 3 - 合成后校准（Phase 3）
  动作: 检测合成后每段实际时长 → 偏差>0.5s的段落标注
  处理: 偏差0.5-1s → 视频微调速；偏差>1s → 重新生成
```

### 时间轴计算公式

```
base_chars_per_sec = 3.5（200-220字/分钟，约3.3-3.7字/秒，取3.5为均值）
preschool: base_chars_per_sec = 2.8（150-180字/分钟）
recitation: 按诗词类型调整（见语速标准章节）

narration_duration = char_count / (base_chars_per_sec × speed) + emotion_offset + pause_total
scene_duration = max(narration_duration, min_visual_duration) + padding(0.3s)
absolute_start = Σ preceding scene_durations
```

### 修改联动

```
旁白文本变更 → 该scene的audio_node + subtitle_node标记"待更新" + timing标记"待校准"
design_system变更 → 所有scene的visual_node标记"待重新生成"（version+1）
参考板subject变更 → 仅引用该subject的scene标记"待重新生成"
```

---

## 镜头语言词库

### 景别（shot_type）

| 景别 | 画面占比 | 适用场景 | prompt关键词 |
|------|---------|---------|-------------|
| 极远景 | 人物<5% | 大江大河、天际线、意境留白 | extreme wide shot, vast landscape |
| 远景 | 人物5-15% | 建筑全景、山水全貌 | wide shot, establishing shot |
| 全景 | 人物15-30% | 人物+环境互动 | full shot, figure in landscape |
| 中景 | 人物30-50% | 人物动作、互动 | medium shot, waist up |
| 近景 | 人物50-70% | 表情、手势 | close-up, chest up |
| 特写 | 人物>70% | 眼神、细节 | extreme close-up, detail shot |

### 镜头运动（camera_move）

| 运动 | 效果 | 情感暗示 | prompt关键词 |
|------|------|---------|-------------|
| 固定 | 静止观察 | 平静、凝视 | static camera, still shot |
| 推 | 放大主体 | 聚焦、强调、逼近 | slow push-in, zoom in |
| 拉 | 展现全貌 | 释放、开阔、余韵 | slow pull-back, zoom out |
| 摇 | 水平扫视 | 环顾、展陈 | slow pan left/right |
| 移 | 跟随移动 | 伴随、同行 | tracking shot, dolly shot |
| 跟 | 主体移动 | 追随、紧迫 | follow shot |
| 升 | 俯视展开 | 升华、超越 | ascending shot, crane up |
| 降 | 沉入场景 | 沉浸、压迫 | descending shot |
| 环绕 | 立体展现 | 壮阔、仪式感 | orbit shot, 360 rotation |

### 景别+运动组合推荐

```
封面/开场：远景+推（壮阔引入）
人物出场：中景+固定（稳重磅定）
情感高潮：近景+推（情绪聚焦）
离别/远去：远景+拉（释放余韵）
结尾留白：极远景+缓拉（意境延伸）
空镜过渡：远景+固定（呼吸空间）
```

---

## 镜头衔接设计

> 分镜之间不仅是硬切，还需要考虑情绪递进和视觉桥梁。

### 衔接模式

| 模式 | 适用场景 | 情绪效果 | prompt/转场关键词 |
|------|---------|---------|------------------|
| 实→虚 | 送者→行者、清醒→梦境 | 充实→空虚 | dissolve, fade through |
| 虚→实 | 行者→送者、回忆→现实 | 渺茫→聚焦 | cut on action, hard cut |
| 满→空 | 人物占比较大→纯环境 | 释放、余韵 | slow dissolve to landscape |
| 空→满 | 纯环境→人物出场 | 悬念、发现 | slow push-in from landscape |
| 近→远 | 情绪高潮→意境收束 | 升华、释然 | slow pull-back, crane up |
| 远→近 | 宏观铺陈→细节聚焦 | 沉浸、逼近 | slow zoom in |

### 送别类专用衔接

```
A镜（送者，人实）→ B镜（行者，人虚）:
  视觉桥梁：从送者目光方向切出 → 叠化至江面孤舟
  情绪递进：怅然(满) → 空寂(空)
  A镜的"满"恰好让B镜的"空"更有力

B镜（行者）→ C镜（空镜）:
  视觉桥梁：孤帆渐渺 → 水天浩渺无帆
  情绪递进：空寂 → 无言
  转场：溶解或缓慢拉远

C镜（空镜）→ D镜（送者独立）:
  视觉桥梁：水天回望 → 送者独对空江
  情绪递进：无言 → 怅然若失
  转场：从远景切至中景，空间收缩
```

### transition_design 字段使用指南

每个 scene 的 `transition_design` 字段用于描述与前后镜头的衔接关系：

```
"transition_design": {
  "from_previous": "从前一镜头的衔接方式",
  "emotional_arc": "与前镜的情绪递进（如：怅然→空寂）",
  "visual_bridge": "视觉桥梁元素（如：孤帆/目光/水天）"
}
```

---

## 环境分层设计

> 环境不是扁平的一层描述，而是远景/中景/近景三层叠加，每层有独立的虚实、色调和元素。

### 三层结构

| 层次 | 画面占比 | 描述重点 | 虚实 | 典型元素 |
|------|---------|---------|------|---------|
| 远景(far) | 50%+ | 天际线、远景山/水 | 极虚，淡墨/留白 | 水天交界、远山一痕、帆影渐渺 |
| 中景(mid) | 30-40% | 主体环境、色彩主体 | 中虚，朦胧 | 江面波光、烟柳、楼台轮廓 |
| 近景(near) | 10-20% | 前景点缀、情绪暗示 | 可实可虚 | 花瓣飘飞、栏杆、芳草 |

### 环境氛围四要素

| 要素 | 说明 | prompt关键词示例 |
|------|------|-----------------|
| 光线(light) | 时段+方向+质感 | soft diffused morning light, golden hour side light |
| 空气感(air) | 雾/烟/通透度 | light mist, hazy atmosphere, clear crisp air |
| 动态(dynamics) | 画面中的运动元素 | petals floating, willow swaying, water rippling |
| 声音暗示(ambient_sound) | 供音频参考 | (见环境音效章节) |

### 分风格环境适配

| 风格 | 远景处理 | 中景处理 | 近景处理 |
|------|---------|---------|---------|
| `ghibli-ink` | 翠绿欲滴，水面天蓝反光 | 花瓣粉白圆润 | 明亮童话感 |
| `traditional-ink` | 大面积留白，仅淡墨远山 | 中墨勾柳枝 | 极简，一两笔暗示 |
| `watercolor` | 水色晕染交融 | 边缘虚化，湿画法 | 花瓣柳丝柔化 |
| `gongbi` | 远景仍虚，保持层次 | 楼阁花木精细 | 繁密但不抢主体 |
| `new-chinese` | 90%留白 | 几笔柳丝、一点帆影 | 极少元素，高度概括 |
| `fantasy-ancient` | 色彩稍浓，暮春绚烂 | 有层次但禁发光 | 保持真实春光 |

### 人景关系处理

| 关系 | 处理方式 |
|------|---------|
| 人物占比 | 送者镜头≤30%，行者镜头≤5%，空镜0% |
| 视线引导 | 人物目光→关键意象→画面纵深尽头 |
| 色彩对比 | 人淡景浓（送别类）/ 人暖景冷（怀古类）/ 人静景动（田园类） |
| 空间层次 | 人物清晰→中景渐虚→远景朦胧→极远景留白 |
| 构图位置 | 人物多置左侧或下方1/3，留出空间纵深 |

> 当前管线暂不自动生成环境音效，仅在 metadata.ambient_sound 中标注设计意图，供后期手动添加。

| 音效类型 | 适用诗词类型 | 获取方式 |
|---------|------------|---------|
| 江水波浪 | 山水/送别/行旅 | 免费音效库(freesound.org) |
| 风声 | 四季/高台/旷野 | 免费音效库 |
| 鸟鸣 | 春景/田园/山林 | 免费音效库 |
| 蝉鸣 | 夏景/离别 | 免费音效库 |
| 雨声 | 秋思/夜雨/愁绪 | 免费音效库 |
| 钟声 | 寺庙/怀古/禅意 | 免费音效库 |

后期添加方式：在 Phase 3 合成时，将环境音作为额外音轨混合（音量≤旁白的30%）。
