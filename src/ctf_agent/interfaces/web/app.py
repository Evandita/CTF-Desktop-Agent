import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from ctf_agent.recording.manager import (
    RecordingSession,
    SCREENSHOT_EVENTS,
    list_recordings,
    get_recording,
    get_screenshot_path,
    delete_recording,
)

from ctf_agent.config.settings import load_config
from ctf_agent.llm.factory import get_provider, get_claude_code_provider
from ctf_agent.container.manager import ContainerManager
from ctf_agent.container.client import ContainerClient
from ctf_agent.tools.registry import ToolRegistry
from ctf_agent.tools.screenshot import TakeScreenshotTool
from ctf_agent.tools.mouse import MouseClickTool, MouseMoveTool, MouseScrollTool, MouseDragTool
from ctf_agent.tools.keyboard import TypeTextTool, PressKeyTool
from ctf_agent.tools.shell import ExecuteCommandTool
from ctf_agent.tools.file_ops import ReadFileTool, WriteFileTool
from ctf_agent.tools.window import FocusWindowTool, ListWindowsTool
from ctf_agent.tools.clipboard import ClipboardGetTool, ClipboardSetTool
from ctf_agent.agent.core import AgentCore, AgentEvent

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="CTF Desktop Agent Web UI")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Global state
_agent: AgentCore | None = None
_cc_provider = None  # ClaudeCodeProvider when using claude-code mode
_container_mgr: ContainerManager | None = None
_client: ContainerClient | None = None
_websocket_clients: list[WebSocket] = []
_config = None
_provider_mode: str = "claude"  # "claude", "ollama", or "claude-code"
_hitl_manager = None  # HITLManager when HITL is enabled
_hitl_bridge_server = None  # HITLBridgeServer for Claude Code mode
_recording: RecordingSession | None = None


class ChatRequest(BaseModel):
    message: str


@app.on_event("startup")
async def startup():
    global _agent, _cc_provider, _container_mgr, _client, _config, _provider_mode
    global _hitl_manager, _hitl_bridge_server
    _config = load_config()
    _provider_mode = _config.llm.provider

    remote_url = _config.container.remote_api_url
    if remote_url:
        # Remote target mode — skip Docker, connect directly
        logger.info(f"Connecting to remote target at {remote_url}")
        _client = ContainerClient(base_url=remote_url)
        await _client.wait_until_ready(max_wait=60)
    else:
        # Local Docker mode
        from ctf_agent.config.models import ContainerConfig as CC
        _container_mgr = ContainerManager(CC(**_config.container.model_dump()))
        _container_mgr.start()
        _client = ContainerClient(base_url=_container_mgr.get_api_url())
        await _client.wait_until_ready(max_wait=120)

    # Initialize HITL if enabled
    if _config.hitl.enabled:
        from ctf_agent.hitl.manager import HITLManager
        _hitl_manager = HITLManager(_config.hitl)
        _hitl_manager.set_notification_callback(_on_hitl_request)

        # Start bridge server for Claude Code mode
        if _provider_mode == "claude-code":
            from ctf_agent.hitl.bridge import HITLBridgeServer
            _hitl_bridge_server = HITLBridgeServer(_hitl_manager, port=9999)
            await _hitl_bridge_server.start()

    if _provider_mode == "claude-code":
        from ctf_agent.agent.prompts import build_system_prompt
        _cc_provider = get_claude_code_provider(
            _config.llm,
            system_prompt=build_system_prompt(
                _config.container.screen_width, _config.container.screen_height
            ),
            max_turns=_config.agent.max_iterations,
            container_api_url=_get_api_url(),
            hitl_config=_config.hitl if _config.hitl.enabled else None,
            hitl_bridge_port=9999 if _hitl_bridge_server else None,
        )
        logger.info("Web UI started with Claude Code provider")
    else:
        llm = get_provider(_config.llm)
        tools = _register_tools(_client)
        _agent = AgentCore(
            llm=llm,
            tools=tools,
            screen_width=_config.container.screen_width,
            screen_height=_config.container.screen_height,
            max_iterations=_config.agent.max_iterations,
            hitl_manager=_hitl_manager,
        )
        logger.info(f"Web UI started with {_provider_mode} provider")

    if _hitl_manager:
        logger.info("HITL enabled")


