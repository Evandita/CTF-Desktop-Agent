# Technical Reference

Detailed technical documentation for CTF Desktop Agent. For a quick overview and getting started, see the [README](../README.md).

## Table of Contents

- [LLM Providers](#llm-providers)
- [Agent Tools](#agent-tools)
- [Human-in-the-Loop (HITL)](#human-in-the-loop-hitl)
- [Web UI](#web-ui)
- [CLI Reference](#cli-reference)
- [Configuration Reference](#configuration-reference)
- [Container Details](#container-details)
- [MCP Server](#mcp-server)

## LLM Providers

### Claude (Anthropic API)

Uses the Anthropic SDK with native vision and tool-use support. The default and most capable option for CTF tasks.

```bash
ctf-agent interactive --provider claude --model claude-sonnet-4-20250514
```

- Requires `ANTHROPIC_API_KEY` environment variable
- Default model: `claude-sonnet-4-20250514`
- Full vision support for analyzing screenshots
- Native structured tool calling

### Ollama (Local)

Runs entirely locally with no API key required. Uses vision-capable models for screenshot analysis and emulated tool calling via prompt engineering.

```bash
ctf-agent interactive --provider ollama --model llava
```

- Requires Ollama running locally (`http://localhost:11434` by default)
- Default model: `llava`
- Tool calling emulated via XML blocks in model output
- Trade-off: slower and less reliable tool use, but fully private

### Claude Code (CLI subprocess)

Spawns the Claude Code CLI as the agent brain. Claude Code connects to the container via MCP and handles its own tool loop -- no custom agent loop needed.

```bash
ctf-agent interactive --provider claude-code
```

- Requires `claude` CLI installed and authenticated
- Uses Model Context Protocol (MCP) for native tool access
- Session continuity via `--session-id` / `--resume`
- Advanced reasoning with autonomous planning
- HITL support through inter-process HTTP bridge

## Agent Tools

The agent interacts with the container through these tools:

| Tool | Description |
|---|---|
| `take_screenshot` | Capture the desktop display (returns base64 PNG) |
| `mouse_click` | Click at (x, y) -- single, double, or right-click |
| `mouse_move` | Move cursor to (x, y) |
| `mouse_drag` | Drag from one point to another |
| `mouse_scroll` | Scroll wheel at (x, y) in a direction |
| `type_text` | Type text via keyboard |
| `press_key` | Press a key or key combination |
| `execute_command` | Run a shell command with optional timeout and working directory |
| `read_file` | Read file contents from the container |
| `write_file` | Write content to a file in the container |

## Human-in-the-Loop (HITL)

HITL allows a human operator to supervise and control agent actions in real time. Three modes are available:

### Tool Approval

Require human approval before executing specific (or all) tools. Auto-approved tools like `ctf_screenshot` skip the gate.

### Checkpoints

Pause the agent every N iterations for a human review. The operator can approve to continue or reject to stop the agent.

### Agent Questions

Allow the agent to ask clarifying questions mid-task. The human's response is fed back as a tool result.

### Enabling HITL

**CLI flags:**
```bash
ctf-agent interactive --hitl --approve-tools --checkpoint 5 --allow-questions
```

**Environment variables:**
```bash
CTF_HITL_ENABLED=true
CTF_HITL_TOOL_APPROVAL=true
CTF_HITL_CHECKPOINT_INTERVAL=5
```

**Config file (`config/default.yaml`):**
```yaml
hitl:
  enabled: true
  tool_approval: true
  tools_requiring_approval: ["all"]
  tools_auto_approved: ["ctf_screenshot", "ctf_container_status"]
  checkpoint_enabled: true
  checkpoint_interval: 5
  agent_questions: true
  approval_timeout: 0  # 0 = wait indefinitely
```

### How It Works

**Standard mode (Claude/Ollama):** The agent loop in `AgentCore.run()` awaits an `asyncio.Future` at each interception point. The future resolves when the human responds via the Web UI (WebSocket) or CLI (terminal prompt).

**Claude Code mode:** The MCP server acts as the interception point. A lightweight HTTP bridge (`127.0.0.1:9999`) connects the MCP server subprocess to the main app's HITL manager. Tool calls block until the human approves or rejects.

### HITL Configuration Reference

| Option | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch for HITL |
| `tool_approval` | bool | `false` | Require approval before tool execution |
| `tools_requiring_approval` | list | `["all"]` | Which tools need approval (`"all"`, `"none"`, or specific names) |
| `tools_auto_approved` | list | `["ctf_screenshot", "ctf_container_status"]` | Tools that skip the approval gate |
| `checkpoint_enabled` | bool | `false` | Pause at regular intervals |
| `checkpoint_interval` | int | `5` | Pause every N iterations/tool calls |
| `agent_questions` | bool | `false` | Allow agent to ask human questions |
| `approval_timeout` | int | `0` | Auto-approve after N seconds (0 = never) |

## Web UI

The web interface provides a split-pane layout with a live desktop view on the left and an agent chat panel on the right.

```bash
make web
# or
make web PROVIDER=claude-code
# Open http://localhost:8080
```

**Features:**
- Live noVNC desktop viewer (embedded iframe)
- Real-time chat with the agent via WebSocket
- Tool call and result display
- HITL approval dialogs inline in chat (approve/reject with optional message)
- Status panel showing message count, image count, HITL state, and pending approvals
- Clear context and stop agent controls

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serve the web UI |
| `/api/chat` | POST | Send a task to the agent |
| `/api/status` | GET | Container status, context info, HITL state |
| `/api/stop` | POST | Stop the running agent task |
| `/api/clear` | POST | Clear conversation context |
| `/api/hitl/respond` | POST | Submit HITL approval (REST fallback) |
| `/ws` | WebSocket | Real-time event streaming |

### WebSocket Event Types

| Event | Description |
|---|---|
| `thinking` | Agent iteration started |
| `text` | LLM text response |
| `tool_call` | Tool invocation details |
| `tool_result` | Tool execution result |
| `screenshot` | Screenshot captured |
| `tool_approval_requested` | Awaiting human approval |
| `tool_rejected` | Human rejected a tool call |
| `approval_request` | HITL approval dialog data |
| `agent_question` | Agent asking clarification |
| `checkpoint` | Checkpoint pause |
| `error` | Error occurred |
| `done` | Task completed |

## CLI Reference

### Commands

**`ctf-agent interactive [OPTIONS]`** -- Start an interactive REPL session.

```
Options:
  --provider TEXT       LLM provider: claude, ollama, claude-code
  --model TEXT          Override model name
  --no-container        Connect to an existing container (skip Docker management)
  --api-url TEXT        Container API URL (default: auto-detect)
  --hitl                Enable Human-in-the-Loop
  --approve-tools       Require approval for tool calls
  --checkpoint N        Pause every N iterations for review
  --allow-questions     Allow agent to ask human questions
```

**Interactive commands:**

| Command | Description |
|---|---|
| `/screenshot` | Capture and display the current desktop |
| `/status` | Show context stats and container state |
| `/clear` | Clear conversation context and HITL state |
| `/stop` | Stop the running agent |
| `/plan <task>` | Break a task into steps using the LLM |
| `quit` / `exit` | Exit the session |

**`ctf-agent run <TASK> [OPTIONS]`** -- Execute a single task non-interactively. Same options as `interactive`.

**`ctf-agent build [--path DOCKER]`** -- Build the Docker image.

## Configuration Reference

Configuration is loaded from (in order of precedence):

1. CLI flags and environment variables (highest)
2. Config file (`config/default.yaml` or `~/.ctf-agent/config.yaml`)
3. Built-in defaults (lowest)

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `CTF_LLM_PROVIDER` | LLM provider | `claude` |
| `CTF_LLM_MODEL` | Model override | (provider default) |
| `ANTHROPIC_API_KEY` | Anthropic API key | -- |
| `CTF_OLLAMA_HOST` | Ollama host URL | `http://localhost:11434` |
| `CTF_SCREEN_WIDTH` | Container screen width | `1024` |
| `CTF_SCREEN_HEIGHT` | Container screen height | `768` |
| `CTF_MAX_ITERATIONS` | Max agent loop iterations | `50` |
| `CTF_LOG_LEVEL` | Logging level | `INFO` |
| `CTF_HITL_ENABLED` | Enable HITL | `false` |
| `CTF_HITL_TOOL_APPROVAL` | Require tool approval | `false` |
| `CTF_HITL_CHECKPOINT_INTERVAL` | Checkpoint interval | `5` |

### Full Config File

```yaml
llm:
  provider: "claude"              # claude, ollama, claude-code
  model: null                     # Override model name
  temperature: 0.0                # LLM temperature
  max_tokens: 4096                # Max tokens per response

container:
  image_name: "ctf-desktop-agent:latest"
  container_name: "ctf-agent-desktop"
  vnc_port: 5900                  # VNC server port
  novnc_port: 6080                # noVNC web viewer port
  api_port: 8888                  # Container API port
  screen_width: 1024              # Virtual display width
  screen_height: 768              # Virtual display height
  memory_limit: "4g"              # Docker memory limit
  cpu_count: 2                    # Docker CPU count

agent:
  max_iterations: 50              # Max agent loop cycles
  max_images_in_context: 10       # Keep only N recent screenshots
  auto_screenshot_after_action: true

web_ui:
  host: "0.0.0.0"
  port: 8080

hitl:
  enabled: false
  tool_approval: false
  tools_requiring_approval: ["all"]
  tools_auto_approved: ["ctf_screenshot", "ctf_container_status"]
  checkpoint_enabled: false
  checkpoint_interval: 5
  agent_questions: false
  approval_timeout: 0

log_level: "INFO"
```

## Container Details

The Docker container runs a full Kali Linux desktop environment with:

- **XFCE4** desktop environment
- **XVFB** virtual framebuffer (headless X server)
- **x11vnc** VNC server on port 5900
- **noVNC** web-based VNC client on port 6080
- **Container API** (FastAPI) on port 8888

### Pre-installed Security Tools

| Category | Tools |
|---|---|
| Recon | nmap, gobuster, dirb, nikto, whatweb |
| Passwords | john, hashcat, hydra, medusa |
| Forensics | binwalk, foremost, steghide, exiftool |
| Binary | gdb+pwndbg, radare2, pwntools, Ghidra |
| Web | sqlmap, curl |
| Network | wireshark-cli, tcpdump, netcat, socat |
| Misc | firefox-esr, openvpn, metasploit |

### Container API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health/` | Health check |
| `POST /screenshot/` | Capture screen (returns base64 PNG) |
| `POST /input/mouse` | Mouse actions (click, double_click, right_click, move, drag, scroll) |
| `POST /input/keyboard` | Keyboard actions (type, key, key_combo) |
| `POST /shell/exec` | Execute shell command with timeout |
| `POST /files/read` | Read file from container |
| `POST /files/write` | Write file to container |

### Container Management

```bash
make build              # Build the image
make container          # Run container standalone
make container-stop     # Stop and remove
ctf-agent interactive --no-container --api-url http://localhost:8888  # Connect to existing
```

## MCP Server

The MCP (Model Context Protocol) server exposes container tools to Claude Code. It runs as a subprocess managed by the Claude Code provider.

**Exposed MCP Tools:**

| Tool | Description |
|---|---|
| `ctf_screenshot` | Capture desktop screenshot |
| `ctf_mouse_click` | Click at coordinates |
| `ctf_mouse_scroll` | Scroll at coordinates |
| `ctf_type_text` | Type text |
| `ctf_press_key` | Press key or combo |
| `ctf_execute` | Execute shell command |
| `ctf_read_file` | Read file |
| `ctf_write_file` | Write file |
| `ctf_container_status` | Get container status |
| `ctf_ask_human` | Ask human a question (HITL only) |

The `.mcp.json` file in the project root auto-configures the MCP server for Claude Code.
