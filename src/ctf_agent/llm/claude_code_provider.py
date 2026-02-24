"""
Claude Code provider — delegates the entire agent task to Claude Code CLI.

Instead of calling an API and running the tool loop ourselves, we spawn
`claude` as a subprocess. Claude Code connects to the container's MCP server
(configured via .mcp.json) and handles tool use autonomously.

This provider does NOT implement the normal chat() interface for the tool loop.
Instead, it provides a run_task() method that streams Claude Code's output.
"""

import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


@dataclass
class ClaudeCodeEvent:
    """Event from Claude Code subprocess output."""
    event_type: str  # "text", "tool_call", "tool_result", "error", "done"
    data: dict


class ClaudeCodeProvider:
    """
    Runs Claude Code CLI as the agent brain. Claude Code uses the MCP server
    to interact with the container, so the tool loop is handled by Claude Code
    itself — not by our AgentCore.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_turns: Optional[int] = None,
        system_prompt: Optional[str] = None,
        container_api_url: Optional[str] = None,
    ):
        self._model = model
        self._max_turns = max_turns
        self._system_prompt = system_prompt
        self._container_api_url = container_api_url
        self._process: Optional[asyncio.subprocess.Process] = None

        # Verify claude is installed
        if not shutil.which("claude"):
            raise RuntimeError(
                "Claude Code CLI ('claude') not found in PATH. "
                "Install it from https://claude.ai/claude-code"
            )

    def model_name(self) -> str:
        return f"claude-code{f' ({self._model})' if self._model else ''}"

    async def run_task(
        self,
        task: str,
        event_callback: Optional[callable] = None,
    ) -> str:
        """
        Run a task using Claude Code. Streams output via event_callback.
        Returns the final text output.

        Uses `claude -p` (print mode) with --output-format stream-json
        for structured streaming output.
        """
        cmd = ["claude", "-p", "--verbose", "--output-format", "stream-json"]

        if self._model:
            cmd.extend(["--model", self._model])

        if self._max_turns:
            cmd.extend(["--max-turns", str(self._max_turns)])

        if self._system_prompt:
            cmd.extend(["--system-prompt", self._system_prompt])

        # Allowlist MCP tools so Claude Code can use them without prompting
        mcp_tools = ",".join([
            "mcp__ctf-desktop__ctf_screenshot",
            "mcp__ctf-desktop__ctf_mouse_click",
            "mcp__ctf-desktop__ctf_mouse_scroll",
            "mcp__ctf-desktop__ctf_type_text",
            "mcp__ctf-desktop__ctf_press_key",
            "mcp__ctf-desktop__ctf_execute",
            "mcp__ctf-desktop__ctf_read_file",
            "mcp__ctf-desktop__ctf_write_file",
            "mcp__ctf-desktop__ctf_container_status",
        ])
        cmd.extend(["--allowedTools", mcp_tools])

        # Disallow built-in tools that operate on the HOST, not the container
        cmd.extend([
            "--disallowedTools",
            "Bash,Read,Write,Edit,Glob,Grep,NotebookEdit",
        ])

        # Build MCP config with resolved absolute paths and pass inline.
        # This avoids relying on .mcp.json auto-discovery which may not
        # work correctly when claude is spawned as a subprocess.
        project_root = str(Path(__file__).resolve().parents[3])
        src_dir = str(Path(__file__).resolve().parents[2])
        mcp_env = {"PYTHONPATH": src_dir}
        if self._container_api_url:
            mcp_env["CTF_CONTAINER_API"] = self._container_api_url
        mcp_config = json.dumps({
            "mcpServers": {
                "ctf-desktop": {
                    "command": sys.executable,
                    "args": ["-m", "ctf_agent.interfaces.mcp_server"],
                    "cwd": project_root,
                    "env": mcp_env,
                }
            }
        })
        cmd.extend(["--mcp-config", mcp_config])

        # Remove ANTHROPIC_API_KEY so Claude Code uses its own auth
        # instead of a potentially invalid key from .env.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        logger.info(f"Spawning Claude Code: {' '.join(cmd)}")

        # Use a large buffer limit (100MB) because stream-json output can
        # contain base64-encoded screenshots in single lines.
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=100 * 1024 * 1024,
        )

        # Send the task via stdin
        self._process.stdin.write(task.encode("utf-8"))
        self._process.stdin.close()

        final_text = ""

        # Read streaming JSON output line by line
        async for line in self._process.stdout:
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue

            try:
                event = json.loads(line_str)
            except json.JSONDecodeError:
                # Plain text output (non-JSON)
                final_text += line_str + "\n"
                if event_callback:
                    event_callback(ClaudeCodeEvent("text", {"text": line_str}))
                continue

            # Parse Claude Code stream-json events
            event_type = event.get("type", "")

            if event_type == "assistant":
                # Assistant message with content blocks
                message = event.get("message", {})
                for block in message.get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        final_text = text
                        if event_callback:
                            event_callback(ClaudeCodeEvent("text", {"text": text}))
                    elif block.get("type") == "tool_use":
                        if event_callback:
                            event_callback(ClaudeCodeEvent("tool_call", {
                                "tool": block.get("name", ""),
                                "input": block.get("input", {}),
                            }))

            elif event_type == "result":
                # Final result
                result_text = event.get("result", "")
                if result_text:
                    final_text = result_text
                if event_callback:
                    event_callback(ClaudeCodeEvent("done", {"text": final_text}))

        # Wait for process to finish
        await self._process.wait()

        # Capture any stderr
        stderr = await self._process.stderr.read()
        if stderr:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            if stderr_text:
                logger.warning(f"Claude Code stderr: {stderr_text}")

        if self._process.returncode != 0:
            if event_callback:
                event_callback(ClaudeCodeEvent("error", {
                    "text": f"Claude Code exited with code {self._process.returncode}"
                }))

        self._process = None
        return final_text

    def stop(self) -> None:
        """Kill the Claude Code subprocess."""
        if self._process:
            self._process.terminate()
