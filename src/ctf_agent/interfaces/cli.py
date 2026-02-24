import asyncio
import json
import logging
import threading
import click
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from ctf_agent.config.settings import load_config
from ctf_agent.config.models import AppConfig
from ctf_agent.llm.factory import get_provider, get_claude_code_provider
from ctf_agent.container.manager import ContainerManager
from ctf_agent.container.client import ContainerClient
from ctf_agent.tools.registry import ToolRegistry
from ctf_agent.tools.screenshot import TakeScreenshotTool
from ctf_agent.tools.mouse import MouseClickTool, MouseMoveTool, MouseScrollTool, MouseDragTool
from ctf_agent.tools.keyboard import TypeTextTool, PressKeyTool
from ctf_agent.tools.shell import ExecuteCommandTool
from ctf_agent.tools.file_ops import ReadFileTool, WriteFileTool
from ctf_agent.agent.core import AgentCore, AgentEvent

console = Console()


def _register_tools(client: ContainerClient) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(TakeScreenshotTool(client))
    registry.register(MouseClickTool(client))
    registry.register(MouseMoveTool(client))
    registry.register(MouseDragTool(client))
    registry.register(MouseScrollTool(client))
    registry.register(TypeTextTool(client))
    registry.register(PressKeyTool(client))
    registry.register(ExecuteCommandTool(client))
    registry.register(ReadFileTool(client))
    registry.register(WriteFileTool(client))
    return registry


def _make_event_handler():
    """Event handler for standard agent loop (claude/ollama providers)."""
    def handle_event(event: AgentEvent):
        if event.event_type == "thinking":
            console.print(f"[dim]--- Iteration {event.data['iteration']} ---[/dim]")
        elif event.event_type == "tool_call":
            console.print(Panel(
                f"[bold cyan]{event.data['tool']}[/bold cyan]\n"
                f"[dim]{event.data['input']}[/dim]",
                title="Tool Call",
                border_style="cyan",
            ))
        elif event.event_type == "tool_result":
            style = "red" if event.data.get("is_error") else "green"
            output = event.data.get("output", "")
            if len(output) > 500:
                output = output[:500] + "...(truncated)"
            console.print(Panel(
                output,
                title=f"Result: {event.data['tool']}",
                border_style=style,
            ))
        elif event.event_type == "text":
            console.print(Markdown(event.data["text"]))
        elif event.event_type == "tool_approval_requested":
            console.print(f"[orange1]Awaiting approval for: {event.data['tool']}[/orange1]")
        elif event.event_type == "tool_rejected":
            console.print(f"[red]Tool rejected: {event.data['tool']} — {event.data.get('reason', '')}[/red]")
        elif event.event_type == "done":
            console.print("[bold green]--- Agent completed ---[/bold green]")
    return handle_event


def _make_claude_code_event_handler():
    """Event handler for Claude Code provider (subprocess-based)."""
    from ctf_agent.llm.claude_code_provider import ClaudeCodeEvent

    def handle_event(event: ClaudeCodeEvent):
        if event.event_type == "text":
            console.print(Markdown(event.data.get("text", "")))
        elif event.event_type == "tool_call":
            console.print(Panel(
                f"[bold cyan]{event.data.get('tool', '')}[/bold cyan]\n"
                f"[dim]{event.data.get('input', {})}[/dim]",
                title="Tool Call",
                border_style="cyan",
            ))
        elif event.event_type == "tool_result":
            style = "red" if event.data.get("is_error") else "green"
            output = event.data.get("output", "")
            if len(output) > 500:
                output = output[:500] + "...(truncated)"
            console.print(Panel(output, title="Result", border_style=style))
        elif event.event_type == "checkpoint":
            console.print(Panel(
                event.data.get("message", "Checkpoint reached."),
                title="[bold yellow]Checkpoint[/bold yellow]",
                border_style="yellow",
            ))
        elif event.event_type == "error":
            console.print(f"[red]{event.data.get('text', 'Unknown error')}[/red]")
        elif event.event_type == "done":
            console.print("[bold green]--- Claude Code completed ---[/bold green]")
    return handle_event


# ---------------------------------------------------------------------------
# CLI HITL approval handler
# ---------------------------------------------------------------------------

