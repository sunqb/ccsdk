---
name: seedream-ark
description: Generate AI images using Volcengine Seedream 5.0 lite model. Supports text-to-image (T2I), image editing (I2I), multi-image fusion, sequential image generation, and web-search-enhanced generation. Use this skill when the user wants to create, generate, or edit images with the latest Seedream 5.0 model.
official: true
version: 1.0.0
---

# ────────────────────────────────────────────────────────
# 路径推算规则（Claude 执行任意命令前均应遵守）
# ────────────────────────────────────────────────────────
# SKILLS_ROOT：技能脚本根目录
#   本 SKILL.md 的绝对路径 → 取父目录(seedream-ark) → 再取上级 = SKILLS_ROOT
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

# Seedream 5.0 图片生成

使用火山引擎 Seedream 5.0 lite 模型生成高质量 AI 图片，支持文本生成图片（T2I）、图片编辑（I2I）、多图融合、组图生成、联网搜索增强等多种创作模式。

> **Seedream 5.0 lite 特有功能**：
> - 联网搜索增强：融合实时网络信息
> - PNG 输出格式：支持无损图片输出
> - 组图生成：一次生成最多 15 张关联图片

## 配置

Seedream 5.0 使用火山方舟统一 API Key，与 Seedance 视频生成共用同一配置。

### 方式一：在应用中配置（推荐）

在 智灵助手 设置中找到「媒体生成」部分，开启「火山方舟」并配置 API Key。

### 方式二：配置文件

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

### 1. 文本生成图片（T2I）

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "一只可爱的橘色小猫坐在窗台上，阳光洒在身上" \
  --output "$OUTPUT_DIR/cute_cat.jpg"
```

### 1b. 带负向提示词（排除不想要的元素）

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "traditional Chinese ink-wash painting, a scholar in white robe by the river" \
  --negative-prompt "xianxia style, glowing particles, modern clothing, neon lights, internet celebrity face, V-shaped face, fluorescent colors, CG plastic texture, armor, magical artifacts" \
  --output "$OUTPUT_DIR/scholar.jpg"
```

### 2. 图片编辑（I2I）

基于已有图片进行编辑：

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "将背景改为海边日落场景" \
  --image "$OUTPUT_DIR/photo.jpg" \
  --output "$OUTPUT_DIR/edited_photo.jpg"
```

### 3. 多图融合

融合多张参考图的特征：

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "将图1的服装换为图2的服装" \
  --image "$OUTPUT_DIR/person.jpg" \
  --image "$OUTPUT_DIR/clothes.jpg" \
  --output "$OUTPUT_DIR/fusion_result.jpg"
```

### 4. 组图生成

一次生成多张关联图片：

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "生成一组共4张连贯插画，展现庭院一角的四季变迁" \
  --sequential \
  --max-images 4 \
  --output "$OUTPUT_DIR/seasons.jpg"
```

输出文件会自动编号：`seasons_1.jpg`, `seasons_2.jpg`, `seasons_3.jpg`, `seasons_4.jpg`

### 5. 联网搜索增强生成

融合实时网络信息（Seedream 5.0 特有）：

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "搜索近期热门的白鸭子形象，设计成巨型装置艺术" \
  --search \
  --output "$OUTPUT_DIR/search_result.jpg"
```

### 6. PNG 无损输出

```bash
OUTPUT_DIR="${CLAUDE_OUTPUT_DIR:-$PWD}"
node "$SKILLS_ROOT/seedream-ark/scripts/generate_image.js" \
  --prompt "产品渲染图，需要保留精确细节" \
  --format png \
  --output "$OUTPUT_DIR/product.png"
```

## 参数说明

### 必需参数

| 参数 | 说明 | 示例 |
|-----|------|------|
| `--prompt` | 图片描述提示词（必需） | "一只可爱的小猫" |

### 可选参数

| 参数 | 说明 | 默认值 | 可选值 |
|-----|------|-------|--------|
| `--image` | 参考图片路径（可多次使用） | 无 | 本地文件路径或URL |
| `--negative-prompt` | 负向提示词（排除不想要的元素） | 无 | 逗号分隔的关键词 |
| `--model` | 模型ID | `doubao-seedream-5-0-260128` | 固定使用 5.0 lite |
| `--size` | 图片尺寸 | `2K` | `2K`, `3K` 或具体像素如 `2048x2048` |
| `--format` | 输出格式 | `jpeg` | `jpeg`, `png` |
| `--no-watermark` | 不添加水印 | 否 | 标志参数 |
| `--sequential` | 生成组图 | 否 | 标志参数 |
| `--max-images` | 组图数量上限 | 15 | 1-15 |
| `--search` | 启用联网搜索 | 否 | 标志参数 |
| `--output` | 输出文件路径 | `generated_image.jpg` | 文件路径 |

## 尺寸规格

### 2K 分辨率推荐值

| 宽高比 | 像素值 |
|-------|--------|
| 1:1 | 2048x2048 |
| 4:3 | 2304x1728 |
| 3:4 | 1728x2304 |
| 16:9 | 2848x1600 |
| 9:16 | 1600x2848 |
| 21:9 | 3136x1344 |

### 3K 分辨率推荐值

| 宽高比 | 像素值 |
|-------|--------|
| 1:1 | 3072x3072 |
| 4:3 | 3456x2592 |
| 3:4 | 2592x3456 |
| 16:9 | 4096x2304 |
| 9:16 | 2304x4096 |
| 21:9 | 4704x2016 |

## 支持的图片格式

**输入图片**：jpeg, png, webp, bmp, tiff, gif, heic
**输出格式**：jpeg, png

## 提示词技巧

### 优秀提示词的特点

1. **清晰的主体描述** - 说明画面的主要内容
2. **具体的风格指定** - 写实、卡通、赛博朋克等
3. **细节补充** - 色彩、光线、氛围等
4. **构图说明** - 特写、全景、俯视等视角

### 提示词模板

```
[风格]，[主体描述]，[细节补充]，[构图/氛围]
```

**示例**：
```
写实风格，一只橘色小猫坐在木制窗台上，阳光从左侧洒进来，温暖治愈的氛围，特写构图
```

## 配额和限制

- **IPM（每分钟图片数）**: 500 张/分钟
- **组图数量**: 最多 15 张
- **参考图数量**: 最多 14 张
- **提示词长度**: 建议不超过 300 汉字或 600 英文单词
- **图片 URL 有效期**: 24 小时

## 常见错误

| 错误 | 原因 | 解决方案 |
|-----|------|---------|
| 未配置 API Key | 缺少认证信息 | 按配置说明设置 API Key |
| 认证失败 (401) | API Key 无效或过期 | 检查或重新生成 API Key |
| 请求过于频繁 (429) | 超过限流配额 | 等待 1 分钟后重试 |
| 参数错误 (400) | 参数格式不正确 | 检查提示词和参数设置 |

## 参考资料

- API 参考：https://www.volcengine.com/docs/82379/1666945
- 控制台：https://console.volcengine.com/ark
- API Key 管理：https://console.volcengine.com/ark/region:ark+cn-beijing/apikey