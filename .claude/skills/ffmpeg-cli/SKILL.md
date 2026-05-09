---
name: ffmpeg-cli
description: FFmpeg video/audio processing toolkit. Provides standardized operations for format conversion, resolution modification, subtitle burning, video/audio concatenation, speed adjustment, audio extraction, and volume normalization. Use this skill when the user needs to edit, convert, merge, or process video/audio files with FFmpeg.
version: 1.0.0
---

# ────────────────────────────────────────────────────────
# 路径推算规则（Claude 执行任意命令前均应遵守）
# ────────────────────────────────────────────────────────
# SKILLS_ROOT：技能脚本根目录
#   本 SKILL.md 的绝对路径 → 取父目录(ffmpeg-cli) → 再取上级 = SKILLS_ROOT
#   如需强制覆盖：export CLAUDE_SKILLS_ROOT=/your/path
SKILLS_ROOT="${CLAUDE_SKILLS_ROOT:-$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]:-$0}")")/.." && pwd)}"

# OUTPUT_DIR：所有生成文件的输出根目录（绝对路径）
#   默认使用当前工作目录（$PWD），即 Claude Code CLI 的 cwd。
#   前端可通过请求参数 cwd 控制输出位置，实现多用户隔离。
#   如需强制覆盖：export CLAUDE_OUTPUT_DIR=/your/path
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"

# ⚠️ 强制约束：所有 --output 和 --image 路径必须使用 $OUTPUT_DIR 下的绝对路径
#   禁止使用 ./xxx 或相对路径，否则文件会落在 Node 进程的 cwd 而非会话目录
# 合成: node "$SKILLS_ROOT/ffmpeg-cli/scripts/merge_av.js" --video "$OUTPUT_DIR/assets/v.mp4" --audio "$OUTPUT_DIR/assets/a.mp3" --output "$OUTPUT_DIR/output/final.mp4"

# FFmpeg CLI - 视频音频处理工具包

基于 FFmpeg 的标准化视频/音频处理工具集，提供 8 大核心操作，所有操作均以 Node.js 脚本封装，支持 CLI 调用和程序化调用。

## 前置依赖

### FFmpeg 安装

**方式一：conda 安装（基础版，无字幕滤镜）**
```bash
conda install -y -c conda-forge ffmpeg
```

**方式二：完整版（含 libass 字幕支持，推荐）**

通过 pip 安装 moviepy，其自带的 FFmpeg 包含 libass：
```bash
pip install moviepy
```

获取 moviepy 自带 FFmpeg 路径：
```bash
python3 -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
```

### FFmpeg 路径配置

脚本按以下优先级查找 FFmpeg：
1. 环境变量 `FFMPEG_PATH`
2. moviepy 自带 FFmpeg（`imageio_ffmpeg.get_ffmpeg_exe()`）
3. 系统 PATH 中的 `ffmpeg`

如需指定 FFmpeg 路径：
```bash
export FFMPEG_PATH="/path/to/ffmpeg"
```

**字幕烧录必须使用带 libass 的 FFmpeg**（moviepy 自带版本或自行编译版本）。

---

## 核心操作一览

| 操作ID | 名称 | 脚本 | 用途 |
|--------|------|------|------|
| OP1 | 音视频合并 | `merge_av.js` | 将无声视频与音频合并（时长匹配） |
| OP2 | 视频拼接 | `concat_videos.js` | 多段视频顺序拼接 |
| OP3 | 音频拼接 | `concat_audios.js` | 多段音频顺序拼接 |
| OP4 | 字幕烧录 | `burn_subtitles.js` | 将 SRT/ASS 字幕烧录到视频 |
| OP5 | 格式转换 | `convert.js` | 视频/音频格式转换 |
| OP6 | 分辨率修改 | `resize.js` | 修改视频分辨率/比例 |
| OP7 | 调速 | `change_speed.js` | 视频和/或音频调速 |
| OP8 | 音频处理 | `audio_process.js` | 提取音频/音量归一化/静帧延长 |

---

## OP1 - 音视频合并（时长匹配）

**核心原则：音频时长为基准（Ground Truth）**

### CLI 调用