class CLIApprovalHandler:
    """Handles HITL approval requests by prompting the user in the terminal."""

    def __init__(self, hitl_manager, loop):
        self._manager = hitl_manager
        self._loop = loop
        self._manager.set_notification_callback(self._on_request)

    def _on_request(self, request):
        """Called when a new approval request is created. Spawns a prompt thread."""
        thread = threading.Thread(
            target=self._prompt_user, args=(request,), daemon=True
        )
        thread.start()

    def _prompt_user(self, request):
        """Prompt the user for approval in the terminal (runs in a thread)."""
        from ctf_agent.hitl.manager import (
            ApprovalResponse, ApprovalDecision, ApprovalType,
        )

        console.print()  # Blank line for visual separation

        if request.approval_type == ApprovalType.TOOL_APPROVAL:
            console.print(Panel(
                f"[bold yellow]Tool:[/bold yellow] {request.data.get('tool_name', '')}\n"
                f"[dim]{json.dumps(request.data.get('tool_input', {}), indent=2)}[/dim]",
                title="[bold orange1]Tool Approval Required[/bold orange1]",
                border_style="orange1",
            ))
        elif request.approval_type == ApprovalType.CHECKPOINT:
            console.print(Panel(
                f"Iteration: {request.data.get('iteration', request.data.get('tool_calls', '?'))}",
                title="[bold yellow]Checkpoint[/bold yellow]",
                border_style="yellow",
            ))
        elif request.approval_type == ApprovalType.AGENT_QUESTION:
            console.print(Panel(
                request.data.get("question", request.data.get("tool_input", {}).get("question", "")),
                title="[bold cyan]Agent Question[/bold cyan]",
                border_style="cyan",
            ))

        try:
            if request.approval_type == ApprovalType.AGENT_QUESTION:
                answer = console.input("[bold cyan]Your answer: [/bold cyan]").strip()
                decision = ApprovalDecision.APPROVE
                message = answer
            else:
                answer = console.input(
                    "[bold orange1](y)es / (n)o / or type a message: [/bold orange1]"
                ).strip()
                if answer.lower() in ("y", "yes", ""):
                    decision = ApprovalDecision.APPROVE
                    message = ""
                elif answer.lower() in ("n", "no"):
                    decision = ApprovalDecision.REJECT
                    message = ""
                else:
                    # Any other text = approve with message
                    decision = ApprovalDecision.APPROVE
                    message = answer
        except (EOFError, KeyboardInterrupt):
            decision = ApprovalDecision.REJECT
            message = "Interrupted"

        response = ApprovalResponse(
            request_id=request.request_id,
            decision=decision,
            message=message,
        )

        # Thread-safe: schedule on the event loop
        self._loop.call_soon_threadsafe(
            self._manager.submit_response, request.request_id, response
        )


# ---------------------------------------------------------------------------
# Setup HITL from config + CLI flags
# ---------------------------------------------------------------------------

def _apply_hitl_flags(config: AppConfig, hitl, approve_tools, checkpoint, allow_questions):
    """Apply CLI HITL flags to config."""
    if hitl or approve_tools or checkpoint > 0 or allow_questions:
        config.hitl.enabled = True
    if approve_tools:
        config.hitl.tool_approval = True
    if checkpoint > 0:
        config.hitl.checkpoint_enabled = True
        config.hitl.checkpoint_interval = checkpoint
    if allow_questions:
        config.hitl.agent_questions = True


def _setup_hitl(config: AppConfig, loop):
    """Create HITLManager + CLIApprovalHandler if HITL is enabled. Returns manager or None."""
    if not config.hitl.enabled:
        return None
    from ctf_agent.hitl.manager import HITLManager
    hitl_manager = HITLManager(config.hitl)
    CLIApprovalHandler(hitl_manager, loop)
    console.print("[orange1]HITL enabled[/orange1]")
    return hitl_manager


# ---------------------------------------------------------------------------
# Interactive commands
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """CTF Desktop Agent - AI-powered CTF challenge solver."""
    pass


@cli.command()
@click.option(
    "--provider",
    type=click.Choice(["claude", "ollama", "claude-code"]),
    default=None,
    help="LLM provider to use",
)
@click.option("--model", default=None, help="Model name override")
@click.option("--no-container", is_flag=True, help="Skip container management (use existing)")
@click.option("--api-url", default=None, help="Container API URL (with --no-container)")
@click.option("--hitl", is_flag=True, help="Enable Human-in-the-Loop mode")
@click.option("--approve-tools", is_flag=True, help="Require approval for tool calls")
@click.option("--checkpoint", type=int, default=0, help="Checkpoint every N iterations")
@click.option("--allow-questions", is_flag=True, help="Allow agent to ask questions")
def interactive(provider, model, no_container, api_url, hitl, approve_tools, checkpoint, allow_questions):
    """Start an interactive session with the agent."""
    config = load_config()
    if provider:
        config.llm.provider = provider
    if model:
        config.llm.model = model
    _apply_hitl_flags(config, hitl, approve_tools, checkpoint, allow_questions)

    if config.llm.provider == "claude-code":
        asyncio.run(_interactive_claude_code(config, no_container, api_url))
    else:
        asyncio.run(_interactive_session(config, no_container, api_url))


# ---------------------------------------------------------------------------
# Standard agent loop (claude / ollama)
# ---------------------------------------------------------------------------

