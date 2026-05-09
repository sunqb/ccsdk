# 后期合成操作指南

## 字幕配置规范

### subtitle_node.config 字段

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `fontsize` | int | 40 | 字体大小（像素） |
| `fontcolor` | string | "white" | 字体颜色 |
| `borderw` | int | 2 | 描边宽度 |
| `bordercolor` | string | "black" | 描边颜色 |
| `position` | string | "bottom" | 位置预设：bottom/center/top/custom |
| `offset_x` | string | "(w-text_w)/2" | X偏移（ffmpeg表达式） |
| `offset_y` | string | "h*0.85" | Y偏移（ffmpeg表达式） |
| `fontfile` | string | "/tmp/STHeiti.ttc" | 字体文件路径 |
| `line_spacing` | int | 0 | 行间距（双行字幕时） |

### 位置预设映射

| position | offset_x | offset_y(单行) | offset_y(双行上行/下行) |
|----------|----------|----------------|------------------------|
| `bottom` | (w-text_w)/2 | h*0.85 | h*0.78 / h*0.86 |
| `center` | (w-text_w)/2 | h*0.48 | h*0.42 / h*0.52 |
| `top` | (w-text_w)/2 | h*0.08 | h*0.05 / h*0.13 |
| `custom` | 用户指定 | 用户指定 | 用户指定 |

### 字幕内容规则

- 视频字幕优先显示诗句原文，支持用户按需调整内容
- 默认：字幕=诗句原文，解说/赏析仅通过旁白传达
- 用户可自定义字幕内容（如添加解说要点、英文翻译等），通过 `subtitle_node.config.content_override` 字段覆盖
- s0 封面默认显示标题+作者（格式："李白（唐）"），也可自定义

## FFmpeg 字体路径规则

```
❌ fontfile=/System/Library/Fonts/STHeiti Medium.ttc（含空格→方框）
❌ fontfile=/System/Library/Fonts/STHeiti%20Medium.ttc（%20不生效）
✅ 先复制: cp "/System/Library/Fonts/STHeiti Medium.ttc" /tmp/STHeiti.ttc
```

## 标准化操作（OP1-OP6）

# SKILLS_ROOT 和 OUTPUT_DIR 由主 SKILL.md 统一定义，本处直接使用

### OP1 - 合并音频与视频（音频时长为基准）

```bash
node "$SKILLS_ROOT/ffmpeg-cli/scripts/merge_av.js" \
  --video "$OUTPUT_DIR/assets/video.mp4" --audio "$OUTPUT_DIR/assets/audio.mp3" --output "$OUTPUT_DIR/output/merged.mp4"
# 匹配策略: |差|<0.5s→直接合并; video长→截断; audio长→延长静帧
# --strategy truncate|extend|shortest  --padding 0.3
```

### OP2 - 多段视频拼接

```bash
node "$SKILLS_ROOT/ffmpeg-cli/scripts/concat_videos.js" \
  --inputs "$OUTPUT_DIR/output/scene_01.mp4" "$OUTPUT_DIR/output/scene_02.mp4" --output "$OUTPUT_DIR/output/merged.mp4"
# --reencode true  编码不一致时
```

### OP3 - 多段音频拼接

```bash
node "$SKILLS_ROOT/ffmpeg-cli/scripts/concat_audios.js" \
  --inputs "$OUTPUT_DIR/assets/narration_01.mp3" "$OUTPUT_DIR/assets/narration_02.mp3" --output "$OUTPUT_DIR/assets/merged.mp3"
# --normalize true  --crossfade 0.05
```

### OP4 - 烧录字幕（时间轴派生自旁白）

```bash
node "$SKILLS_ROOT/ffmpeg-cli/scripts/burn_subtitles.js" \
  --video "$OUTPUT_DIR/output/video.mp4" --subtitle "$OUTPUT_DIR/output/subs.srt" --output "$OUTPUT_DIR/output/final.mp4" \
  --font "PingFang SC" --font-size 22 --position bottom
# 字幕时间轴派生规则：诗句=旁白时间范围; 标题/作者=scene开头+padding
```

### OP5 - 视频调速

```bash
node "$SKILLS_ROOT/ffmpeg-cli/scripts/change_speed.js" \
  --input "$OUTPUT_DIR/assets/video.mp4" --output "$OUTPUT_DIR/assets/adjusted.mp4" --target-duration 5.0
# --speed 1.5  --target video|audio|both
# atempo范围0.5-2.0，超出自动链式处理
```

### OP6 - 完整合成管线

```
1. 逐scene: OP1（音视频匹配）
2. OP2（视频拼接）
3. OP3（音频拼接+归一化）→ OP1（合并音视频）
4. OP4（生成SRT+烧录字幕）
5. 质量验证
```

## 推荐合成流程（实践验证）

```bash
# 0. 字体预处理
cp "/System/Library/Fonts/STHeiti Medium.ttc" /tmp/STHeiti.ttc

# 1. 合并各场景音频片段
ffmpeg -y -i "$OUTPUT_DIR/assets/n2a.mp3" -i "$OUTPUT_DIR/assets/n2b.mp3" -filter_complex "[0:a][1:a]concat=n=2:v=0:a=1[outa]" -map "[outa]" "$OUTPUT_DIR/output/n2_full.mp3"

# 2. 计算慢放倍率并慢放视频
slow_factor = audio_duration / video_duration
ffmpeg -y -i "$OUTPUT_DIR/assets/src.mp4" -filter:v "setpts=${slow_factor}*PTS" -c:v libx264 -preset slow -crf 18 -an "$OUTPUT_DIR/output/slow.mp4"

# 3. 合成各场景（视频+音频+字幕）
ffmpeg -y -i "$OUTPUT_DIR/output/slow.mp4" -i "$OUTPUT_DIR/output/n2_full.mp3" \
  -filter_complex "[0:v]drawtext=text='诗句':fontsize=40:fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h*0.85:fontfile=/tmp/STHeiti.ttc[v]" \
  -map "[v]" -map 1:a -c:v libx264 -preset slow -crf 18 -c:a aac -b:a 128k -shortest "$OUTPUT_DIR/output/scene.mp4"

# 4. 拼接所有场景
ffmpeg -y -i "$OUTPUT_DIR/output/scene0.mp4" -i "$OUTPUT_DIR/output/scene1.mp4" ... \
  -filter_complex "[0:v][0:a][1:v][1:a]...concat=n=5:v=1:a=1[outv][outa]" \
  -map "[outv]" -map "[outa]" -c:v libx264 -preset slow -crf 18 -c:a aac -b:a 128k \
  -movflags +faststart "$OUTPUT_DIR/output/final.mp4"
```

## 质量检查清单

```
□ 字幕正常显示中文（非方框/乱码）
□ 字幕位置统一（底部居中）
□ 字幕内容符合预期（默认诗句原文，或用户自定义内容）
□ 各场景人物造型与参考图一致
□ 旁白音色统一（无情绪割裂）
□ 旁白无意外感叹词
□ 音画同步（偏差<0.5s）
□ 送别类诗词有"离去者"画面
```
