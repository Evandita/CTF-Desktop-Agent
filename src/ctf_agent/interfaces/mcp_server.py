"""
MCP Server for CTF Desktop Agent.

Exposes container tools (screenshot, mouse, keyboard, shell, files) as MCP tools
that Claude Code can use natively. Claude Code becomes the agent brain — no custom
agent loop needed.

Usage:
    # Start container first, then run this server (Claude Code manages it via .mcp.json)
    python -m ctf_agent.interfaces.mcp_server

    # Or with a custom container API URL
    CTF_CONTAINER_API=http://localhost:8888 python -m ctf_agent.interfaces.mcp_server
"""

import asyncio
import base64
import json
import os
import logging
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    CallToolResult,
)

from ctf_agent.container.client import ContainerClient
from ctf_agent.container.manager import ContainerManager
from ctf_agent.config.models import ContainerConfig
from ctf_agent.config.settings import load_config

logger = logging.getLogger(__name__)

# Global state
_client: ContainerClient | None = None
_container_mgr: ContainerManager | None = None
_hitl_bridge_client = None  # HITLBridgeClient when HITL is enabled
_hitl_config: dict | None = None  # Parsed HITL config from env


def _get_client() -> ContainerClient:
    if _client is None:
        raise RuntimeError("Container client not initialized")
    return _client


def _needs_approval(tool_name: str) -> bool:
    """Check if a tool needs HITL approval based on the config passed via env."""
    if not _hitl_config or not _hitl_bridge_client:
        return False
    if not _hitl_config.get("enabled") or not _hitl_config.get("tool_approval"):
        return False
    if tool_name in _hitl_config.get("tools_auto_approved", []):
        return False
    required = _hitl_config.get("tools_requiring_approval", [])
    if "all" in required:
        return True
    if "none" in required:
        return False
    return tool_name in required


server = Server("ctf-desktop-agent")


