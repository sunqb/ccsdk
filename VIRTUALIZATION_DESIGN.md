# Docker 沙箱虚拟化方案设计

本文档说明当前项目的虚拟化隔离方案，包括架构、请求链路、文件系统、容器安全参数、DoD/DinD 区别、性能影响、部署前置条件和后续扩展方向。

## 目标

当前服务会让 Claude Agent SDK / Claude Code CLI 执行工具调用和 Skill 脚本。普通目录隔离只能控制文件输出路径，不能阻止工具调用读取其他目录或影响 API 服务运行环境。

本方案的目标是：

- API 服务只负责鉴权、会话管理、虚拟空间准备和 SSE 转发。
- 每次 Agent 请求都在一个一次性 Docker 沙箱容器中执行。
- 登录用户按 `spaceId` 隔离数据空间。
- 同一用户空间内，不同 `conversationId` 的 Claude HOME 和 resume 历史分开存储。
- 容器只挂载当前用户空间，不能看到其他用户空间。
- 对容器进行 CPU、内存、进程数、权限和根文件系统写入限制。

## 核心结论

当前方案不是完整虚拟机，而是 Docker 容器隔离：

```text
Docker 一次性容器
+ bind mount 用户空间
+ cgroups 资源限制
+ Linux namespace 隔离
+ 只读 rootfs
+ 非 root 用户
+ capabilities 收敛
```

当前 API 服务本身也可以运行在 Docker 中。它通过容器内的 `docker` CLI 访问宿主机 `/var/run/docker.sock`，让宿主 Docker daemon 创建 sandbox 容器。这是 Docker-outside-of-Docker，不是 Docker-in-Docker。

## 术语

| 名称 | 含义 |
|------|------|
| `spaceId` | 用户/租户数据空间 ID。登录用户建议传稳定用户 ID 或其哈希值。 |
| `conversationId` | 一条对话的 ID，用于 Claude resume 和会话历史隔离。 |
| `workspace` | 当前 `spaceId` 下共享业务产物目录。 |
| `.home` | 当前 `conversationId` 的 Claude HOME，保存 CLI 配置、缓存、`.jsonl` 历史。 |
| API 容器 | 运行 FastAPI 服务的主容器。 |
| sandbox 容器 | 每次请求临时创建的 Agent 执行容器。 |
| DoD | Docker-outside-of-Docker，容器内 Docker CLI 调宿主 Docker daemon。 |
| DinD | Docker-in-Docker，容器内再运行一个 Docker daemon。 |

## 总体架构

```text
Client
  |
  | POST /agent-sdk/stream
  | { spaceId, conversationId, prompt, options }
  v
FastAPI API 服务
  |
  | 1. SessionManager 维护 conversationId -> resume_id
  | 2. VirtualSpaceManager 准备 <WORK_DIR>/virtual_spaces/<safe-space-key>
  | 3. DockerSandboxRunner 执行 docker run
  v
宿主 Docker daemon
  |
  | 创建一次性 sandbox 容器
  v
Sandbox 容器
  |
  | python -m app.sandbox_worker
  | Claude Agent SDK / Claude Code CLI
  v
模型 API
```

组件职责：

| 组件 | 文件 | 职责 |
|------|------|------|
| API 路由 | `app/routers/agent_sdk.py` | 接收 `/agent-sdk/stream` 请求，解析 `spaceId`、`conversationId` 和 options。 |
| Agent 编排 | `app/services/agent.py` | 选择虚拟空间，组装 sandbox 请求，转发事件流。 |
| 虚拟空间 | `app/services/virtual_space.py` | 准备 `spaceId` 级目录、共享 workspace、会话级 `.home`。 |
| Docker 执行器 | `app/services/docker_sandbox.py` | 拼装并执行 `docker run`，读取容器 stdout JSON 事件。 |
| 容器 worker | `app/sandbox_worker.py` | 容器内入口，调用 Agent SDK 并逐行输出事件。 |
| 镜像 | `Dockerfile` | API 服务和 sandbox 共用镜像，内置 Python 依赖、应用代码、Docker CLI。 |
| Compose | `docker-compose.yml` | 本地和单机部署编排，挂载 Docker socket 与 `WORK_DIR`。 |

