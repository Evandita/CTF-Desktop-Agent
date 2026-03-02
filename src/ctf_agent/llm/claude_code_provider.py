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
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ctf_agent.config.models import HITLConfig
    from ctf_agent.hitl.manager import HITLManager

logger = logging.getLogger(__name__)

# Pattern matching Anthropic API errors about duplicate tool_use IDs
_DUPLICATE_ID_PATTERN = re.compile(r"tool_use.*ids must be unique", re.IGNORECASE)


@dataclass
class ClaudeCodeEvent:
    """Event from Claude Code subprocess output."""
    event_type: str  # "text", "tool_call", "tool_result", "error", "done", "checkpoint"
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
        hitl_config: Optional["HITLConfig"] = None,
        hitl_bridge_port: Optional[int] = None,
    ):
        self._model = model
        self._max_turns = max_turns
        self._system_prompt = system_prompt
        self._container_api_url = container_api_url
        self._process: Optional[asyncio.subprocess.Process] = None
        self._session_id: str = str(uuid.uuid4())
        self._has_session: bool = False  # True after first successful run
        self._hitl_config = hitl_config
        self._hitl_bridge_port = hitl_bridge_port
        self._tool_call_count: int = 0

        # Verify claude is installed
        if not shutil.which("claude"):
            raise RuntimeError(
                "Claude Code CLI ('claude') not found in PATH. "
                "Install it from https://claude.ai/claude-code"
            )

    def model_name(self) -> str:
        return f"claude-code{f' ({self._model})' if self._model else ''}"

    @staticmethod
    def _is_duplicate_id_error(text: str) -> bool:
        """Check if text contains the Anthropic API duplicate tool_use ID error."""
        return bool(_DUPLICATE_ID_PATTERN.search(text))

    async def run_task(
        self,
        task: str,
        event_callback: Optional[callable] = None,
        hitl_manager: Optional["HITLManager"] = None,
        _retry: bool = False,
    ) -> str:
        """
        Run a task using Claude Code. Streams output via event_callback.
        Returns the final text output.

        Uses `claude -p` (print mode) with --output-format stream-json
        for structured streaming output.
        """
        cmd = ["claude", "-p", "--verbose", "--output-format", "stream-json"]

        # Session continuity: resume prior conversation if one exists
        if self._has_session:
            cmd.extend(["--resume", self._session_id])
        else:
            cmd.extend(["--session-id", self._session_id])

        if self._model:
            cmd.extend(["--model", self._model])

        if self._max_turns:
            cmd.extend(["--max-turns", str(self._max_turns)])

        if self._system_prompt and not self._has_session:
            # Only pass system prompt on first call; resumed sessions
            # already have it from the initial conversation.
            cmd.extend(["--system-prompt", self._system_prompt])

        # Allowlist MCP tools so Claude Code can use them without prompting
        mcp_tools_list = [
            "mcp__ctf-desktop__ctf_screenshot",
            "mcp__ctf-desktop__ctf_mouse_click",
            "mcp__ctf-desktop__ctf_mouse_scroll",
            "mcp__ctf-desktop__ctf_type_text",
            "mcp__ctf-desktop__ctf_press_key",
            "mcp__ctf-desktop__ctf_execute",
            "mcp__ctf-desktop__ctf_read_file",
            "mcp__ctf-desktop__ctf_write_file",
            "mcp__ctf-desktop__ctf_container_status",
        ]
        # Add ask_human tool when HITL agent questions are enabled
        if self._hitl_config and self._hitl_config.agent_questions:
            mcp_tools_list.append("mcp__ctf-desktop__ctf_ask_human")

        cmd.extend(["--allowedTools", ",".join(mcp_tools_list)])

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

        # Pass HITL config to MCP server process via env vars
        if self._hitl_config and self._hitl_config.enabled and self._hitl_bridge_port:
            mcp_env["CTF_HITL_BRIDGE_PORT"] = str(self._hitl_bridge_port)
            mcp_env["CTF_HITL_CONFIG"] = self._hitl_config.model_dump_json()

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
        duplicate_id_detected = False

        # Checkpoint config
        checkpoint_enabled = (
            hitl_manager
            and self._hitl_config
            and self._hitl_config.enabled
            and self._hitl_config.checkpoint_enabled
        )
        checkpoint_interval = (
            self._hitl_config.checkpoint_interval
            if self._hitl_config
            else 5
        )

        # Read streaming JSON output line by line
        async for line in self._process.stdout:
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue

            try:
                event = json.loads(line_str)
            except json.JSONDecodeError:
                # Plain text output (non-JSON)
                if self._is_duplicate_id_error(line_str):
                    duplicate_id_detected = True
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
                        self._tool_call_count += 1
                        if event_callback:
                            event_callback(ClaudeCodeEvent("tool_call", {
                                "tool": block.get("name", ""),
                                "input": block.get("input", {}),
                            }))

                        # --- CHECKPOINT: kill + resume after N tool calls ---
                        if (
                            checkpoint_enabled
                            and self._tool_call_count % checkpoint_interval == 0
                        ):
                            self._process.terminate()
                            await self._process.wait()
                            self._has_session = True

                            if event_callback:
                                event_callback(ClaudeCodeEvent("checkpoint", {
                                    "tool_calls": self._tool_call_count,
                                    "message": (
                                        f"Checkpoint after {self._tool_call_count} "
                                        f"tool calls. Continue?"
                                    ),
                                }))

                            from ctf_agent.hitl.manager import (
                                ApprovalType, ApprovalDecision,
                            )
                            resp = await hitl_manager.request_approval(
                                ApprovalType.CHECKPOINT,
                                {"tool_calls": self._tool_call_count},
                            )

                            if resp.decision == ApprovalDecision.REJECT:
                                self._process = None
                                return final_text

                            # Resume with continuation prompt
                            self._process = None
                            return await self.run_task(
                                "Continue from where you left off.",
                                event_callback=event_callback,
                                hitl_manager=hitl_manager,
                            )

            elif event_type == "result":
                # Final result
                result_text = event.get("result", "")
                if result_text:
                    if self._is_duplicate_id_error(result_text):
                        duplicate_id_detected = True
                    final_text = result_text
                if not duplicate_id_detected and event_callback:
                    event_callback(ClaudeCodeEvent("done", {}))

        # Wait for process to finish
        await self._process.wait()

        # Capture any stderr
        stderr = await self._process.stderr.read()
        if stderr:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            if stderr_text:
                if self._is_duplicate_id_error(stderr_text):
                    duplicate_id_detected = True
                logger.warning(f"Claude Code stderr: {stderr_text}")

        # Auto-retry with a fresh session on duplicate tool_use ID error
        if duplicate_id_detected and not _retry:
            logger.warning(
                "Duplicate tool_use ID error detected — retrying with fresh session"
            )
            self._process = None
            self.clear_session()
            return await self.run_task(
                task,
                event_callback=event_callback,
                hitl_manager=hitl_manager,
                _retry=True,
            )

        if self._process.returncode != 0:
            # Reset session on failure so the next call starts fresh
            # instead of trying to resume a broken session.
            self._has_session = False
            if event_callback:
                event_callback(ClaudeCodeEvent("error", {
                    "text": f"Claude Code exited with code {self._process.returncode}"
                }))
        else:
            # Mark session as established so subsequent calls resume it
            self._has_session = True

        self._process = None
        return final_text

    def clear_session(self) -> None:
        """Reset the session so the next run_task starts a fresh conversation."""
        self._session_id = str(uuid.uuid4())
        self._has_session = False
        self._tool_call_count = 0

    @property
    def session_id(self) -> str:
        return self._session_id

    def stop(self) -> None:
        """Kill the Claude Code subprocess."""
        if self._process:
            self._process.terminate()
