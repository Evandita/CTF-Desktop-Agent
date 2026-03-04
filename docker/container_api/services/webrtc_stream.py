import asyncio
import json
import logging
import os
import subprocess
import time
import uuid

import mss
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.contrib.media import MediaRelay
from av import VideoFrame
from PIL import Image

from services import input_control

logger = logging.getLogger(__name__)

DISPLAY = os.environ.get("DISPLAY", ":1")


class DesktopVideoTrack(VideoStreamTrack):
    """Captures the X11 display via mss and streams as WebRTC video frames."""

    kind = "video"

    def __init__(self, target_fps: int = 15):
        super().__init__()
        self._target_fps = target_fps
        self._frame_interval = 1.0 / target_fps
        self._sct = None
        self._frame_count = 0
        self._start_time = None

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # Lazy-init mss in the async context
        if self._sct is None:
            os.environ["DISPLAY"] = DISPLAY
            self._sct = mss.mss()
            self._start_time = time.monotonic()

        # Rate-limit to target FPS
        expected_time = self._start_time + self._frame_count * self._frame_interval
        now = time.monotonic()
        if now < expected_time:
            await asyncio.sleep(expected_time - now)

        # Capture full screen (monitor 1 = primary)
        monitor = self._sct.monitors[1]
        screenshot = self._sct.grab(monitor)

        # Convert BGRA → RGB via PIL, then to av.VideoFrame
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        frame = VideoFrame.from_image(img)
        frame.pts = pts
        frame.time_base = time_base

        self._frame_count += 1
        return frame


class DataChannelInputHandler:
    """Routes input messages from WebRTC DataChannel to xdotool/xclip."""

    def __init__(self):
        self.clipboard_mode = "disabled"

    def handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from DataChannel: %s", raw[:100])
            return

        msg_type = data.get("type")

        if msg_type == "clipboard_mode":
            self.clipboard_mode = data.get("mode", "disabled")
            logger.debug("DataChannel clipboard mode set to: %s", self.clipboard_mode)
        elif msg_type == "mouse":
            self._handle_mouse(data)
        elif msg_type == "key":
            self._handle_key(data)
        elif msg_type == "clipboard":
            self._handle_clipboard(data)
        else:
            logger.debug("Unknown DataChannel message type: %s", msg_type)

    def _handle_mouse(self, data: dict) -> None:
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
                x, y,
                data.get("direction", "down"),
                int(data.get("amount", 3)),
            )

    def _handle_key(self, data: dict) -> None:
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

    def _handle_clipboard(self, data: dict) -> None:
        if self.clipboard_mode not in ("host_to_guest", "bidirectional"):
            return
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
                logger.exception("Failed to set clipboard via DataChannel")


class WebRTCConnectionManager:
    """Manages WebRTC peer connections for desktop streaming."""

    def __init__(self, target_fps: int = 15):
        self._relay = MediaRelay()
        self._video_track = DesktopVideoTrack(target_fps=target_fps)
        self._connections: dict[str, RTCPeerConnection] = {}
        self._input_handler = DataChannelInputHandler()

    async def create_connection(
        self,
        offer_sdp: str,
        offer_type: str = "offer",
        ice_servers: list[dict] | None = None,
    ) -> tuple[str, str, str]:
        """Handle SDP offer. Returns (answer_sdp, answer_type, connection_id)."""
        rtc_ice = [RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
        if ice_servers:
            rtc_ice = [RTCIceServer(**s) for s in ice_servers]

        config = RTCConfiguration(iceServers=rtc_ice)
        pc = RTCPeerConnection(configuration=config)
        connection_id = uuid.uuid4().hex[:16]
        self._connections[connection_id] = pc

        # Share the single video track across all peers via relay
        relayed_track = self._relay.subscribe(self._video_track)
        pc.addTrack(relayed_track)

        @pc.on("datachannel")
        def on_datachannel(channel):
            @channel.on("message")
            def on_message(message):
                self._input_handler.handle_message(message)

        @pc.on("connectionstatechange")
        async def on_state_change():
            if pc.connectionState in ("failed", "closed"):
                await self.close_connection(connection_id)

        # Set remote offer and create answer
        offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        logger.info("WebRTC connection %s established", connection_id)
        return pc.localDescription.sdp, pc.localDescription.type, connection_id

    async def close_connection(self, connection_id: str) -> None:
        pc = self._connections.pop(connection_id, None)
        if pc:
            await pc.close()
            logger.info("WebRTC connection %s closed", connection_id)

    async def shutdown(self) -> None:
        for cid in list(self._connections):
            await self.close_connection(cid)