## 隔离粒度

虚拟化模式下空间选择规则固定为：

```text
space key = spaceId or conversationId
```

含义：

- 传 `spaceId`：按用户空间隔离。适合登录用户。
- 不传 `spaceId`：按 `conversationId` 隔离。适合未登录临时会话。
- `cwd` 不参与虚拟化空间选择，只保留给非虚拟化模式作为本地工作目录。

同一个 `spaceId` 内：

- 多个 `conversationId` 共享 `/sandbox/workspace`，因此同一用户多个会话可以读取自己的历史产物。
- 每个 `conversationId` 使用独立 `/sandbox/sessions/<safe-conversationId>/.home`，因此 Claude resume 历史按对话隔离。

不同 `spaceId` 之间：

- 宿主目录不同。
- sandbox 容器只挂载当前 `spaceId` 的目录。
- 容器文件系统层面看不到其他 `spaceId`。

## 文件系统设计

宿主侧目录：

```text
<WORK_DIR>/virtual_spaces/<safe-space-key>/
├── app/
├── pyproject.toml
├── requirements.txt
├── README.md
├── .claude/
│   ├── CLAUDE.md
│   ├── settings.json
│   └── skills/
├── workspace/
│   ├── assets/
│   └── output/
└── sessions/
    ├── <safe-conversationId-a>/
    │   └── .home/
    │       └── .claude/
    │           └── projects/
    └── <safe-conversationId-b>/
        └── .home/
            └── .claude/
                └── projects/
```

容器内路径：

```text
/sandbox
├── .claude/skills
├── workspace
└── sessions/<safe-conversationId>/.home

HOME=/sandbox/sessions/<safe-conversationId>/.home
XDG_CONFIG_HOME=/sandbox/sessions/<safe-conversationId>/.home/.config
XDG_CACHE_HOME=/sandbox/sessions/<safe-conversationId>/.home/.cache
XDG_DATA_HOME=/sandbox/sessions/<safe-conversationId>/.home/.local/share
CLAUDE_CONFIG_DIR=/sandbox/sessions/<safe-conversationId>/.home/.claude
WORK_DIR=/sandbox/workspace
SKILLS_DIR=/sandbox/.claude/skills
```

## 请求执行流程

1. 客户端请求：

```json
{
  "spaceId": "user-123",
  "conversationId": "chat-abc",
  "prompt": "生成一个视频脚本",
  "options": {
    "disallowedTools": ["Bash"],
    "maxTurns": 1
  }
}
```

2. API 服务生成空间键：

```text
space key = spaceId or conversationId
session key = conversationId or uuid
```

3. `VirtualSpaceManager` 准备目录：

```text
virtual_spaces/<safe-space-key>/workspace
virtual_spaces/<safe-space-key>/sessions/<safe-conversationId>/.home
virtual_spaces/<safe-space-key>/.claude/skills
```

4. `DockerSandboxRunner` 创建一次性容器。

5. 容器内 `sandbox_worker` 调用 Claude Agent SDK。

6. 容器 stdout 输出 AgentEvent JSON 行，API 服务转为 SSE。

7. 请求结束后容器通过 `--rm` 自动删除，文件留在宿主 `WORK_DIR`。

## Docker 运行参数

当前 sandbox 容器由 `docker run` 创建，核心参数如下：

```bash
docker run --rm -i \
  --read-only \
  --user <SANDBOX_UID>:<SANDBOX_GID> \
  --network <SANDBOX_NETWORK> \
  --memory <SANDBOX_MEMORY> \
  --cpus <SANDBOX_CPUS> \
  --pids-limit <SANDBOX_PIDS_LIMIT> \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=<SANDBOX_TMPFS_SIZE> \
  -v <virtual-space-root>:/sandbox:rw \
  -w /app \
  -e WORK_DIR=/sandbox/workspace \
  -e SKILLS_DIR=/sandbox/.claude/skills \
  -e HOME=/sandbox/sessions/<safe-conversationId>/.home \
  -e XDG_CONFIG_HOME=/sandbox/sessions/<safe-conversationId>/.home/.config \
  -e XDG_CACHE_HOME=/sandbox/sessions/<safe-conversationId>/.home/.cache \
  -e XDG_DATA_HOME=/sandbox/sessions/<safe-conversationId>/.home/.local/share \
  -e CLAUDE_CONFIG_DIR=/sandbox/sessions/<safe-conversationId>/.home/.claude \
  ccsdk-sandbox:latest python -m app.sandbox_worker
```

