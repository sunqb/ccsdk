---
name: seedance-ark
description: Generate AI videos using Volcengine Seedance model (config-based version). Supports text-to-video (T2V), image-to-video (I2V), and audio-synced video generation. Use this skill when the user wants to create or generate videos with Seedance models.
official: true
version: 1.0.0
---

# ────────────────────────────────────────────────────────
# 路径推算规则（Claude 执行任意命令前均应遵守）
# ────────────────────────────────────────────────────────
# SKILLS_ROOT：技能脚本根目录
#   本 SKILL.md 的绝对路径 → 取父目录(seedance-ark) → 再取上级 = SKILLS_ROOT
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
#   FILE_PATH="/actual/generated/file.mp4"
#   OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
#   BASE_URL="${CLAUDE_OUTPUT_BASE_URL:-}"
#   REL="${FILE_PATH#$OUTPUT_DIR}"
#   if [ -n "$BASE_URL" ]; then echo "${BASE_URL}${REL}"; else echo "$FILE_PATH"; fi
#
# 🚫 严格禁止：
#   - 禁止跳过上述 bash 命令、直接在回复里自行拼接或猜测 URL
#   - 禁止使用任何非 CLAUDE_OUTPUT_BASE_URL 来源的域名（含 r2.aityp.com 等）

# Seedance Volc 视频生成

使用火山引擎 Seedance 模型生成高质量 AI 视频，支持文本生成视频（T2V）、图片生成视频（I2V）、音画同步等多种创作模式。支持 Seedance 1.0 / 1.5 / 2.0 三代模型。

> **配置文件版**：此版本从 `~/.phoenixassistantai/media_config.json` 读取配置，无需设置环境变量。

## 配置

Seedance 视频生成使用火山方舟统一 API Key，与 Seedream 图片生成共用同一配置。

### 方式一：在应用中配置（推荐）

在 智灵助手 设置中找到「媒体生成」部分，开启「火山方舟」并配置 API Key。

### 方式二：创建配置文件

创建配置文件 `~/.phoenixassistantai/media_config.json`：

```json
{
  "volcengineArk": {
    "enabled": true,
    "apiKey": "你的API密钥"
  }
}
```

### 方式三：环境变量

```bash
# macOS/Linux
export ARK_API_KEY="你的API密钥"

# Windows PowerShell
$env:ARK_API_KEY="你的API密钥"
```

### 获取 API Key

1. 访问火山方舟控制台：https://console.volcengine.com/ark/region:ark+cn-beijing/apikey
2. 创建新的 API Key
3. 复制密钥并配置

> **注意**：同一个火山方舟 API Key 可以同时用于 Seedream 图片生成和 Seedance 视频生成。

## 使用示例

**路径说明**：下面的示例使用 `$SKILLS_ROOT` 环境变量来引用脚本路径。

### 1. 文本生成视频（T2V）

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedance-ark/scripts/generate_video.js" \
  --prompt "一只小猫在草地上玩耍，阳光明媚，镜头缓缓推进" \
  --duration 5 \
  --output "$OUTPUT_DIR/cat_video.mp4"
```

### 2. 图片生成视频（I2V，单图）

> ⚠️ 当前仅支持单张参考图。

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedance-ark/scripts/generate_video.js" \
  --prompt "女孩睁开眼，温柔地看向镜头，头发被风吹动" \
  --image "$OUTPUT_DIR/girl.jpg" \
  --duration 5 \
  --output "$OUTPUT_DIR/i2v_video.mp4"
```

### 3. 音画同步视频（仅 1.5 pro，单图）

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedance-ark/scripts/generate_video.js" \
  --prompt "镜头围绕人物推镜头拉近，特写人物面部，她正在用京剧唱腔唱'月移花影，疑是玉人来'" \
  --image "$OUTPUT_DIR/actress.jpg" \
  --audio \
  --duration 5 \
  --model "doubao-seedance-1-5-pro-251215" \
  --output "$OUTPUT_DIR/audio_video.mp4"
