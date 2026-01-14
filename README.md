# CC Agent SDK

基于 Claude Agent SDK (Python) 的 Agent 服务，完全遵循 [cc-agent-sdk](https://github.com/Auto-200/cc-agent-sdk) 设计理念。

## 特性

- ✅ **完全兼容 cc-agent-sdk API**：实现所有核心端点
- ✅ **Skills 自动匹配**：Claude 根据 description 自动调用 Skills
- ✅ **SSE 流式响应**：实时推送 Agent 执行事件
- ✅ **会话管理**：支持 `conversationId` 进行会话继续
- ✅ **请求级配置覆盖**：支持 `model`、`baseURL`、`apiKey` 覆盖
- ✅ **中文支持**：正确处理中文输出编码

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/sunqb/ccsdk.git
cd ccsdk
```

### 2. 安装依赖

```bash
# 使用 uv (推荐)
uv pip install -r requirements.txt

# 或使用 pip
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
vim .env
```

必填配置：
```env
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_BASE_URL=https://api.anthropic.com  # 可选
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
```

### 4. 启动服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. 测试 API

```bash
curl -X POST http://localhost:8000/agent-sdk/stream \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello, Claude!"}'
```

## 核心架构

### 完全遵循 cc-agent-sdk 设计

```
┌─────────────────────────────────────────────────┐
│                   Client                        │
└─────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│              FastAPI Application                │
│                                                 │
│  /agent-sdk/stream    - 统一调用入口            │
│  /agent-sdk/history   - 历史记录                │
│  /agent-sdk/projects  - 项目列表                │
│  /agent-sdk/conversations - 会话列表            │
│                                                 │
│  /skills              - Skills 管理 (查询/创建)  │
│                                                 │
└─────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│           Claude Agent SDK (Python)             │
│                                                 │
│  • settingSources: ["project"]                  │
│  • 从 .claude/skills/ 加载 Skills               │
│  • Claude 根据 description 自动匹配             │
│                                                 │
└─────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│            Anthropic Claude API                 │
└─────────────────────────────────────────────────┘
```

## Skills 使用方式

### Skills 自动加载

Skills 存放在 `.claude/skills/` 目录，SDK 会自动加载：

```
.claude/skills/
├── Topic_Planning/
│   └── SKILL.md
└── example/
    └── SKILL.md
```

### SKILL.md 格式

```markdown
---
name: Topic_Planning
description: 选题策划主入口 - 识别策划场景，引导用户进入对应的专项Skill流程
version: 1.0.0
tags: [topic, planning, router]
---

# 选题策划主入口

## 核心任务
作为选题策划系统的总入口，负责...
```

### Skills 自动匹配机制

**无需手动指定 Skill**，Claude 会自动判断：

```bash
# 用户发送自然语言请求
curl -X POST http://localhost:8000/agent-sdk/stream \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "《长安的荔枝》选题",
    "cwd": "/path/to/project"
  }'

# Claude 自动：
# 1. 识别到 "选题" 关键词
# 2. 匹配 Topic_Planning skill 的 description
# 3. 决定是否调用该 Skill
# 4. 如果匹配度高，自动调用
```

**设计哲学**：完全信任 Claude 的判断能力，不需要人工指定 Skill 名称。

## API 端点

### 核心端点

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/agent-sdk/stream` | 流式查询 (SSE) |
| GET | `/agent-sdk/history` | 查询会话历史 |
| GET | `/agent-sdk/projects` | 列出所有项目 |
| GET | `/agent-sdk/conversations` | 列出所有会话 |

### Skills 管理端点

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/skills` | 列出所有 Skills |
| GET | `/skills/{name}` | 获取 Skill 详情 |
| GET | `/skills/{name}/content` | 获取 Skill 内容 |
| POST | `/skills` | 创建新 Skill |
| DELETE | `/skills/{name}` | 删除 Skill |

**注意**：没有 `/skills/{name}/invoke` 端点，因为 Skills 通过 `/agent-sdk/stream` 自动调用。

### POST /agent-sdk/stream

**请求体:**
```json
{
  "prompt": "用户提示词",
  "conversationId": "会话ID (可选)",
  "cwd": "/path/to/project",
  "settingSources": ["project"],
  "model": "claude-sonnet-4-5-20250929",
  "resultMode": "full",
  "eventMode": "full",
  "options": {
    "allowedTools": null,
    "maxTurns": 10
  }
}
```

**可选参数说明：**
- `eventMode=full`：输出完整事件流（默认，尽量与 Claude Code CLI/SDK 保持一致）
- `eventMode=text_only`：仅输出 `content_block_delta/text_delta`（并保留 `stream_event/end` 与 `error`）；该模式下服务会强制 `resultMode=none`，避免最后的全量 `result`

**响应 (text/event-stream):**
```
data: {"type": "stream_event", "subtype": "start", "conversationId": "xxx"}

data: {"type": "stream_event", "subtype": "init", "data": {...}, "conversationId": "xxx"}

data: {"type": "content_block_delta", "subtype": "text_delta", "data": {"text": "你好！"}, "conversationId": "xxx"}