模型配置、输出目录和业务密钥不会通过 `docker run -e` 全量展开，而是由 API 服务写入 worker stdin 的请求 JSON。`app/sandbox_worker.py` 读取 `request.env` 后再写入 `os.environ`，供 Claude Agent SDK、Claude CLI 和 skills 使用。

Docker 沙箱中 `CLAUDE_OUTPUT_DIR` 固定为容器内路径：

```text
/sandbox/workspace
```

它对应宿主路径：

```text
<WORK_DIR>/virtual_spaces/<safe-space-key>/workspace
```

如果宿主配置：

```env
CLAUDE_OUTPUT_DIR=<WORK_DIR>
CLAUDE_OUTPUT_BASE_URL=http://your-server/files/ccsdk
```

API 服务会在启动沙箱前把 `CLAUDE_OUTPUT_BASE_URL` 改写为当前 workspace 的 URL 前缀：

```text
http://your-server/files/ccsdk/virtual_spaces/<safe-space-key>/workspace
```

这样 skill 仍然按 `/sandbox/workspace` 写文件，前端仍然拿到可直接访问的 HTTP URL。

业务变量采用显式白名单透传：

```env
SANDBOX_ENV_PASSTHROUGH=ARK_API_KEY,MINIMAX_API_KEY
ARK_API_KEY=xxx
MINIMAX_API_KEY=xxx
```

API 服务只会把 `SANDBOX_ENV_PASSTHROUGH` 中列出的变量从自身环境复制到沙箱请求，不会把 API 容器的全部环境变量暴露给一次性沙箱容器。

参数含义：

| 参数 | 作用 |
|------|------|
| `--rm` | 请求结束后自动删除容器。 |
| `-i` | 通过 stdin 向 worker 传入请求 JSON。 |
| `--read-only` | 容器根文件系统只读，防止修改镜像内应用和依赖。 |
| `--user UID:GID` | 非 root 运行。 |
| `--network bridge` | 允许访问模型 API。可设为 `none`，但模型请求会失败。 |
| `--memory` | 限制内存。 |
| `--cpus` | 限制 CPU。 |
| `--pids-limit` | 限制容器内进程数。 |
| `--cap-drop ALL` | 去除 Linux capabilities。 |
| `no-new-privileges` | 禁止进程通过 setuid 等方式获得新权限。 |
| `--tmpfs /tmp` | 临时目录使用内存文件系统，请求结束消失。 |
| `-v <space>:/sandbox:rw` | 只挂载当前用户空间。 |

## DoD 与 DinD

当前使用的是 DoD。

```text
API 容器
  |
  | docker CLI
  | /var/run/docker.sock
  v
宿主 Docker daemon
  |
  v
sandbox sibling 容器
```

DoD 特点：

- API 容器里只需要 Docker CLI。
- 真正创建容器的是宿主 Docker daemon。
- sandbox 容器和 API 容器是同级 sibling 容器。
- 部署简单，性能开销小。
- 安全风险是 Docker socket 权限很高，API 容器相当于能控制宿主 Docker。

DinD 是另一种模式：

```text
API 容器
  |
  v
容器内 Docker daemon
  |
  v
容器内再创建 sandbox 容器
```

DinD 特点：

- 容器内运行一个独立 Docker daemon。
- 通常需要 privileged 或额外内核能力。
- 存储、网络、镜像缓存更复杂。
- CI 场景常见，但生产服务里维护成本更高。

本项目选择 DoD，因为目标是单机或 Docker Compose 部署下快速实现真实执行隔离，避免在 API 容器中维护第二套 Docker daemon。

## 与普通 Docker 服务的区别

