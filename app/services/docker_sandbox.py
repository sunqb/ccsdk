"""
Docker 沙箱执行器。
"""
import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from ..config import settings

logger = logging.getLogger(__name__)


_CONTAINER_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _container_name(session_id: str) -> str:
    safe = _CONTAINER_SAFE_RE.sub("-", session_id).strip(".-")[:36] or "session"
    return f"ccsdk-sandbox-{safe}-{uuid.uuid4().hex[:8]}"


class DockerSandboxRunner:
    """在受限 Docker 容器中运行单次 Agent 查询。"""

    @property
    def enabled(self) -> bool:
        return settings.sandbox_enabled

    async def run(
        self,
        *,
        session_id: str,
        sandbox_root: Path,
        request: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        if settings.sandbox_runtime != "docker":
            raise ValueError(f"Unsupported SANDBOX_RUNTIME: {settings.sandbox_runtime}")

        sandbox_root = sandbox_root.resolve()
        container_name = _container_name(session_id)
        cmd = self._build_command(
            container_name=container_name,
            sandbox_root=sandbox_root,
        )
        logger.info("[DockerSandbox] run: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        async def collect_stderr() -> list[str]:
            lines: list[str] = []
            async for raw in process.stderr:
                text = raw.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.error("[DockerSandbox stderr] %s", text)
                    lines.append(text)
            return lines

        stderr_task = asyncio.create_task(collect_stderr())
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
        process.stdin.write(payload)
        await process.stdin.drain()
        process.stdin.close()

        try:
            async with asyncio.timeout(settings.sandbox_timeout_seconds):
                async for raw in process.stdout:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("[DockerSandbox stdout] non-json line: %s", line)
                        continue
                    if isinstance(event, dict):
                        yield event

                return_code = await process.wait()
        except TimeoutError:
            process.kill()
            await process.wait()
            await self._remove_container(container_name)
            yield {
                "type": "error",
                "subtype": None,
                "data": {"message": "Sandbox execution timed out"},
                "conversationId": session_id,
            }
            return

        stderr_lines = await stderr_task
        if return_code != 0:
            yield {
                "type": "error",
                "subtype": None,
                "data": {
                    "message": "Sandbox container failed",
                    "returnCode": return_code,
                    "stderr": "\n".join(stderr_lines[-80:]),
                },
                "conversationId": session_id,
            }

    async def _remove_container(self, container_name: str) -> None:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()

    def _build_command(self, *, container_name: str, sandbox_root: Path) -> list[str]:
        cmd = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            container_name,
            "--user",
            f"{settings.sandbox_uid}:{settings.sandbox_gid}",
            "--network",
            settings.sandbox_network,
            "--memory",
            settings.sandbox_memory,
            "--cpus",
            settings.sandbox_cpus,
            "--pids-limit",
            str(settings.sandbox_pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            f"/tmp:rw,nosuid,nodev,noexec,size={settings.sandbox_tmpfs_size}",
            "--tmpfs",
            (
                f"/home/sandbox:rw,nosuid,nodev,size={settings.sandbox_tmpfs_size},"
                f"uid={settings.sandbox_uid},gid={settings.sandbox_gid},mode=700"
            ),
            "-v",
            f"{sandbox_root}:/sandbox:rw",
            "-w",
            "/app",
            "-e",
            "WORK_DIR=/sandbox/workspace",
            "-e",
            "SKILLS_DIR=/sandbox/.claude/skills",
            "-e",
            "HOME=/home/sandbox",
            "-e",
            "XDG_CONFIG_HOME=/home/sandbox/.config",
            "-e",
            "XDG_CACHE_HOME=/home/sandbox/.cache",
            "-e",
            "XDG_DATA_HOME=/home/sandbox/.local/share",
            "-e",
            "CLAUDE_CONFIG_DIR=/home/sandbox/.claude",
            settings.sandbox_image,
            "python",
            "-m",
            "app.sandbox_worker",
        ]
        if settings.sandbox_read_only_rootfs:
            cmd.insert(3, "--read-only")
        return cmd


docker_sandbox_runner = DockerSandboxRunner()