async def _interactive_session(config: AppConfig, no_container: bool, api_url: str | None):
    llm = get_provider(config.llm)

    loop = asyncio.get_running_loop()
    hitl_manager = _setup_hitl(config, loop)

    console.print(Panel(
        "[bold]CTF Desktop Agent[/bold]\n\n"
        f"Provider: {llm.model_name()}\n"
        "Type your task or challenge description. Type 'quit' to exit.\n"
        "Commands: /screenshot, /status, /plan <task>, /stop, /clear",
        border_style="blue",
    ))

    container_mgr, client = await _setup_container(config, no_container, api_url)
    if client is None:
        return

    tools = _register_tools(client)
    agent = AgentCore(
        llm=llm,
        tools=tools,
        screen_width=config.container.screen_width,
        screen_height=config.container.screen_height,
        max_iterations=config.agent.max_iterations,
        max_images_in_context=config.agent.max_images_in_context,
        hitl_manager=hitl_manager,
    )
    event_handler = _make_event_handler()

    try:
        while True:
            try:
                user_input = console.input("[bold blue]You> [/bold blue]").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "/quit"):
                break
            if user_input == "/screenshot":
                result = await client.take_screenshot()
                console.print(f"Screenshot: {result.width}x{result.height}")
                continue
            if user_input == "/status":
                console.print(f"Context: {agent.context.get_summary()}")
                if container_mgr:
                    console.print(f"Container: {'running' if container_mgr.is_running() else 'stopped'}")
                if hitl_manager:
                    console.print(f"HITL pending: {len(hitl_manager.get_pending_requests())}")
                continue
            if user_input == "/clear":
                agent.context.clear()
                if hitl_manager:
                    hitl_manager.cancel_all()
                console.print("Context cleared.")
                continue
            if user_input == "/stop":
                agent.stop()
                console.print("Agent stop requested.")
                continue
            if user_input.startswith("/plan "):
                task = user_input[6:].strip()
                from ctf_agent.agent.planner import TaskPlanner
                planner = TaskPlanner(llm)
                with console.status("Planning..."):
                    plan = await planner.create_plan(task)
                console.print(Panel(Markdown(plan), title="Plan", border_style="yellow"))
                continue

            await agent.run(user_input, event_callback=event_handler)
    finally:
        await _teardown(client, container_mgr)


# ---------------------------------------------------------------------------
# Claude Code mode — Claude Code CLI is the brain
# ---------------------------------------------------------------------------

async def _interactive_claude_code(config: AppConfig, no_container: bool, api_url: str | None):
    from ctf_agent.agent.prompts import build_system_prompt

    loop = asyncio.get_running_loop()
    hitl_manager = _setup_hitl(config, loop)

    # Start HITL bridge server for Claude Code mode
    hitl_bridge = None
    if hitl_manager:
        from ctf_agent.hitl.bridge import HITLBridgeServer
        hitl_bridge = HITLBridgeServer(hitl_manager, port=9999)
        await hitl_bridge.start()

    container_mgr, client = await _setup_container(config, no_container, api_url)
    if client is None:
        return

    # Determine the container API URL so Claude Code's MCP server
    # connects to the existing container instead of starting a new one
    container_url = api_url or (
        container_mgr.get_api_url() if container_mgr else None
    )

    cc_provider = get_claude_code_provider(
        config.llm,
        system_prompt=build_system_prompt(
            config.container.screen_width, config.container.screen_height
        ),
        max_turns=config.agent.max_iterations,
        container_api_url=container_url,
        hitl_config=config.hitl if config.hitl.enabled else None,
        hitl_bridge_port=9999 if hitl_bridge else None,
    )

    console.print(Panel(
        "[bold]CTF Desktop Agent[/bold]\n\n"
        f"Provider: {cc_provider.model_name()}\n"
        "Claude Code is the brain. It uses MCP tools to control the container.\n"
        "Type your task or challenge description. Type 'quit' to exit.\n"
        "Commands: /stop, /status, /clear",
        border_style="magenta",
    ))

    event_handler = _make_claude_code_event_handler()

    try:
        while True:
            try:
                user_input = console.input("[bold magenta]You> [/bold magenta]").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "/quit"):
                break
            if user_input == "/stop":
                cc_provider.stop()
                console.print("Stop requested.")
                continue
            if user_input == "/clear":
                cc_provider.clear_session()
                if hitl_manager:
                    hitl_manager.cancel_all()
                console.print("Session cleared. Next message starts a fresh conversation.")
                continue
            if user_input == "/status":
                if container_mgr:
                    console.print(f"Container: {'running' if container_mgr.is_running() else 'stopped'}")
                    console.print(f"noVNC: {container_mgr.get_novnc_url()}")
                console.print(f"Session: {cc_provider.session_id}")
                if hitl_manager:
                    console.print(f"HITL pending: {len(hitl_manager.get_pending_requests())}")
                continue

            with console.status("[magenta]Claude Code is working...[/magenta]"):
                result = await cc_provider.run_task(
                    user_input,
                    event_callback=event_handler,
                    hitl_manager=hitl_manager,
                )
    finally:
        if hitl_bridge:
            await hitl_bridge.stop()
        await _teardown(client, container_mgr)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _setup_container(
    config: AppConfig, no_container: bool, api_url: str | None
) -> tuple[ContainerManager | None, ContainerClient | None]:
    """Start or connect to the container. Returns (manager, client)."""
    container_mgr = None
    client = None

    if no_container:
        url = api_url or f"http://localhost:{config.container.api_port}"
        client = ContainerClient(base_url=url)
        with console.status("Connecting to container API..."):
            ready = await client.wait_until_ready(max_wait=10)
            if not ready:
                console.print(f"[red]Cannot connect to container API at {url}[/red]")
                return None, None
        console.print(f"[green]Connected to container API at {url}[/green]")
    else:
        from ctf_agent.config.models import ContainerConfig as CC
        container_mgr = ContainerManager(CC(**config.container.model_dump()))
        with console.status("Starting container..."):
            container_mgr.start()
        client = ContainerClient(base_url=container_mgr.get_api_url())
        with console.status("Waiting for container API..."):
            ready = await client.wait_until_ready(max_wait=120)
            if not ready:
                console.print("[red]Container API failed to start![/red]")
                container_mgr.stop()
                return None, None
        console.print(
            f"[green]Container ready. noVNC: {container_mgr.get_novnc_url()}[/green]"
        )

    return container_mgr, client