普通 Docker 服务：

- 容器长期运行。
- 用于承载一个服务进程。
- 通常挂载固定数据目录。
- 请求都在同一个服务容器内处理。

当前 sandbox：

- 每次 Agent 请求创建一个临时容器。
- 容器只处理一次请求。
- 容器只挂载当前 `spaceId` 的虚拟空间。
- 请求结束容器删除。
- workspace 和 Claude HOME 留在宿主目录，用于文件产物和 resume。

## 性能影响

主要开销：

1. 容器启动开销：每次请求执行 `docker run`，通常是几十到几百毫秒。Docker Desktop / Colima 上可能更高。
2. 模板准备开销：首次或每次请求会复制应用文件、skills、配置文件到虚拟空间。
3. 文件系统开销：bind mount 和目录权限修正有一定成本。

对 LLM 请求而言，模型响应通常是秒级到几十秒，因此 Docker 启动开销不是主要瓶颈。高并发场景下，Docker daemon、CPU、内存和镜像启动会成为瓶颈。

可优化方向：

- 空间模板只初始化一次，按版本增量同步。
- 对高频请求做任务队列和并发限流。
- 针对长任务设置更合理的 `SANDBOX_TIMEOUT_SECONDS`。
- 未来可引入容器池，但需要处理 HOME、workspace、环境变量和进程清理。

## 前置条件

宿主机或部署环境必须满足：

- 已安装 Docker Engine / Docker Desktop / Colima。
- API 服务环境内能执行 `docker` 命令。
- API 服务有权限访问 Docker daemon。
- 如果 API 服务运行在容器内，必须挂载：

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

- API 镜像必须包含 Docker CLI。当前 `Dockerfile` 已安装 `docker-cli`。
- `WORK_DIR` / `VIRTUAL_SPACE_DIR` 必须是宿主 Docker daemon 可 bind mount 的路径。
- `SANDBOX_IMAGE` 必须已经构建：

```bash
docker build -t ccsdk-sandbox:latest .
```

- `SANDBOX_UID` / `SANDBOX_GID` 必须能写入 `WORK_DIR`。
- 模型请求需要网络时，`SANDBOX_NETWORK` 不能设为 `none`。

## Docker Compose 部署要点

当前 `docker-compose.yml` 采用 DoD：

```yaml
services:
  cc-agent-sdk:
    image: ${SANDBOX_IMAGE:-ccsdk-sandbox:latest}
    volumes:
      - ${WORK_DIR:-/tmp/ccsdk-workspace}:${WORK_DIR:-/tmp/ccsdk-workspace}
      - /var/run/docker.sock:/var/run/docker.sock
```

关键点：

- `WORK_DIR` 在 API 容器内和宿主 Docker daemon 视角下必须一致。
- 如果宿主路径是 `/data/ccsdk`，就挂载 `/data/ccsdk:/data/ccsdk`。
- 不要把容器内路径设成 Docker daemon 看不到的路径。
- macOS / Docker Desktop / Colima 需要确认目录已被 Docker 文件共享。

### 输出目录与 Nginx 映射

Docker 沙箱模式下，Skill 运行在一次性 sandbox 容器内，不能直接写宿主路径。容器内输出路径固定为：

```text
/sandbox/workspace
```

宿主真实路径由当前虚拟空间决定：

```text
<WORK_DIR>/virtual_spaces/<safe-space-key>/workspace
```

推荐生产配置：

```env
WORK_DIR=/data/ccsdk
VIRTUAL_SPACE_DIR=/data/ccsdk/virtual_spaces
CLAUDE_OUTPUT_DIR=/data/ccsdk
CLAUDE_OUTPUT_BASE_URL=http://118.195.240.72:62031/files/ccsdk
```

Nginx 暴露 `CLAUDE_OUTPUT_DIR` 对应宿主目录：

```nginx
location /files/ccsdk/ {
    alias /data/ccsdk/;
    add_header Access-Control-Allow-Origin *;
    add_header Accept-Ranges bytes;
}
```

映射结果：

