# CLAUDE.md

## Project Overview

CTF Desktop Agent — an AI-powered containerized desktop agent for CTF challenges and security tasks. Runs a full Kali Linux desktop in Docker, controlled by an AI via screenshots, mouse/keyboard, and shell commands.

## Architecture

```
User (CLI / Web UI)
  → AgentCore or ClaudeCodeProvider
    → LLM Brain (Claude API / Ollama / Claude Code CLI)
    → Tools (screenshot, mouse, keyboard, shell, files)
      → ContainerClient (async HTTP)
        → Container API (FastAPI inside Docker, port 8888)
          → xdotool / scrot / subprocess
```

## Source Layout

```
src/ctf_agent/
  __main__.py              # Entry point → cli()
  agent/
    core.py                # AgentCore — main agentic loop (iterate until done or max_iterations)
    context.py             # ConversationContext — message history with smart image pruning
    prompts.py             # System prompt templates for CTF tasks
    planner.py             # Task decomposition via LLM
  config/
    models.py              # Pydantic config models (LLMConfig, ContainerConfig, AgentConfig, etc.)
    settings.py            # Config loading: env vars > YAML > defaults
  container/
    manager.py             # Docker lifecycle (build/start/stop/logs)
    client.py              # Async HTTP client (httpx) to container API
  hitl/
    manager.py             # HITL coordinator — asyncio.Future-based blocking
    bridge.py              # HTTP bridge for MCP subprocess ↔ main process HITL
  interfaces/
    cli.py                 # Click CLI (interactive/run/build commands), Rich output
    mcp_server.py          # MCP server exposing tools to Claude Code
    web/
      app.py               # FastAPI web UI + WebSocket streaming
      static/              # index.html, app.js, style.css, webrtc-viewer.js
  llm/
    base.py                # Abstract LLMProvider interface
    claude_provider.py     # Anthropic SDK — native vision + tool use
    ollama_provider.py     # Local Ollama — XML-emulated tool calls
    claude_code_provider.py # Spawns `claude` CLI subprocess, MCP-based
    factory.py             # create_provider() factory
    message_types.py       # TextContent, ImageContent, ToolUseContent, ToolResultContent
  tools/
    base.py                # Tool abstract base class
    registry.py            # ToolRegistry — register/lookup/execute tools
    screenshot.py          # take_screenshot
    mouse.py               # mouse_click, mouse_move, mouse_drag, mouse_scroll
    keyboard.py            # type_text, press_key
    shell.py               # execute_command
    file_ops.py            # read_file, write_file
  recording/
    manager.py             # Session recording (JSONL events + PNG screenshots)
```

```
docker/
  Dockerfile               # Kali Linux image with security tools
  supervisord.conf          # Manages: XVFB, XFCE4, container API, tmux, visible terminal
  entrypoint.sh             # Container startup
  scripts/ctf-exec.sh       # Visible terminal command executor
  container_api/
    server.py               # FastAPI server inside container (port 8888)
    routes/                 # health, screenshot, input, shell, filesystem, clipboard, webrtc, stream, window
    services/               # command_runner, display, input_control, file_manager, webrtc_stream
```

```
config/default.yaml         # Default configuration
recordings/                 # Saved session recordings
tests/                      # pytest suite
```

## Key Patterns

- **Provider pattern**: `LLMProvider` ABC with 3 implementations (Claude, Ollama, Claude Code). Factory in `llm/factory.py`.
- **Tool registry**: Tools inherit from `Tool` ABC, registered in `ToolRegistry`. All tools communicate with the container via async HTTP.
- **Config precedence**: CLI flags / env vars (`CTF_*` prefix) > YAML file > Pydantic model defaults.
- **HITL**: Three modes — tool approval, periodic checkpoints, agent questions. Uses `asyncio.Future` to block until human responds. For Claude Code mode, an HTTP bridge connects MCP subprocess to main app.
- **Context management**: `ConversationContext` keeps full text history but prunes images to the N most recent (default 10).
- **Recording**: Events logged as JSONL + screenshots saved as PNGs under `recordings/{session_id}/`.

## Common Commands

```bash
pip install -e ".[dev]"              # Install with dev deps
make build                           # Build Docker image
make container                       # Run container standalone
make container-stop                  # Stop container
ctf-agent interactive --provider claude   # CLI interactive session
ctf-agent run "task" --provider claude    # Single task
make web                             # Web UI at http://localhost:8080
make test                            # Run tests
make lint                            # Lint with ruff
```

## Code Conventions

- Python 3.11+, async/await throughout (FastAPI + httpx)
- Line length: 100 (ruff)
- Type hints used, Pydantic for config/data models
- pytest with pytest-asyncio for tests
- Entry point: `ctf_agent.interfaces.cli:cli` (defined in pyproject.toml `[project.scripts]`)

## Environment Variables

Key env vars (see `.env.example`):
- `CTF_LLM_PROVIDER` — `claude`, `ollama`, or `claude-code`
- `ANTHROPIC_API_KEY` — required for claude provider
- `CTF_LLM_MODEL` — model override
- `CTF_OLLAMA_HOST` — Ollama URL (default `http://localhost:11434`)
- `CTF_SCREEN_WIDTH` / `CTF_SCREEN_HEIGHT` — container resolution
- `CTF_MAX_ITERATIONS` — max agent loop cycles (default 50)
- `CTF_HITL_ENABLED`, `CTF_HITL_TOOL_APPROVAL`, `CTF_HITL_CHECKPOINT_INTERVAL`

## Container

- Kali Linux with XFCE4 desktop, XVFB, FastAPI API (8888)
- Desktop streamed to browser via WebRTC (with WebSocket JPEG fallback)
- VirtualBox-style bidirectional clipboard sharing (Disabled / Host→Guest / Guest→Host / Bidirectional)
- Pre-installed: nmap, gobuster, john, hashcat, gdb+pwndbg, radare2, Ghidra, sqlmap, binwalk, steghide, pwntools, metasploit, wireshark-cli, hydra, netcat, firefox-esr
- Commands execute in a visible tmux terminal (user can watch via Web UI desktop viewer)
- Container API uses xdotool for input, scrot for screenshots, xclip for clipboard
