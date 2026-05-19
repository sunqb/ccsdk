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


def _log_stderr_line(text: str) -> None:
    lowered = text.lower()
    if "traceback" in lowered or "error:" in lowered or lowered.startswith("error"):
        logger.error("[DockerSandbox stderr] %s", text)
    elif "warning" in lowered or lowered.startswith("warn"):
        logger.warning("[DockerSandbox stderr] %s", text)
    elif "debug:" in lowered or lowered.startswith("debug"):
        logger.debug("[DockerSandbox stderr] %s", text)
    else:
        logger.info("[DockerSandbox stderr] %s", text)


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
        sandbox_home: Path | None = None,
        request: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        if settings.sandbox_runtime != "docker":
            raise ValueError(f"Unsupported SANDBOX_RUNTIME: {settings.sandbox_runtime}")

        sandbox_root = sandbox_root.resolve()
        container_name = _container_name(session_id)
        container_home = "/sandbox/.home"
        if sandbox_home is not None:
            sandbox_home = sandbox_home.resolve()
            if not sandbox_home.is_relative_to(sandbox_root):
                raise ValueError("Invalid sandbox home path")
            rel_home = sandbox_home.relative_to(sandbox_root).as_posix()
            container_home = f"/sandbox/{rel_home}"

        cmd = self._build_command(
            container_name=container_name,
            sandbox_root=sandbox_root,
            container_home=container_home,
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
                    _log_stderr_line(text)
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

    def _build_command(
        self,
        *,
        container_name: str,
        sandbox_root: Path,
        container_home: str,
    ) -> list[str]:
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
            "-v",
            f"{sandbox_root}:/sandbox:rw",
            "-w",
            "/app",
            "-e",
            "WORK_DIR=/sandbox/workspace",
            "-e",
            "SKILLS_DIR=/sandbox/.claude/skills",
            "-e",
            f"HOME={container_home}",
            "-e",
            f"XDG_CONFIG_HOME={container_home}/.config",
            "-e",
            f"XDG_CACHE_HOME={container_home}/.cache",
            "-e",
            f"XDG_DATA_HOME={container_home}/.local/share",
            "-e",
            f"CLAUDE_CONFIG_DIR={container_home}/.claude",
            settings.sandbox_image,
            "python",
            "-m",
            "app.sandbox_worker",
        ]
        if settings.sandbox_read_only_rootfs:
            cmd.insert(3, "--read-only")
        return cmd


docker_sandbox_runner = DockerSandboxRunner()