```bash
node scripts/merge_av.js \
  --video input_video.mp4 \
  --audio input_audio.mp3 \
  --output output.mp4 \
  [--strategy auto|truncate|extend|shortest] \
  [--padding 0.3]
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--video` | 是 | — | 输入视频文件路径 |
| `--audio` | 是 | — | 输入音频文件路径 |
| `--output` | 是 | — | 输出文件路径 |
| `--strategy` | 否 | auto | 时长匹配策略：auto(自动)/truncate(截断)/extend(延长视频)/shortest(取短) |
| `--padding` | 否 | 0 | 视频末尾额外延长秒数 |

### 匹配策略

- **auto**（默认）：|视频-音频|<0.5s→直接合并；视频长→截断视频；音频长→延长视频静帧
- **truncate**：始终截断到较短时长
- **extend**：音频长时延长视频静帧
- **shortest**：取最短时长（`-shortest` 标志）

### 程序化调用

```javascript
const { mergeAV } = require('./scripts/merge_av.js');
await mergeAV({
  video: 'input.mp4',
  audio: 'input.mp3',
  output: 'output.mp4',
  strategy: 'auto'
});
```

---

## OP2 - 视频拼接

### CLI 调用

```bash
node scripts/concat_videos.js \
  --inputs video1.mp4 video2.mp4 video3.mp4 \
  --output merged.mp4 \
  [--reencode false]
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--inputs` | 是 | — | 输入视频文件路径列表 |
| `--output` | 是 | — | 输出文件路径 |
| `--reencode` | 否 | false | 是否重新编码（编码不一致时需设为true） |

### 注意事项

- 默认使用 `concat` 协议（`-c copy`），要求所有视频编码参数一致
- 编码不一致时设 `--reencode true`，会重新编码但速度较慢
- 拼接顺序与输入顺序一致

---

## OP3 - 音频拼接

### CLI 调用

```bash
node scripts/concat_audios.js \
  --inputs audio1.mp3 audio2.mp3 audio3.mp3 \
  --output merged.mp3 \
  [--normalize false] \
  [--crossfade 0]
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--inputs` | 是 | — | 输入音频文件路径列表 |
| `--output` | 是 | — | 输出文件路径 |
| `--normalize` | 否 | false | 拼接前是否音量归一化（推荐分段拼接时开启） |
| `--crossfade` | 否 | 0 | 段间交叉淡化时长（秒），0=无淡化 |

---

## OP4 - 字幕烧录

### CLI 调用

```bash
node scripts/burn_subtitles.js \
  --video input.mp4 \
  --subtitle subs.srt \
  --output output.mp4 \
  [--font "PingFang SC"] \
  [--font-size 22] \
  [--position bottom] \
  [--method ffmpeg|moviepy]
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--video` | 是 | — | 输入视频文件路径 |
| `--subtitle` | 是 | — | 字幕文件路径（.srt 或 .ass） |
| `--output` | 是 | — | 输出文件路径 |
| `--font` | 否 | PingFang SC | 字体名称（中文推荐：PingFang SC/Source Han Sans SC/SimHei） |
| `--font-size` | 否 | 22 | 字号 |
| `--position` | 否 | bottom | 字幕位置：bottom/center/top |
| `--method` | 否 | auto | 烧录方法：auto(自动检测)/ffmpeg(FFmpeg滤镜)/moviepy(MoviePy) |
| `--primary-color` | 否 | &HFFFFFF& | 字幕颜色（ASS格式，白色） |
| `--outline-color` | 否 | &H000000& | 描边颜色（ASS格式，黑色） |
| `--outline-width` | 否 | 2 | 描边宽度 |

### 方法选择逻辑

- **auto**：检测 FFmpeg 是否支持 subtitles 滤镜 → 支持则用 ffmpeg，否则用 moviepy
- **ffmpeg**：直接使用 FFmpeg subtitles 滤镜，速度快（需 libass 支持）
- **moviepy**：使用 MoviePy TextClip，中文字体支持好但速度较慢

### SRT 文件格式参考

```srt
1
00:00:01,000 --> 00:00:04,000
泉眼无声惜细流

2
00:00:04,500 --> 00:00:08,000
树阴照水爱晴柔
```

### 系统中文字体路径

| 系统 | 推荐字体 | 路径 |
|------|---------|------|
| macOS | PingFang SC | /System/Library/Fonts/PingFang.ttc |
| macOS | Hiragino Sans GB | /System/Library/Fonts/Hiragino Sans GB.ttc |
| Windows | SimHei | C:/Windows/Fonts/simhei.ttf |
| Windows | Microsoft YaHei | C:/Windows/Fonts/msyh.ttc |
| Linux | WenQuanYi Zen Hei | /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc |

---

## OP5 - 格式转换

### CLI 调用

```bash
node scripts/convert.js \
  --input input.avi \
  --output output.mp4 \
  [--video-codec libx264] \
  [--audio-codec aac] \
  [--crf 23] \
  [--preset medium] \
  [--fps 30]
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` | 是 | — | 输入文件路径 |
| `--output` | 是 | — | 输出文件路径（扩展名决定格式） |
| `--video-codec` | 否 | libx264 | 视频编码器：libx264/libx265/libvpx-vp9/copy(不转码) |
| `--audio-codec` | 否 | aac | 音频编码器：aac/libmp3lame/copy(不转码) |
| `--crf` | 否 | 23 | 视频质量（18-28，越小质量越高） |
| `--preset` | 否 | medium | 编码速度：ultrafast/superfast/veryfast/faster/fast/medium/slow/slower/veryslow |
| `--fps` | 否 | 源FPS | 帧率 |
| `--copy-all` | 否 | false | 仅改容器格式，不重新编码（`-c copy`） |

### 常见转换场景

```bash
# AVI → MP4
node scripts/convert.js --input input.avi --output output.mp4

# MP4 → WebM
node scripts/convert.js --input input.mp4 --output output.webm --video-codec libvpx-vp9

# 仅改容器（不重新编码，极快）
node scripts/convert.js --input input.mkv --output output.mp4 --copy-all true

# 高质量转码
node scripts/convert.js --input input.mp4 --output output.mp4 --crf 18 --preset slow
```

---

## OP6 - 分辨率修改

### CLI 调用

```bash
node scripts/resize.js \
  --input input.mp4 \
  --output output.mp4 \
  [--width 1920] \
  [--height 1080] \
  [--scale 0.5] \
  [--ratio 16:9]
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` | 是 | — | 输入文件路径 |
| `--output` | 是 | — | 输出文件路径 |
| `--width` | 否 | — | 目标宽度（像素），与height二选一或同时指定 |
| `--height` | 否 | — | 目标高度（像素） |
| `--scale` | 否 | — | 缩放比例（0.5=缩小一半），与width/height互斥 |
| `--ratio` | 否 | — | 目标宽高比（如16:9），自动裁剪或加黑边 |

### 常见场景

```bash
# 缩放到 1080p
node scripts/resize.js --input input.mp4 --output output.mp4 --width 1920 --height 1080

# 缩小一半
node scripts/resize.js --input input.mp4 --output output.mp4 --scale 0.5

# 转为竖屏9:16（加黑边）
node scripts/resize.js --input input.mp4 --output output.mp4 --ratio 9:16

# 仅限宽度，高度按比例
node scripts/resize.js --input input.mp4 --output output.mp4 --width 1280
```

---

## OP7 - 调速

### CLI 调用

```bash
node scripts/change_speed.js \
  --input input.mp4 \
  --output output.mp4 \
  --speed 1.5 \
  [--target video|audio|both] \
  [--target-duration 30]
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` | 是 | — | 输入文件路径 |
| `--output` | 是 | — | 输出文件路径 |
| `--speed` | 否 | — | 速度倍率（0.5=半速，2.0=双速），与target-duration二选一 |
| `--target-duration` | 否 | — | 目标时长（秒），自动计算speed |
| `--target` | 否 | both | 调速对象：video(仅视频)/audio(仅音频)/both(音视频同步) |

### 注意事项

- FFmpeg `atempo` 滤镜范围 0.5-2.0，超出需链式调用
- 调速后音频音调不变（atempo 时间拉伸）
- 仅视频调速时音频会被移除

---

## OP8 - 音频处理

### CLI 调用

```bash
# 提取音频
node scripts/audio_process.js \
  --input input.mp4 \
  --output audio.mp3 \
  --action extract

# 音量归一化
node scripts/audio_process.js \
  --input input.mp3 \
  --output normalized.mp3 \
  --action normalize \
  [--target-loudness -14]

# 视频静帧延长
node scripts/audio_process.js \
  --input input.mp4 \
  --output extended.mp4 \
  --action pad \
  --duration 10
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` | 是 | — | 输入文件路径 |
| `--output` | 是 | — | 输出文件路径 |
| `--action` | 是 | — | 操作：extract(提取音频)/normalize(音量归一化)/pad(静帧延长) |
| `--target-loudness` | 否 | -14 | 归一化目标响度（LUFS），广播标准-14 |
| `--duration` | 否 | — | pad操作的目标总时长（秒） |