async def _teardown(client: ContainerClient | None, container_mgr: ContainerManager | None):
    """Clean up container and client."""
    if client:
        await client.close()
    if container_mgr:
        with console.status("Stopping container..."):
            container_mgr.stop()
        console.print("[dim]Container stopped.[/dim]")


# ---------------------------------------------------------------------------
# Non-interactive commands
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("task")
@click.option("--provider", type=click.Choice(["claude", "ollama", "claude-code"]), default=None)
@click.option("--model", default=None)
@click.option("--api-url", default=None, help="Container API URL (skip container management)")
def run(task, provider, model, api_url):
    """Run a single task non-interactively."""
    config = load_config()
    if provider:
        config.llm.provider = provider
    if model:
        config.llm.model = model

    if config.llm.provider == "claude-code":
        asyncio.run(_run_single_claude_code(config, task, api_url))
    else:
        asyncio.run(_run_single(config, task, api_url))


async def _run_single(config: AppConfig, task: str, api_url: str | None):
    """Run single task with standard agent loop (claude/ollama)."""
    llm = get_provider(config.llm)
    container_mgr, client = await _setup_container(
        config, no_container=bool(api_url), api_url=api_url
    )
    if client is None:
        return

    tools = _register_tools(client)
    agent = AgentCore(
        llm=llm,
        tools=tools,
        screen_width=config.container.screen_width,
        screen_height=config.container.screen_height,
        max_iterations=config.agent.max_iterations,
    )
    event_handler = _make_event_handler()

    try:
        result = await agent.run(task, event_callback=event_handler)
        console.print(Panel(result, title="Final Result", border_style="green"))
    finally:
        await _teardown(client, container_mgr)


async def _run_single_claude_code(config: AppConfig, task: str, api_url: str | None):
    """Run single task with Claude Code as the brain."""
    from ctf_agent.agent.prompts import build_system_prompt

    container_mgr, client = await _setup_container(
        config, no_container=bool(api_url), api_url=api_url
    )
    if client is None:
        return

    container_url = api_url or (
        container_mgr.get_api_url() if container_mgr else None
    )
    cc_provider = get_claude_code_provider(
        config.llm,
        system_prompt=build_system_prompt(
            config.container.screen_width, config.container.screen_height
        ),
        max_turns=config.agent.max_iterations,
        container_api_url=container_url,
    )
    event_handler = _make_claude_code_event_handler()

    try:
        result = await cc_provider.run_task(task, event_callback=event_handler)
        console.print(Panel(result, title="Final Result", border_style="green"))
    finally:
        await _teardown(client, container_mgr)


@cli.command()
@click.option("--path", default="docker", help="Path to docker directory")
def build(path):
    """Build the Docker image."""
    from ctf_agent.config.models import ContainerConfig as CC
    config = load_config()
    mgr = ContainerManager(CC(**config.container.model_dump()))
    mgr.build_image(dockerfile_path=path)
    console.print("[green]Docker image built successfully.[/green]")


if __name__ == "__main__":
    cli()
