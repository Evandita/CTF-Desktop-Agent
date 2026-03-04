"""WebSocket-based desktop streaming.

Provides a reliable fallback for environments where WebRTC ICE cannot
traverse Docker bridge networking (e.g. Docker Desktop on macOS/Windows).

Protocol:
    Server → Client:  binary messages (JPEG frames)
                      JSON text messages (clipboard updates)
    Client → Server:  JSON text messages (input events, same format as
                      the WebRTC DataChannel)
"""

import asyncio
import io
import json
import logging
import os
import subprocess

import mss
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from PIL import Image

from services import input_control

router = APIRouter()
logger = logging.getLogger(__name__)

DISPLAY = os.environ.get("DISPLAY", ":1")
DEFAULT_FPS = 10
DEFAULT_QUALITY = 60


@router.websocket("/ws/desktop")
async def desktop_stream(websocket: WebSocket):
    await websocket.accept()

    fps = DEFAULT_FPS
    quality = DEFAULT_QUALITY

    os.environ["DISPLAY"] = DISPLAY
    sct = mss.mss()

    state = {
        "clipboard_mode": "disabled",
        "clipboard_task": None,
        "last_set_text": None,  # anti-echo: last text set by host→guest
    }

    # Spawn a task to send frames; the main loop handles incoming messages
    send_task = asyncio.create_task(_send_frames(websocket, sct, fps, quality))
    loop = asyncio.get_running_loop()

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            if msg_type == "clipboard_mode":
                _update_clipboard_mode(state, websocket, data.get("mode", "disabled"))
            elif msg_type == "clipboard":
                if state["clipboard_mode"] in ("host_to_guest", "bidirectional"):
                    text = data.get("text", "")
                    state["last_set_text"] = text
                    loop.run_in_executor(None, _handle_clipboard, data)
            else:
                # mouse / key events — run in thread to avoid blocking
                loop.run_in_executor(None, _handle_input_parsed, data)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("Desktop stream closed", exc_info=True)
    finally:
        send_task.cancel()
        if state["clipboard_task"]:
            state["clipboard_task"].cancel()
        try:
            sct.close()
        except Exception:
            pass


def _update_clipboard_mode(state: dict, websocket: WebSocket, mode: str):
    """Update clipboard mode and start/stop the clipboard monitor task."""
    if mode not in ("disabled", "host_to_guest", "guest_to_host", "bidirectional"):
        mode = "disabled"
    state["clipboard_mode"] = mode

    # Cancel existing monitor
    if state["clipboard_task"]:
        state["clipboard_task"].cancel()
        state["clipboard_task"] = None

    # Start monitor if guest→host is enabled
    if mode in ("guest_to_host", "bidirectional"):
        state["clipboard_task"] = asyncio.create_task(
            _monitor_clipboard(websocket, state)
        )

    logger.debug("Clipboard mode set to: %s", mode)


def _read_clipboard() -> str:
    """Read clipboard text via xclip (runs in thread pool)."""
    proc = subprocess.run(
        ["xclip", "-selection", "clipboard", "-o"],
        capture_output=True,
        timeout=2,
        env={"DISPLAY": DISPLAY},
    )
    return proc.stdout.decode("utf-8", errors="replace")


async def _monitor_clipboard(websocket: WebSocket, state: dict):
    """Poll xclip and push clipboard changes to the browser."""
    last_text = ""
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                # Run blocking xclip in thread pool to avoid stalling the event loop
                current_text = await loop.run_in_executor(None, _read_clipboard)

                # Skip if unchanged or if this is an echo of a host→guest paste
                if current_text != last_text:
                    if current_text != state.get("last_set_text"):
                        await websocket.send_text(json.dumps({
                            "type": "clipboard",
                            "action": "update",
                            "text": current_text,
                        }))
                    last_text = current_text
            except Exception:
                logger.debug("Clipboard monitor error", exc_info=True)

            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass


async def _send_frames(
    websocket: WebSocket, sct: mss.mss, fps: int, quality: int
):
    interval = 1.0 / fps
    buf = io.BytesIO()

    try:
        while True:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=quality)

            await websocket.send_bytes(buf.getvalue())
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.debug("Frame sender stopped", exc_info=True)


def _handle_input_parsed(data: dict):
    """Route a parsed input message to xdotool (mouse/key only)."""
    msg_type = data.get("type")

    if msg_type == "mouse":
        _handle_mouse(data)
    elif msg_type == "key":
        _handle_key(data)


def _handle_mouse(data: dict):
    action = data.get("action", "")
    x = int(data.get("x", 0))
    y = int(data.get("y", 0))

    if action == "click":
        input_control.mouse_click(x, y, int(data.get("button", 1)))
    elif action == "double_click":
        input_control.mouse_double_click(x, y)
    elif action == "right_click":
        input_control.mouse_right_click(x, y)
    elif action == "move":
        input_control.mouse_move(x, y)
    elif action == "drag":
        input_control.mouse_drag(
            x, y, int(data.get("end_x", x)), int(data.get("end_y", y))
        )
    elif action == "scroll":
        input_control.mouse_scroll(
            x, y, data.get("direction", "down"), int(data.get("amount", 3))
        )


def _handle_key(data: dict):
    action = data.get("action", "")
    if action == "type":
        text = data.get("text", "")
        if text:
            input_control.type_text(text)
    elif action == "key":
        key = data.get("key", "")
        if key:
            input_control.press_key(key)
    elif action == "key_combo":
        keys = data.get("keys", [])
        if keys:
            input_control.key_combo(keys)


def _handle_clipboard(data: dict):
    if data.get("action") == "set":
        text = data.get("text", "")
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
                env={"DISPLAY": DISPLAY},
            )
        except Exception:
            logger.exception("Failed to set clipboard")
