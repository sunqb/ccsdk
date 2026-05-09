---
name: minimax-tts
description: Text-to-speech synthesis using MiniMax speech models (speech-2.8-hd/turbo). Supports configurable voice, speed, pitch, emotion, pronunciation dictionary, and multiple audio formats. Use this skill when the user wants to generate audio, synthesize speech, create narration, or convert text to voice using MiniMax TTS API.
version: 1.0.0
---

# ────────────────────────────────────────────────────────
# 路径推算规则（Claude 执行任意命令前均应遵守）
# ────────────────────────────────────────────────────────
# SKILLS_ROOT：技能脚本根目录
#   本 SKILL.md 的绝对路径 → 取父目录(minimax-tts) → 再取上级 = SKILLS_ROOT
#   如需强制覆盖：export CLAUDE_SKILLS_ROOT=/your/path
SKILLS_ROOT="${CLAUDE_SKILLS_ROOT:-$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]:-$0}")")/.." && pwd)}"

# OUTPUT_DIR：所有生成文件的输出根目录（绝对路径）
#   默认使用当前工作目录（$PWD），即 Claude Code CLI 的 cwd。
#   前端可通过请求参数 cwd 控制输出位置，实现多用户隔离。
#   如需强制覆盖：export CLAUDE_OUTPUT_DIR=/your/path
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"

# ⚠️ 强制约束：所有 --output 和 --image 路径必须使用 $OUTPUT_DIR 下的绝对路径
#   禁止使用 ./xxx 或相对路径，否则文件会落在 Node 进程的 cwd 而非会话目录
# 示例: node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" --text "..." --output "$OUTPUT_DIR/assets/narr.mp3"

# MiniMax TTS 语音合成

使用 MiniMax 语音合成 API 将文本转换为高质量语音，支持多种音色、情感、语速调节，适用于旁白生成、有声阅读、配音等场景。

## 配置

### 方式一：配置文件（推荐）

创建配置文件 `~/.phoenixassistantai/media_config.json`：

```json
{
  "minimaxTTS": {
    "enabled": true,
    "apiKey": "你的API密钥"
  }
}
```

### 方式二：环境变量

```bash
# macOS/Linux
export MINIMAX_API_KEY="你的API密钥"

# Windows PowerShell
$env:MINIMAX_API_KEY="你的API密钥"
```

### 获取 API Key

1. 访问 MiniMax 开放平台：https://platform.minimaxi.com/user-center/basic-information/interface-key
2. 创建新的 API Key
3. 复制密钥并配置

## 使用示例

**路径说明**：下面的示例使用 `$SKILLS_ROOT` 环境变量来引用脚本路径。

### 1. 基础语音合成

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "你好，这是一段测试语音" \
  --output "$OUTPUT_DIR/hello.mp3"
```

### 2. 指定音色和情感

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "今天是不是很开心呀，当然了！" \
  --voice "male-qn-qingse" \
  --emotion "happy" \
  --output "$OUTPUT_DIR/happy.mp3"
```

### 3. 从文件读取文本

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text-file "$OUTPUT_DIR/narration.txt" \
  --output "$OUTPUT_DIR/narration.mp3" \
  --speed 0.9 \
  --voice "Chinese (Mandarin)_Warm_Bestie"
```

### 4. 完整参数配置

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "泉眼无声惜细流，树阴照水爱晴柔" \
  --model "speech-2.8-hd" \
  --voice "Chinese (Mandarin)_Warm_Bestie" \
  --speed 1.0 \
  --volume 1.0 \
  --pitch 0 \
  --emotion "calm" \
  --format mp3 \
  --sample-rate 32000 \
  --bitrate 128000 \
  --channel 1 \
  --output "$OUTPUT_DIR/xiaochi.mp3"
```

### 5. 使用发音词典

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "这里的处理方式很危险" \
  --pronunciation "处理/(chu3)(li3)" --pronunciation "危险/dangerous" \
  --output "$OUTPUT_DIR/custom_pron.mp3"
```

### 6. URL输出模式（获取音频下载链接）

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "这是一段语音" \
  --output-format url \
  --output "$OUTPUT_DIR/result.mp3"
```

### 7. 开启字幕服务

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "这是一段需要字幕的语音" \
  --subtitle \
  --output "$OUTPUT_DIR/with_subtitle.mp3"
```

### 8. 使用语言增强（方言/小语种）

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "你好世界" \
  --language-boost "Chinese,Yue" \
  --output "$OUTPUT_DIR/cantonese.mp3"
```

## 参数说明

### 必需参数（二选一）

| 参数 | 说明 | 示例 |
|-----|------|------|
| `--text` | 直接输入合成文本 | "你好世界" |
| `--text-file` | 从文件读取合成文本 | ./narration.txt |

