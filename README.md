# CTF Desktop Agent

AI-powered containerized desktop agent for CTF challenges and security tasks. Runs a full Kali Linux desktop in Docker and lets an AI control it via screenshots, mouse/keyboard, and shell commands.

## Architecture

```
User (CLI / Web UI)
  -> AgentCore or ClaudeCodeProvider
    -> LLM Brain (Claude API / Ollama / Claude Code)
    -> Tools (screenshot, mouse, keyboard, shell, files)
      -> ContainerClient (HTTP)
        -> Container API (FastAPI inside Docker)
          -> xdotool / scrot / subprocess
```

Three brain options, two interfaces:

| Provider | How it works | Requirements |
|---|---|---|
| `claude` | Custom agent loop calls Anthropic API directly | `ANTHROPIC_API_KEY` |
| `ollama` | Custom agent loop calls local Ollama models | Ollama running locally |
| `claude-code` | Spawns Claude Code CLI as the brain via MCP | `claude` CLI installed |

## Quick Start

### 1. Install

```bash
pip install -e ".[dev]"
```

### 2. Build the Docker image

```bash
make build
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env -- set provider and API key
```

### 4. Run

**With Claude API:**
```bash
ctf-agent interactive --provider claude
```

**With Ollama (local):**
```bash
ctf-agent interactive --provider ollama --model llava
```

**With Claude Code as the brain:**
```bash
ctf-agent interactive --provider claude-code
```

**Web UI (any provider):**
```bash
make web
# Open http://localhost:8080
```

**Single task (non-interactive):**
```bash
ctf-agent run "Scan 10.0.0.1 with nmap and find open ports" --provider claude-code
```

### Use Claude Code directly via MCP

You can also use Claude Code directly (without the CLI/Web UI wrapper). The project includes a `.mcp.json` that auto-configures the MCP server.

```bash
# 1. Build and start the container
make build && make container

# 2. Open Claude Code in this project directory
claude

# Claude Code will auto-detect the MCP server from .mcp.json
# You'll see tools like ctf_screenshot, ctf_execute, ctf_mouse_click, etc.
```

## Features

- **Full Kali Linux desktop** in Docker with XFCE4 and XVFB
- **Live desktop streaming** via WebRTC (with WebSocket JPEG fallback for Docker environments)
- **Bidirectional clipboard sharing** — VirtualBox-style modes: Disabled, Host→Guest, Guest→Host, Bidirectional
- **Persistent state**: container reuse across restarts + Docker volume for user data (`/home/ctfuser`) that survives rebuilds. Auto-restores `apt` packages from `~/.extra-packages`.
- **3 LLM backends**: Claude API, Ollama (local), or Claude Code CLI
- **Tool-based agent**: screenshot, mouse, keyboard, shell commands, file I/O
- **Human-in-the-Loop (HITL)**: tool approval, periodic checkpoints, agent-to-human questions
- **Session continuity**: Claude Code mode maintains context across messages in the same chat
- **CTF-optimized**: pre-installed security tools (nmap, gobuster, john, hashcat, binwalk, steghide, pwntools, gdb+pwndbg, radare2, sqlmap, Ghidra, and more)
- **MCP server**: exposes container tools natively to Claude Code
- **CLI + Web UI**: terminal interface with rich output and browser dashboard with live desktop view
- **Task planning**: AI can break complex challenges into steps via `/plan`
- **Real-time streaming**: WebSocket-based event streaming for live UI updates
- **Smart context management**: automatic image pruning to stay within token limits

## Project Structure

```
ctf-desktop-agent/
  config/
    default.yaml              # Default configuration
  docker/
    Dockerfile                # Kali Linux container image
    container_api/            # FastAPI server running inside container
  src/ctf_agent/
    agent/                    # Agent loop, context management, prompts, planner
    config/                   # Pydantic config models, settings loader
    container/                # Docker lifecycle, async HTTP client
    hitl/                     # Human-in-the-Loop manager and inter-process bridge
    interfaces/
      cli.py                  # Click CLI with rich output
      mcp_server.py           # MCP server for Claude Code
      web/                    # FastAPI web app + WebSocket + static frontend
    llm/                      # LLM providers (Claude, Ollama, Claude Code)
    tools/                    # Tool implementations (screenshot, mouse, keyboard, shell, files)
    recording/                # Session recording (events + screenshots)
  tests/                      # Test suite
```

## Documentation

For detailed technical documentation (all config options, API endpoints, WebSocket events, HITL configuration, CLI reference, etc.), see **[docs/reference.md](docs/reference.md)**.

## Development

```bash
pip install -e ".[dev]"       # Install with dev dependencies
make container                # Run container (with persistent volume)
ctf-agent interactive --no-container  # Connect to existing container
make test                     # Run tests
make lint                     # Lint with ruff
make clean                    # Clean build artifacts
```

### Container Management

The container persists state across restarts and rebuilds:

```bash
make container                # Start container (reuses existing if present)
make container-stop           # Stop container (state preserved for restart)
make container-destroy        # Remove container (volume kept, user data safe)
make container-clean          # Full reset: remove container + volume
```

User data in `/home/ctfuser` (downloads, browser profiles, SSH keys, shell history, Python venvs) is stored on a Docker volume and survives container removal and image rebuilds.

To auto-restore `apt` packages after a rebuild, add them inside the container:

```bash
echo "package-name" >> ~/.extra-packages
```

Packages listed in `~/.extra-packages` are automatically installed on container startup.

## Requirements

- Python 3.11+
- Docker
- One of: Anthropic API key, Ollama, or Claude Code CLI

## License

MIT
