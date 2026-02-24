# CTF Desktop Agent

AI-powered containerized desktop agent for CTF challenges and security tasks. Runs a full Kali Linux desktop in Docker and lets an AI control it via screenshots, mouse/keyboard, and shell commands.

## Architecture

```
User (CLI / Web UI)
  → AgentCore or ClaudeCodeProvider
    → LLM Brain (Claude API / Ollama / Claude Code)
    → Tools (screenshot, mouse, keyboard, shell, files)
      → ContainerClient (HTTP)
        → Container API (FastAPI inside Docker)
          → xdotool / scrot / subprocess
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
# Edit .env — set provider and API key
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

**Single task:**
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

- **Full Kali Linux desktop** in Docker with XFCE4
- **VNC + noVNC** for live desktop viewing in browser
- **3 LLM backends**: Claude API, Ollama (local), or Claude Code CLI
- **Tool-based agent**: screenshot, mouse, keyboard, shell commands, file I/O
- **CTF-optimized**: pre-installed security tools (nmap, gobuster, john, hashcat, binwalk, steghide, pwntools, gdb+pwndbg, radare2, sqlmap, Ghidra, and more)
- **MCP server**: exposes container tools natively to Claude Code
- **CLI + Web UI**: terminal interface and browser dashboard
- **Task planning**: AI can break complex challenges into steps

## Pre-installed Security Tools

| Category | Tools |
|---|---|
| Recon | nmap, gobuster, dirb, nikto, whatweb |
| Passwords | john, hashcat, hydra, medusa |
| Forensics | binwalk, foremost, steghide, exiftool |
| Binary | gdb+pwndbg, radare2, pwntools |
| Web | sqlmap, curl |
| Network | wireshark-cli, tcpdump, netcat, socat |
| Misc | Ghidra, firefox-esr, openvpn |

## Configuration

Configuration is loaded from (in order of precedence):
1. Environment variables (`CTF_LLM_PROVIDER`, `ANTHROPIC_API_KEY`, etc.)
2. Config file (`config/default.yaml` or `~/.ctf-agent/config.yaml`)
3. Built-in defaults

See `.env.example` for available environment variables.

## Development

```bash
# Install with dev deps
pip install -e ".[dev]"

# Run container separately for development
make container

# Connect to existing container
ctf-agent interactive --no-container

# Run tests
make test

# Lint
make lint
```

## License

MIT