> 文本长度限制：不超过 10,000 字符；超过 3,000 字符建议使用流式输出。

### 可选参数

| 参数 | 说明 | 默认值 | 可选值 |
|-----|------|-------|--------|
| `--model` | 模型版本 | `speech-2.8-hd` | 见模型列表 |
| `--voice` / `-v` | 音色ID | `Chinese (Mandarin)_Warm_Bestie` | 见音色列表 |
| `--speed` | 语速 | `1.0` | 0.5-2.0 |
| `--volume` | 音量 | `1.0` | 0.1-2.0 |
| `--pitch` | 音调 | `0` | -12 到 12 |
| `--emotion` | 情感 | 无 | 见情感列表 |
| `--format` / `-f` | 音频格式 | `mp3` | `mp3`, `wav`, `flac` |
| `--sample-rate` | 采样率 | `32000` | 16000, 24000, 32000, 44100, 48000 |
| `--bitrate` | 比特率 | `128000` | 64000, 128000, 256000 |
| `--channel` | 声道数 | `1` | 1(单声道), 2(立体声) |
| `--output` / `-o` | 输出文件路径 | `output.mp3` | 文件路径 |
| `--output-format` | API输出格式 | `hex` | `hex`(数据直返), `url`(24h有效链接) |
| `--pronunciation` | 发音词典（可多次使用） | 无 | `"词语/(拼音)"` 格式 |
| `--language-boost` | 语言增强 | 无 | 见语言列表 |
| `--subtitle` | 开启字幕服务 | 否 | 标志参数 |
| `--aigc-watermark` | 添加AIGC水印 | 否 | 标志参数 |
| `--stream` | 流式输出 | 否 | 标志参数 |

## 模型选择

| 模型 | 特点 | 适用场景 |
|-----|------|---------|
| `speech-2.8-hd` | 最高音质，支持语气词标签 | 高质量旁白、有声书（**推荐**） |
| `speech-2.8-turbo` | 快速生成，支持语气词标签 | 实时对话、快速预览 |
| `speech-02-hd` | 高音质 | 通用场景 |
| `speech-02-turbo` | 快速生成 | 实时场景 |
| `speech-01-hd` | 基础高音质 | 兼容旧项目 |
| `speech-01-turbo` | 基础快速 | 兼容旧项目 |

## 音色列表

### 中文男声

| voice_id | 风格描述 | 适用场景 |
|----------|---------|---------|
| `Chinese_radio_host_male_vv1` | 低沉沉稳，浑厚磁性，沉浸式 | 古诗词旁白首选、深夜电台、正式活动主持 |
| `Chinese (Mandarin)_Reliable_Executive` | 低沉厚实，磁性，从容不迫 | 豪放词/边塞诗旁白、高端商务解说 |
| `hunyin_6` | 清亮干脆，意气风发 | 古风广播剧、少年侠客角色、送别诗 |
| `Chinese (Mandarin)_Male_Announcer` | 清澈干净，自然流畅，邻家大哥哥 | 温情叙事、有声小说朗读、情感电台 |
| `Chinese_radient_storyteller_vv1` | 沙哑鼻音，引人入胜，极强表现力 | 叙事长诗、诗歌朗诵、文化纪录片 |
| `male-qn-qingse` | 青涩男声 | 少年角色、校园题材 |
| `male-qn-jingying` | 精英男声 | 商务解说、极简风格旁白 |
| `male-qn-badao` | 霸道男声 | 广播剧角色 |
| `male-qn-daxuesheng` | 大学生男声 | 青春题材 |
| `preschool_male` | 学前男声 | 幼儿启蒙 |

### 中文女声

| voice_id | 风格描述 | 适用场景 |
|----------|---------|---------|
| `Chinese (Mandarin)_Gentle_Senior` | 温婉柔和，娓娓道来，富有感染力 | 婉约词旁白、治愈系有声读物、情感电台 |
| `Chinese (Mandarin)_Sweet_Lady` | 甜美细腻，舒缓自然，邻家亲切 | 儿童诗词启蒙、情感类电台、生活类Vlog |
| `Chinese (Mandarin)_Cute_Spirit` | 软萌稚嫩，轻快活泼 | 幼儿古诗启蒙、卡通动画、萌宠角色 |
| `Chinese (Mandarin)_Warm_Bestie` | 温暖亲切的女声（默认推荐） | 通用场景 |
| `Chinese (Mandarin)_Female_Young` | 年轻清亮女声 | 青少年向内容 |
| `Chinese (Mandarin)_Female_Mature` | 成熟知性女声 | 传统水墨/工笔向旁白 |
| `preschool_female` | 学前女声 | 幼儿启蒙 |

> 更多音色请参考 MiniMax 官方文档：https://platform.minimaxi.com/docs/guides/t2a-voice