data: {"type": "result", "subtype": "success", "data": {"result": "..."}, "conversationId": "xxx"}
```

## 环境变量

| 变量名 | 描述 | 默认值 | 必填 |
|--------|------|--------|------|
| `ANTHROPIC_API_KEY` | Anthropic API Key | - | ✅ |
| `ANTHROPIC_AUTH_TOKEN` | 同 API_KEY | - | 否 |
| `ANTHROPIC_BASE_URL` | API Base URL | - | 否 |
| `ANTHROPIC_MODEL` | 使用的模型 | `claude-sonnet-4-5-20250929` | 否 |
| `AGENT_SDK_API_KEY` | API 认证密钥 | - | 否 |
| `AGENT_SDK_STREAM_RESULT_MODE` | `/agent-sdk/stream` 的 result(success) 输出模式：`full|empty|none` | `full` | 否 |
| `AGENT_SDK_STREAM_EVENT_MODE` | `/agent-sdk/stream` 的事件输出模式：`full|text_only` | `full` | 否 |
| `HOST` | 服务监听地址 | `0.0.0.0` | 否 |
| `PORT` | 服务监听端口 | `8000` | 否 |
| `WORK_DIR` | 工作目录 | 当前目录 | 否 |
| `SKILLS_DIR` | Skills 目录 | `./.claude/skills` | 否 |

## 项目结构

```
ccsdk/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置管理
│   ├── auth.py              # API Key 认证
│   ├── models/              # 数据模型
│   │   ├── request.py
│   │   └── response.py
│   ├── services/            # 业务逻辑
│   │   ├── agent.py         # Agent 服务
│   │   ├── session.py       # 会话管理
│   │   ├── skills.py        # Skills 管理
│   │   └── history.py       # 历史记录
│   └── routers/             # API 路由
│       ├── agent_sdk.py     # /agent-sdk/* 端点
│       └── skills.py        # /skills/* 端点
│
├── .claude/
│   └── skills/              # Skills 目录
│       ├── Topic_Planning/
│       │   └── SKILL.md
│       └── example/
│           └── SKILL.md
│
├── .env                     # 环境变量
├── requirements.txt         # Python 依赖
├── pyproject.toml          # 项目配置
└── README.md               # 项目文档
```

## 关键实现细节

### 1. API Key 配置

支持 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_AUTH_TOKEN` 两种环境变量：

```python
# config.py
anthropic_api_key: str = field(
    default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
)
```

### 2. 环境变量继承

SDK 子进程需要完整的环境变量：

```python
# agent.py
env = dict(os.environ)  # 继承所有环境变量
env["ANTHROPIC_API_KEY"] = effective_api_key
env["ANTHROPIC_BASE_URL"] = effective_base_url
```

### 3. 中文编码修复

SSE 响应中正确显示中文：

```python
# agent.py
def to_sse(self) -> str:
    return f"data: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"
```

### 4. 默认工具配置

使用 SDK 默认工具集，不限制为 `["Skill"]`：

```python
# agent_sdk.py
tools = allowed_tools if allowed_tools is not None else None
```

### 5. 设置加载

默认只加载项目级别配置，避免用户配置冲突：

```python
# agent.py
effective_setting_sources = setting_sources if setting_sources is not None else ["project"]
```

## 常见问题

### Q: 如何让 Claude 调用我的 Skill？

确保 SKILL.md 的 `description` 字段准确描述功能，Claude 会根据用户 prompt 自动匹配。

### Q: Skills 不被调用怎么办？

1. 检查 `settingSources` 是否包含 `"project"`
2. 检查 `.claude/skills/` 目录下是否有 SKILL.md
3. 确认 SKILL.md 的 YAML frontmatter 格式正确
4. 查看 init 事件中的 `skills` 字段是否包含你的 Skill

### Q: 中文显示为 \uXXXX 怎么办？

最新版本已修复，确保使用 `ensure_ascii=False` 序列化 JSON。

### Q: API 401 错误？

检查 `ANTHROPIC_API_KEY` 是否正确设置，SDK 子进程是否能访问该环境变量。

### Q: 如何调试 Skills 加载？

检查服务启动日志：
```
Loaded 2 skills from ./.claude/skills
```

查看 init 事件的 `skills` 字段：
```json
{
  "skills": ["Topic_Planning", "example"]
}
```

## 与 cc-agent-sdk 对比

| 功能 | cc-agent-sdk | 本实现 |
|------|--------------|--------|
| 语言 | TypeScript | Python |
| 框架 | Bun | FastAPI |
| Skills 加载 | ✅ SDK 自动加载 | ✅ SDK 自动加载 |
| Skills 匹配 | ✅ Claude 自动 | ✅ Claude 自动 |
| SSE 流式响应 | ✅ | ✅ |
| 会话管理 | ✅ | ✅ |
| 中文支持 | ✅ | ✅ |
| API 端点 | `/agent-sdk/*` | `/agent-sdk/*` |
| Skills 管理 | 无独立端点 | `/skills/*` |

## 开发

### 安装开发依赖

```bash
pip install -r requirements.txt
```

### 运行测试

```bash
pytest
```

### 代码格式化

```bash
black app/
ruff check app/
```

## 部署

### Docker

```bash
docker build -t ccsdk .
docker run -d -p 8000:8000 \
  -e ANTHROPIC_API_KEY=xxx \
  ccsdk
```

### Docker Compose

```bash
docker-compose up -d
```

## 许可证

MIT

## 贡献

欢迎提交 Issue 和 Pull Request！