```text
容器内:
/sandbox/workspace/output/final_video.mp4

宿主机:
/data/ccsdk/virtual_spaces/<safe-space-key>/workspace/output/final_video.mp4

前端 URL:
http://118.195.240.72:62031/files/ccsdk/virtual_spaces/<safe-space-key>/workspace/output/final_video.mp4
```

API 服务会根据 `CLAUDE_OUTPUT_DIR` 计算当前 workspace 相对于宿主输出根目录的路径，并把 `CLAUDE_OUTPUT_BASE_URL` 改写成当前 workspace 的 URL 前缀后传给 sandbox worker。因此 Skill 内继续使用：

```text
CLAUDE_OUTPUT_DIR=/sandbox/workspace
CLAUDE_OUTPUT_BASE_URL=http://118.195.240.72:62031/files/ccsdk/virtual_spaces/<safe-space-key>/workspace
```

不要把宿主的 `/data/ccsdk` 或 macOS `/Volumes/...` 直接作为 sandbox 内的 `CLAUDE_OUTPUT_DIR`。容器内只认 `/sandbox/workspace`。

## 路径映射关系

理解路径时要区分三个视角：

| 视角 | 看到的路径 | 说明 |
|------|------------|------|
| API 容器 | `WORK_DIR` / `VIRTUAL_SPACE_DIR` | FastAPI 服务创建虚拟空间时使用的路径。 |
| Docker daemon | `docker run -v <source>:/sandbox` 的 `<source>` | 真正执行 bind mount 的一侧，必须能访问该路径。 |
| 物理机 | macOS / Linux 上能看到的文件位置 | 取决于 Docker daemon 是否直接运行在物理机上。 |

当前 `docker-compose.yml` 默认配置：

```yaml
volumes:
  - ${WORK_DIR:-/tmp/ccsdk-workspace}:${WORK_DIR:-/tmp/ccsdk-workspace}
```

默认环境变量：

```env
WORK_DIR=/tmp/ccsdk-workspace
VIRTUAL_SPACE_DIR=/tmp/ccsdk-workspace/virtual_spaces
SESSION_FILE_PATH=/tmp/ccsdk-workspace/.claude/sessions.json
```

因此容器内部和 Docker daemon 视角都是：

```text
/tmp/ccsdk-workspace
└── virtual_spaces/
    └── <safe-space-key>/
        ├── workspace/
        └── sessions/<safe-conversationId>/.home/
```

### macOS + Colima 本地开发

使用 Colima 时，Docker daemon 运行在 Colima 的 Linux VM 中。此时：

```text
Docker daemon 视角:
/tmp/ccsdk-workspace

API 容器视角:
/tmp/ccsdk-workspace

macOS 普通文件系统:
通常看不到 /tmp/ccsdk-workspace
```

原因是这个 `/tmp/ccsdk-workspace` 位于 Colima VM 内部 Linux 文件系统，不是 macOS 自己的 `/tmp/ccsdk-workspace`。

在当前机器上，Colima VM 的磁盘文件位于：

```text
/Users/sunqb/.colima/_lima/colima/diffdisk
```

映射关系可以理解为：

```text
Colima VM 内部:
/tmp/ccsdk-workspace/virtual_spaces/...

最终落在 macOS 文件:
/Users/sunqb/.colima/_lima/colima/diffdisk
```

`diffdisk` 是 VM 磁盘文件，不能像普通目录一样直接打开到其中的 `/tmp/ccsdk-workspace`。如果需要查看当前默认路径下的数据，可以进入 API 容器或 Colima VM 查看：

```bash
docker exec cc-agent-sdk ls -la /tmp/ccsdk-workspace/virtual_spaces
```

如果 Colima 正在运行，也可以进入 VM：

```bash
colima ssh -- ls -la /tmp/ccsdk-workspace/virtual_spaces
```

如果希望 macOS 物理机直接看到 sandbox 文件，应把 `WORK_DIR` 改成 macOS 可见且 Colima 可共享的目录，例如：