```

### 4. Seedance 2.0 视频生成

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
# 基础用法
node "$SKILLS_ROOT/seedance-ark/scripts/generate_video.js" \
  --prompt "水墨画风，江南水乡，小桥流水人家，镜头缓缓横移" \
  --model "doubao-seedance-2-0-260128" \
  --duration 8 \
  --output "$OUTPUT_DIR/scene_2.0.mp4"

# 带 seed 复现 + 指定分辨率
node "$SKILLS_ROOT/seedance-ark/scripts/generate_video.js" \
  --prompt "武侠风，竹林中的剑客，衣袂飘飘，镜头推近特写" \
  --image "$OUTPUT_DIR/swordsman.jpg" \
  --model "doubao-seedance-2-0-260128" \
  --duration 10 \
  --resolution 720p \
  --seed 42 \
  --return-last-frame \
  --output "$OUTPUT_DIR/swordsman_scene.mp4"
```

> ⚠️ Seedance 2.0 需显式指定 `--model "doubao-seedance-2-0-260128"`，默认仍为 1.5。

### Seedance 2.0 与 1.x 主要差异

| 能力 | 1.x | 2.0 |
|-----|-----|-----|
| 时长范围 | 2-12s | 4-15s |
| 分辨率 | 自动 | 可选 480p / 720p |
| 随机种子 | 不支持 | `--seed` 可复现 |
| 尾帧返回 | 不支持 | `--return-last-frame` |
| 联网搜索 | 不支持 | `--web-search` |
| 水印 | 默认有 | 默认无 |
| 宽高比 | 4种 | 7种（新增 4:3 / 3:4 / 21:9） |

## 参数说明

### 必需参数

| 参数 | 说明 | 示例 |
|-----|------|------|
| `--prompt` | 视频描述提示词（必需） | "小猫在玩耍" |

### 可选参数

| 参数 | 说明 | 默认值 | 可选值 |
|-----|------|-------|--------|
| `--image` | 参考图片路径（单张） | 无 | 本地文件路径或URL |
| `--model` | 模型ID | `doubao-seedance-1-5-pro-251215` | 见模型列表 |
| `--duration` | 视频时长（秒） | 5 | 2-12（2.0: 4-15） |
| `--ratio` | 宽高比 | `adaptive` | `adaptive`, `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, `21:9` |
| `--audio` | 生成音频（仅1.5/2.0支持） | 否 | 标志参数 |
| `--resolution` | 输出分辨率（仅2.0） | `720p` | `480p`, `720p` |
| `--seed` | 随机种子（仅2.0，用于复现） | 随机 | 整数 |
| `--return-last-frame` | 返回尾帧图片（仅2.0） | 否 | 标志参数 |
| `--web-search` | 启用联网搜索（仅2.0） | 否 | 标志参数 |
| `--no-watermark` | 不添加水印（2.0默认无水印） | 否 | 标志参数 |
| `--output` | 输出文件路径 | `generated_video.mp4` | 文件路径 |
| `--poll-interval` | 状态查询间隔（秒） | 5 | 1-10 |
| `--timeout` | 最大等待时间（秒） | 300 | 60-600 |

## 模型选择

| 模型 | 特点 | 时长范围 | 默认 |
|-----|------|---------|------|
| `doubao-seedance-1-5-pro-251215` | 音画同生，最高质量 | 4-12秒 | ✅ |
| `doubao-seedance-1-0-pro-250528` | 高质量标准版本 | 2-12秒 | |
| `doubao-seedance-1-0-pro-fast-251015` | 快速生成，成本更低 | 2-12秒 | |
| `doubao-seedance-2-0-260128` | 最新一代，多模态参考，视频编辑 | 4-15秒 | |

## 配额和限制

- 免费额度：200万 token
- RPM（每分钟请求数）：600（Pro 系列）、300（Lite 系列）
- 并发数：10（Pro 系列）、5（Lite 系列）
- 视频保存时间：24 小时

## 提示词技巧

### 优秀提示词的特点

1. **清晰的场景描述** - 说明环境、时间、氛围
2. **具体的动作细节** - 描述物体或人物的具体动作
3. **镜头运动** - 说明推拉摇移、特写等镜头语言
4. **风格指定** - 写实、卡通、动漫等风格说明

### 提示词模板

```
[风格]，[场景描述]，[主体动作]，[镜头运动]，[氛围/情绪]
```

## 参考资料

- API 参考：https://www.volcengine.com/docs/82379/1520758
- 控制台：https://console.volcengine.com/ark
- API Key 管理：https://console.volcengine.com/ark/region:ark+cn-beijing/apikey