---

## 供其他 Skill 调用的 API

### 标准化操作映射

其他 Skill（如 poetry-video-creator）引用此 Skill 时，使用以下操作映射：

| 操作ID | 场景 | 脚本 | 说明 |
|--------|------|------|------|
| OP1 | 合并音频与无声视频 | `merge_av.js` | 音频时长为基准，视频跟随 |
| OP2 | 多段视频顺序拼接 | `concat_videos.js` | 合并分镜视频 |
| OP3 | 多段音频顺序拼接 | `concat_audios.js` | 合并分段旁白 |
| OP4 | 字幕烧录 | `burn_subtitles.js` | SRT/ASS→视频 |
| OP5 | 格式转换 | `convert.js` | 容器/编码转换 |
| OP6 | 分辨率修改 | `resize.js` | 缩放/裁剪/加黑边 |
| OP7 | 调速 | `change_speed.js` | 音视频同步调速 |
| OP8 | 音频处理 | `audio_process.js` | 提取/归一化/静帧延长 |

### 调用示例

```bash
# poetry-video-creator 合成管线示例

# OP1: 音视频匹配
node "$SKILLS_ROOT/ffmpeg-cli/scripts/merge_av.js" \
  --video "$OUTPUT_DIR/assets/scene_01.mp4" --audio "$OUTPUT_DIR/assets/narration_01.mp3" --output "$OUTPUT_DIR/output/scene_01_merged.mp4"

# OP2: 视频拼接
node "$SKILLS_ROOT/ffmpeg-cli/scripts/concat_videos.js" \
  --inputs "$OUTPUT_DIR/output/scene_01_merged.mp4" "$OUTPUT_DIR/output/scene_02_merged.mp4" --output "$OUTPUT_DIR/output/merged.mp4"

# OP4: 字幕烧录
node "$SKILLS_ROOT/ffmpeg-cli/scripts/burn_subtitles.js" \
  --video "$OUTPUT_DIR/output/merged.mp4" --subtitle "$OUTPUT_DIR/output/subs.srt" --output "$OUTPUT_DIR/output/final.mp4"

# OP7: 调速到目标时长
node "$SKILLS_ROOT/ffmpeg-cli/scripts/change_speed.js" \
  --input "$OUTPUT_DIR/assets/scene.mp4" --output "$OUTPUT_DIR/assets/scene_adjusted.mp4" --target-duration 5.0
```

---

## 质量标准

| 操作 | 质量要求 |
|------|---------|
| 音视频合并 | 音频与视频时长偏差 < 0.5s |
| 视频拼接 | 相邻片段无黑帧/跳帧，编码参数一致 |
| 音频拼接 | 段间无爆音/断点，音量归一化后 ±3 LUFS |
| 字幕烧录 | 字幕时间轴与音频对齐，中文字体正常渲染 |
| 格式转换 | 目标格式可正常播放，质量损失可接受 |
| 分辨率修改 | 画面无拉伸变形，宽高比正确 |
| 调速 | 音视频同步，音调不变 |
| 音频处理 | 归一化后响度在目标 ±2 LUFS |

---

## 常见问题

### 1. 字幕烧录报错 "No such filter: 'subtitles'"

FFmpeg 未编译 libass 支持。解决方案：
- 使用 `--method moviepy` 调用 MoviePy 烧录
- 或安装 moviepy 后使用其自带的 FFmpeg（自动支持）

### 2. 视频拼接后黑帧/跳帧

输入视频编码参数不一致。解决方案：
- 使用 `--reencode true` 重新编码
- 或先用 convert.js 统一编码参数再拼接

### 3. 中文字体显示为方块

系统中未安装对应中文字体。解决方案：
- macOS: 系统自带 PingFang SC，无需额外安装
- Linux: 安装 `fonts-wqy-zenhei` 或 `fonts-noto-cjk`
- Windows: 系统自带 SimHei/Microsoft YaHei

### 4. FFmpeg 命令执行超时

大文件处理耗时较长。建议：
- 字幕烧录等耗时操作预留充足时间
- 可先用短片段测试参数正确性