@server.list_tools()
async def list_tools() -> list[Tool]:
    tools = [
        Tool(
            name="ctf_screenshot",
            description=(
                "Capture a screenshot of the CTF container's desktop. "
                "Returns the current screen as an image. Use this to see "
                "what's on the Kali Linux desktop before taking actions."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="ctf_mouse_click",
            description=(
                "Click the mouse at (x, y) coordinates on the container desktop. "
                "click_type can be 'single', 'double', or 'right'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                    "click_type": {
                        "type": "string",
                        "enum": ["single", "double", "right"],
                        "default": "single",
                    },
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="ctf_mouse_scroll",
            description="Scroll the mouse wheel at (x, y) in a given direction.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                    },
                    "amount": {"type": "integer", "default": 3},
                },
                "required": ["x", "y", "direction"],
            },
        ),
        Tool(
            name="ctf_type_text",
            description=(
                "Type text using the keyboard in the container desktop. "
                "Characters are typed one by one as if the user is typing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="ctf_press_key",
            description=(
                "Press a key or key combination in the container desktop. "
                "Single key: 'Return', 'Tab', 'Escape', 'BackSpace', 'Up', 'Down', etc. "
                "Combo: provide keys as a list like ['ctrl', 'c'] or ['alt', 'F4']."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Single key (e.g., 'Return', 'Tab')",
                    },
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key combo (e.g., ['ctrl', 'c'])",
                    },
                },
            },
        ),
        Tool(
            name="ctf_execute",
            description=(
                "Execute a shell command in the Kali Linux container. "
                "The container has security tools pre-installed: "
                "nmap, gobuster, john, hashcat, binwalk, steghide, pwntools, "
                "gdb+pwndbg, radare2, sqlmap, wireshark-cli, hydra, netcat, "
                "and more. Returns stdout, stderr, and return code."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30)",
                        "default": 30,
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="ctf_read_file",
            description="Read a file from the container filesystem.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute file path in the container",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="ctf_write_file",
            description="Write content to a file in the container filesystem.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute file path in the container",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write",
                    },
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="ctf_container_status",
            description=(
                "Get the status of the CTF container. Returns whether "
                "it's running and the noVNC URL for viewing the desktop."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]

    # Add ask_human tool when HITL agent questions are enabled
    if _hitl_config and _hitl_config.get("enabled") and _hitl_config.get("agent_questions"):
        tools.append(Tool(
            name="ctf_ask_human",
            description=(
                "Ask the human operator a question and wait for their response. "
                "Use when you need clarification about the task, are uncertain "
                "about which approach to take, or want confirmation before a "
                "potentially destructive action."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Your question for the human operator",
                    }
                },
                "required": ["question"],
            },
        ))

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        # --- HITL: Agent question tool ---
        if name == "ctf_ask_human":
            if _hitl_bridge_client:
                result = await _hitl_bridge_client.request_approval(
                    approval_type="agent_question",
                    tool_name=name,
                    tool_input=arguments,
                )
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text=f"Human response: {result.get('message', 'No response')}",
                    )]
                )
            else:
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text="HITL not enabled. Cannot ask human questions.",
                    )],
                    isError=True,
                )

        # --- HITL: Tool approval gate ---
        if _needs_approval(name):
            try:
                result = await _hitl_bridge_client.request_approval(
                    approval_type="tool_approval",
                    tool_name=name,
                    tool_input=arguments,
                )
                if result.get("decision") == "reject":
                    reason = result.get("message", "No reason given")
                    return CallToolResult(
                        content=[TextContent(
                            type="text",
                            text=(
                                f"TOOL EXECUTION BLOCKED: Human operator rejected "
                                f"this tool call. Reason: {reason}. "
                                f"Try a different approach."
                            ),
                        )],
                        isError=True,
                    )
            except Exception as e:
                logger.warning(f"HITL bridge error: {e}. Proceeding without approval.")

        client = _get_client()

        if name == "ctf_screenshot":
            result = await client.take_screenshot()
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Screenshot captured ({result.width}x{result.height})",
                    ),
                    ImageContent(
                        type="image",
                        data=result.image_base64,
                        mimeType="image/png",
                    ),
                ]
            )

        elif name == "ctf_mouse_click":
            click_type = arguments.get("click_type", "single")
            action_map = {
                "single": "click",
                "double": "double_click",
                "right": "right_click",
            }
            await client.mouse_action(
                action=action_map[click_type],
                x=arguments["x"],
                y=arguments["y"],
            )
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Clicked ({click_type}) at ({arguments['x']}, {arguments['y']})",
                    )
                ]
            )

        elif name == "ctf_mouse_scroll":
            await client.mouse_action(
                action="scroll",
                x=arguments["x"],
                y=arguments["y"],
                scroll_direction=arguments["direction"],
                scroll_amount=arguments.get("amount", 3),
            )
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Scrolled {arguments['direction']} at ({arguments['x']}, {arguments['y']})",
                    )
                ]
            )

        elif name == "ctf_type_text":
            await client.keyboard_action(action="type", text=arguments["text"])
            text_preview = arguments["text"][:100]
            if len(arguments["text"]) > 100:
                text_preview += "..."
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"Typed: {text_preview}")
                ]
            )

        elif name == "ctf_press_key":
            if "keys" in arguments and arguments["keys"]:
                await client.keyboard_action(
                    action="key_combo", keys=arguments["keys"]
                )
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=f"Pressed combo: {'+'.join(arguments['keys'])}",
                        )
                    ]
                )
            elif "key" in arguments and arguments["key"]:
                await client.keyboard_action(action="key", key=arguments["key"])
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=f"Pressed key: {arguments['key']}",
                        )
                    ]
                )
            else:
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text="Error: must provide 'key' or 'keys'",
                        )
                    ],
                    isError=True,
                )

        elif name == "ctf_execute":
            result = await client.execute_command(
                command=arguments["command"],
                timeout=arguments.get("timeout", 30),
                working_dir=arguments.get("working_dir"),
            )
            parts = []
            if result.stdout:
                parts.append(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                parts.append(f"STDERR:\n{result.stderr}")
            parts.append(f"Return code: {result.return_code}")
            if result.timed_out:
                parts.append("WARNING: Command timed out")
            return CallToolResult(
                content=[TextContent(type="text", text="\n".join(parts))],
                isError=result.return_code != 0,
            )

        elif name == "ctf_read_file":
            content = await client.read_file(arguments["path"])
            return CallToolResult(
                content=[TextContent(type="text", text=content)]
            )

        elif name == "ctf_write_file":
            await client.write_file(arguments["path"], arguments["content"])
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"File written: {arguments['path']}",
                    )
                ]
            )

        elif name == "ctf_container_status":
            running = _container_mgr.is_running() if _container_mgr else False
            novnc_url = _container_mgr.get_novnc_url() if _container_mgr else "N/A"
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=(
                            f"Container running: {running}\n"
                            f"noVNC URL: {novnc_url}\n"
                            f"Open the noVNC URL in a browser to watch the desktop live."
                        ),
                    )
                ]
            )

        else:
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"Unknown tool: {name}")
                ],
                isError=True,
            )

    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {e}")],
            isError=True,
        )


async def main():
    global _client, _container_mgr, _hitl_bridge_client, _hitl_config

    config = load_config()

    # Check if user wants to connect to an existing container
    api_url = os.environ.get("CTF_CONTAINER_API")

    if api_url:
        # Connect to existing container
        _client = ContainerClient(base_url=api_url)
        logger.info(f"Connecting to existing container at {api_url}")
    else:
        # Start a new container
        container_config = ContainerConfig(**config.container.model_dump())
        _container_mgr = ContainerManager(container_config)

        logger.info("Starting CTF container...")
        _container_mgr.start()

        _client = ContainerClient(base_url=_container_mgr.get_api_url())
        logger.info("Waiting for container API...")

    ready = await _client.wait_until_ready(max_wait=120)
    if not ready:
        logger.error("Container API did not become ready")
        raise RuntimeError("Container API not ready")

    # Initialize HITL bridge client if configured via env vars
    hitl_config_json = os.environ.get("CTF_HITL_CONFIG")
    bridge_port = os.environ.get("CTF_HITL_BRIDGE_PORT")
    if hitl_config_json and bridge_port:
        _hitl_config = json.loads(hitl_config_json)
        from ctf_agent.hitl.bridge import HITLBridgeClient
        _hitl_bridge_client = HITLBridgeClient(port=int(bridge_port))
        logger.info(f"HITL bridge client initialized (port={bridge_port})")

    logger.info("Container ready, starting MCP server...")

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        if _client:
            await _client.close()
        if _container_mgr:
            _container_mgr.stop()
            logger.info("Container stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