@app.on_event("shutdown")
async def shutdown():
    if _hitl_bridge_server:
        await _hitl_bridge_server.stop()
    if _client:
        await _client.close()
    if _container_mgr:
        _container_mgr.stop()


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(content=html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    global _recording

    # Start recording for this task
    try:
        if _recording and _recording.active:
            _recording.stop()
        _recording = RecordingSession(client=_client)
        _recording.start(task=req.message, provider=_provider_mode)
    except Exception:
        logger.debug("Failed to start recording", exc_info=True)

    if _provider_mode == "claude-code":
        if not _cc_provider:
            return {"error": "Claude Code provider not initialized"}
        asyncio.create_task(_run_claude_code(req.message))
    else:
        if not _agent:
            return {"error": "Agent not initialized"}
        asyncio.create_task(_run_agent(req.message))
    return {"status": "started", "message": req.message}


def _get_api_url() -> str | None:
    """Return the container API URL (remote or local Docker)."""
    if _config and _config.container.remote_api_url:
        return _config.container.remote_api_url
    if _container_mgr:
        return _container_mgr.get_api_url()
    return None


@app.get("/api/status")
async def status():
    ctx = {}
    if _agent:
        ctx = _agent.context.get_summary()
    hitl_info = {}
    if _hitl_manager:
        hitl_info = {
            "enabled": True,
            "pending_count": len(_hitl_manager.get_pending_requests()),
        }
    container_running = True if (_config and _config.container.remote_api_url) else (
        _container_mgr.is_running() if _container_mgr else False
    )
    return {
        "provider": _provider_mode,
        "container_running": container_running,
        "context": ctx,
        "container_api_url": _get_api_url(),
        "hitl": hitl_info,
    }


@app.post("/api/stop")
async def stop_agent():
    if _provider_mode == "claude-code" and _cc_provider:
        _cc_provider.stop()
    elif _agent:
        _agent.stop()
    if _hitl_manager:
        _hitl_manager.cancel_all()
    return {"status": "stop_requested"}


@app.post("/api/clear")
async def clear_context():
    if _agent:
        _agent.context.clear()
    if _cc_provider:
        _cc_provider.clear_session()
    if _hitl_manager:
        _hitl_manager.cancel_all()
    return {"status": "cleared"}


class HITLResponseRequest(BaseModel):
    request_id: str
    decision: str
    message: str = ""


@app.post("/api/hitl/respond")
async def hitl_respond(req: HITLResponseRequest):
    """REST fallback for submitting HITL approval responses."""
    if not _hitl_manager:
        return {"error": "HITL not enabled"}
    from ctf_agent.hitl.manager import ApprovalResponse, ApprovalDecision
    response = ApprovalResponse(
        request_id=req.request_id,
        decision=ApprovalDecision(req.decision),
        message=req.message,
    )
    ok = _hitl_manager.submit_response(req.request_id, response)
    return {"status": "ok" if ok else "not_found"}


# ---------------------------------------------------------------------------
# WebRTC signaling proxy (so browser only talks to port 8080)
# ---------------------------------------------------------------------------

@app.post("/api/webrtc/offer")
async def proxy_webrtc_offer(data: dict):
    """Proxy WebRTC offer to the container API signaling endpoint."""
    import httpx
    api_url = _get_api_url()
    if not api_url:
        return {"error": "Container not running"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(f"{api_url}/webrtc/offer", json=data)
            if resp.status_code != 200:
                return {"error": f"Container returned {resp.status_code}", "detail": resp.text[:500]}
            return resp.json()
    except httpx.ConnectError:
        return {"error": "Cannot connect to container API"}
    except Exception as e:
        logger.warning(f"WebRTC offer proxy failed: {e}")
        return {"error": str(e)}


@app.post("/api/webrtc/disconnect")
async def proxy_webrtc_disconnect(data: dict):
    """Proxy WebRTC disconnect to the container API."""
    import httpx
    api_url = _get_api_url()
    if not api_url:
        return {"error": "Container not running"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(f"{api_url}/webrtc/disconnect", json=data)
            if resp.status_code != 200:
                return {"error": f"Container returned {resp.status_code}"}
            return resp.json()
    except httpx.ConnectError:
        return {"error": "Cannot connect to container API"}
    except Exception as e:
        logger.warning(f"WebRTC disconnect proxy failed: {e}")
        return {"error": str(e)}


@app.get("/api/recordings")
async def recordings_list():
    """List all recorded sessions."""
    return list_recordings()


@app.get("/api/recordings/{session_id}")
async def recording_detail(session_id: str):
    """Get a recording's metadata + event timeline."""
    rec = get_recording(session_id)
    if rec is None:
        return {"error": "Recording not found"}
    return rec


@app.get("/api/recordings/{session_id}/screenshot/{filename}")
async def recording_screenshot(session_id: str, filename: str):
    """Serve a screenshot PNG from a recording session."""
    path = get_screenshot_path(session_id, filename)
    if path is None:
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(path, media_type="image/png")


@app.delete("/api/recordings/{session_id}")
async def recording_delete(session_id: str):
    """Delete a recording session."""
    ok = delete_recording(session_id)
    return {"status": "deleted" if ok else "not_found"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _websocket_clients.append(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                # Legacy plain-text ping
                if raw == "ping":
                    await ws.send_json({"type": "pong"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})

            elif msg_type == "approval_response" and _hitl_manager:
                from ctf_agent.hitl.manager import ApprovalResponse, ApprovalDecision
                response = ApprovalResponse(
                    request_id=msg["request_id"],
                    decision=ApprovalDecision(msg["decision"]),
                    message=msg.get("message", ""),
                )
                _hitl_manager.submit_response(msg["request_id"], response)

    except WebSocketDisconnect:
        if ws in _websocket_clients:
            _websocket_clients.remove(ws)


def _on_hitl_request(request):
    """Callback: broadcast new HITL approval request to all WebSocket clients."""
    asyncio.create_task(_broadcast("approval_request", {
        "request_id": request.request_id,
        "approval_type": request.approval_type.value,
        "data": request.data,
    }))


async def _broadcast(event_type: str, data: dict):
    # Record event if recording is active
    if _recording and _recording.active:
        try:
            _recording.record_event(event_type, data)
            # Capture screenshot on significant events
            if event_type in SCREENSHOT_EVENTS:
                event_idx = _recording._event_index - 1  # just recorded
                await _recording.capture_screenshot(event_idx)
        except Exception:
            logger.debug("Recording event capture failed", exc_info=True)

        # Auto-stop recording when task completes
        if event_type in ("done", "error"):
            try:
                _recording.stop()
            except Exception:
                logger.debug("Recording stop failed", exc_info=True)

    msg = {"type": event_type, **data}
    for ws in list(_websocket_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            if ws in _websocket_clients:
                _websocket_clients.remove(ws)


async def _run_agent(message: str):
    """Run task with standard agent loop (claude/ollama)."""
    try:
        def event_callback(event: AgentEvent):
            asyncio.create_task(_broadcast(event.event_type, event.data))
        await _agent.run(message, event_callback=event_callback)
    except Exception:
        logger.exception("Agent task failed")
        await _broadcast("error", {"text": "Agent task failed. Check server logs."})


async def _run_claude_code(message: str):
    """Run task with Claude Code as the brain."""
    try:
        from ctf_agent.llm.claude_code_provider import ClaudeCodeEvent

        def event_callback(event: ClaudeCodeEvent):
            asyncio.create_task(_broadcast(event.event_type, event.data))
        await _cc_provider.run_task(
            message,
            event_callback=event_callback,
            hitl_manager=_hitl_manager,
        )
    except Exception:
        logger.exception("Claude Code task failed")
        _cc_provider.clear_session()
        await _broadcast("error", {"text": "Claude Code task failed. Session reset."})


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
    registry.register(FocusWindowTool(client))
    registry.register(ListWindowsTool(client))
    registry.register(ClipboardGetTool(client))
    registry.register(ClipboardSetTool(client))
    return registry