## 情感列表

| emotion | 说明 |
|---------|------|
| `happy` | 开心 |
| `sad` | 伤心 |
| `angry` | 生气 |
| `fearful` | 恐惧 |
| `disgusted` | 厌恶 |
| `surprised` | 惊讶 |
| `calm` | 平静 |

> 情感参数仅部分音色支持，详见官方文档。

## 语言增强列表

支持的语言/方言（`--language-boost` 参数）：

`Chinese`, `Chinese,Yue`（粤语）, `English`, `Arabic`, `Russian`, `Spanish`, `French`, `Portuguese`, `German`, `Turkish`, `Dutch`, `Ukrainian`, `Vietnamese`, `Indonesian`, `Japanese`, `Italian`, `Korean`, `Thai`, `Polish`, `Romanian`, `Greek`, `Czech`, `Finnish`, `Hindi`, `Bulgarian`, `Danish`, `Hebrew`, `Malay`, `Persian`, `Slovak`, `Swedish`, `Croatian`, `Filipino`, `Hungarian`, `Norwegian`, `Slovenian`, `Catalan`, `Nynorsk`, `Tamil`, `Afrikaans`, `auto`

## 文本特殊标记

### 停顿控制

格式：`<#x#>`，`x` 为停顿时长（秒），范围 [0.01, 99.99]

```
这是第一句<#0.5#>停顿半秒后继续
```

### 语气词标签（仅 speech-2.8 系列）

| 标签 | 含义 | 标签 | 含义 |
|------|------|------|------|
| `(laughs)` | 笑声 | `(chuckle)` | 轻笑 |
| `(coughs)` | 咳嗽 | `(sighs)` | 叹气 |
| `(breath)` | 换气 | `(gasps)` | 倒吸气 |
| `(humming)` | 哼唱 | `(emm)` | 嗯 |

## 输出信息

脚本成功运行后将输出以下信息：

```
✅ 语音合成成功！
文件路径: /path/to/output.mp3
音频时长: 9.9 秒
采样率: 32000 Hz
比特率: 128000 bps
音频格式: mp3
声道数: 1
计费字符数: 26
```

## 程序化调用（供其他 Skill 集成）

其他 Skill 可通过读取本文件了解接口规范，并以以下方式调用：

### 方式一：命令行调用

```bash
node "$SKILLS_ROOT/minimax-tts/scripts/synthesize.js" \
  --text "合成文本" \
  --voice "Chinese (Mandarin)_Warm_Bestie" \
  --speed 1.0 \
  --output "$OUTPUT_DIR/assets/narration.mp3"
```

### 方式二：作为模块引用

```javascript
const { synthesize } = require('$SKILLS_ROOT/minimax-tts/scripts/synthesize.js');

const result = await synthesize({
  text: '合成文本',
  voice: 'Chinese (Mandarin)_Warm_Bestie',
  speed: 1.0,
  volume: 1.0,
  pitch: 0,
  emotion: 'calm',
  format: 'mp3',
  sampleRate: 32000,
  bitrate: 128000,
  channel: 1,
  output: `${OUTPUT_DIR}/assets/narration.mp3`
});
// result: { filePath, audioLength, sampleRate, bitrate, format, channel, usageCharacters }
```

### 方式三：从 storyboard.json 读取 TTS 参数

本 Skill 的参数设计兼容 `poetry-video-creator` 的 `storyboard.json` 中 `tts_params` 字段：

```json
{
  "tts_params": {
    "voice_id": "Chinese (Mandarin)_Warm_Bestie",
    "speed": 1.0,
    "volume": 5.0,
    "pitch": 0
  }
}
```

映射关系：
- `voice_id` → `--voice`
- `speed` → `--speed`
- `volume` → `--volume`（注意：storyboard中为1-10范围，API为0.1-2.0，脚本自动转换）
- `pitch` → `--pitch`

## 常见错误

| 错误 | 原因 | 解决方案 |
|-----|------|---------|
| 未配置 API Key | 缺少认证信息 | 按配置说明设置 API Key |
| 认证失败 (401) | API Key 无效或过期 | 检查或重新生成 API Key |
| 请求过于频繁 (429) | 超过限流配额 | 等待后重试 |
| 参数错误 (400) | 参数格式不正确 | 检查文本和参数设置 |
| 文本过长 | 超过 10000 字符 | 分段合成后合并 |

## 参考资料

- API 参考：https://platform.minimaxi.com/docs/api-reference/speech-t2a-http
- 控制台：https://platform.minimaxi.com/user-center/basic-information/interface-key
- 错误码：https://platform.minimaxi.com/docs/api-reference/errorcode
- 速率限制：https://platform.minimaxi.com/docs/guides/rate-limits