```env
WORK_DIR=/Volumes/samsungssd/code/temp/ccsdk/.runtime/ccsdk-workspace
VIRTUAL_SPACE_DIR=/Volumes/samsungssd/code/temp/ccsdk/.runtime/ccsdk-workspace/virtual_spaces
SESSION_FILE_PATH=/Volumes/samsungssd/code/temp/ccsdk/.runtime/ccsdk-workspace/.claude/sessions.json
```

然后重启：

```bash
docker compose up -d --force-recreate
```

此时路径关系变为：

```text
macOS 物理机:
/Volumes/samsungssd/code/temp/ccsdk/.runtime/ccsdk-workspace

API 容器:
/Volumes/samsungssd/code/temp/ccsdk/.runtime/ccsdk-workspace

sandbox 容器:
/sandbox
```

注意：macOS 路径必须在 Docker Desktop / Colima 允许共享的目录范围内，否则 Docker daemon 会挂载失败或创建空目录。

### Linux 服务器部署

Linux 服务器上 Docker daemon 通常直接运行在物理机上。此时 `WORK_DIR` 就是服务器上的普通目录。

推荐配置：

```env
WORK_DIR=/data/ccsdk
VIRTUAL_SPACE_DIR=/data/ccsdk/virtual_spaces
SESSION_FILE_PATH=/data/ccsdk/.claude/sessions.json
```

对应关系：

```text
Linux 物理机:
/data/ccsdk/virtual_spaces/<safe-space-key>/

API 容器:
/data/ccsdk/virtual_spaces/<safe-space-key>/

sandbox 容器:
/sandbox
```

Compose 必须挂载同一路径：

```yaml
volumes:
  - /data/ccsdk:/data/ccsdk
  - /var/run/docker.sock:/var/run/docker.sock
```

这样 API 容器创建的目录就是宿主 Docker daemon 能 bind mount 的目录，sandbox 容器也能正确看到 `/sandbox`。

### 路径排查命令

查看 compose 最终配置：

```bash
docker compose config
```

查看 API 容器内实际目录：

```bash
docker exec cc-agent-sdk ls -la "$WORK_DIR"
docker exec cc-agent-sdk ls -la "$VIRTUAL_SPACE_DIR"
```

查看 Docker daemon 创建 sandbox 时使用的真实 bind mount：

```bash
docker compose logs --tail=200 cc-agent-sdk | grep 'DockerSandbox] run'
```

日志中类似：

```text
-v /tmp/ccsdk-workspace/virtual_spaces/user-123-<hash>:/sandbox:rw
```

冒号左边就是 Docker daemon 视角下的真实源路径，冒号右边是 sandbox 容器内路径。

推荐生产配置：

```env
WORK_DIR=/data/ccsdk
VIRTUAL_SPACE_DIR=/data/ccsdk/virtual_spaces
SESSION_STORE=file
SESSION_FILE_PATH=/data/ccsdk/.claude/sessions.json

SANDBOX_ENABLED=true
SANDBOX_RUNTIME=docker
SANDBOX_IMAGE=ccsdk-sandbox:latest
SANDBOX_NETWORK=bridge
SANDBOX_MEMORY=2g
SANDBOX_CPUS=1.0
SANDBOX_PIDS_LIMIT=256
SANDBOX_TMPFS_SIZE=256m
SANDBOX_TIMEOUT_SECONDS=900
SANDBOX_READ_ONLY_ROOTFS=true
SANDBOX_UID=1000
SANDBOX_GID=1000
```

## 安全边界

本方案增强的是“用户请求之间”的隔离：

- 用户 A 容器只挂载用户 A 的 `spaceId` 目录。
- 用户 B 容器只挂载用户 B 的 `spaceId` 目录。
- 容器根文件系统只读。
- 容器非 root。
- capabilities 收敛。
- `/tmp` 请求结束即消失。

但需要明确：

- 挂载 `/var/run/docker.sock` 后，API 容器拥有较高 Docker 管理权限。
- API 服务本身必须是可信组件。
- 这不是强安全多租户虚拟机隔离。
- 对不可信代码执行的极高安全场景，应考虑 Firecracker、Kata Containers、gVisor 或远程 Job Runner。

## 常见问题

### 为什么没有 `import docker`？

当前没有使用 Python Docker SDK，而是直接通过标准库启动 Docker CLI：

```python
asyncio.create_subprocess_exec("docker", "run", ...)
```

这样依赖少，行为接近手动 `docker run`，也便于排查日志。

### API 服务在 Docker 里，再 docker run 是否有问题？

没问题。当前是 DoD，不是 DinD。API 容器内的 Docker CLI 调宿主 Docker daemon 创建 sibling sandbox 容器。

### `spaceId` 和 `conversationId` 怎么选？

登录用户：

```json
{
  "spaceId": "user-123",
  "conversationId": "chat-abc"
}
```

未登录临时会话：

```json
{
  "conversationId": "temp-chat-abc"
}
```

### 同一个用户多个对话能互相看到文件吗？

能。同一个 `spaceId` 下共享：

```text
/sandbox/workspace
```

但每个对话的 Claude HOME 分开：

```text
/sandbox/sessions/<conversationId>/.home
```

### `cwd` 还生效吗？

只在非虚拟化模式生效。开启 `SANDBOX_ENABLED=true` 或 `VIRTUAL_SPACE_ENABLED=true` 后，空间选择使用 `spaceId or conversationId`。

### 为什么容器结束后还能继续对话？

容器进程会删除，但 Claude HOME 被写到宿主虚拟空间：

```text
virtual_spaces/<spaceId>/sessions/<conversationId>/.home
```

下次同一 `conversationId` 请求会重新挂载同一目录，并通过 `resume_id` 继续。

## 后续扩展方向

### 运行时扩展

当前只支持：

```env
SANDBOX_RUNTIME=docker
```

可以抽象新的 Runner：

- `DockerSandboxRunner`
- `FirecrackerSandboxRunner`
- `KataSandboxRunner`
- `GVisorSandboxRunner`
- `RemoteJobRunner`

Runner 契约保持一致：

```text
输入：session_id, sandbox_root, sandbox_home, request
输出：AgentEvent 字典流
```

### 更强隔离

可选方向：

- **gVisor**：在容器和内核之间加用户态内核层，增强 syscall 隔离。
- **Kata Containers**：每个容器运行在轻量 VM 中，隔离强于普通容器。
- **Firecracker**：微虚拟机，适合更强多租户边界，但工程复杂度更高。
- **远程 Job Runner**：API 服务只提交任务，执行层独立部署和弹性扩缩容。

### 资源治理

建议增加：

- 每个 `spaceId` 的并发上限。
- 全局 sandbox 容器并发上限。
- 队列排队与超时。
- `workspace` 磁盘配额。
- 会话过期清理。
- 运行日志和容器退出码统计。

### 文件生命周期

当前文件保留在：

```text
<WORK_DIR>/virtual_spaces/<safe-space-key>/
```

后续建议：

- 按 `spaceId` 配额清理。
- 按 `conversationId` 清理过期 `.home`。
- workspace 内产物按业务引用计数或 TTL 清理。
- 静态文件 URL 做鉴权或签名，避免直接暴露用户产物。

## 验证命令

健康检查：

```bash
curl -i http://127.0.0.1:18081/health
```

同一 `spaceId`、不同 `conversationId` 验证：

```bash
curl -N http://127.0.0.1:18081/agent-sdk/stream \
  -H 'Content-Type: application/json' \
  -d '{
    "spaceId": "user-123",
    "conversationId": "chat-a",
    "prompt": "请只回复 A",
    "options": {"disallowedTools": ["Bash"], "maxTurns": 1}
  }'
```

```bash
curl -N http://127.0.0.1:18081/agent-sdk/stream \
  -H 'Content-Type: application/json' \
  -d '{
    "spaceId": "user-123",
    "conversationId": "chat-b",
    "prompt": "请只回复 B",
    "options": {"disallowedTools": ["Bash"], "maxTurns": 1}
  }'
```

预期：

- 两次请求挂载同一个 `virtual_spaces/user-123-<hash>:/sandbox`。
- 两次请求 HOME 分别为：

```text
/sandbox/sessions/chat-a-<hash>/.home
/sandbox/sessions/chat-b-<hash>/.home
```
