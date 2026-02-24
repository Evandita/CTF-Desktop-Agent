"""
HITL Bridge — HTTP-based communication between MCP server and main app.

The main app runs a lightweight HTTP server (HITLBridgeServer).
The MCP server process sends approval requests via httpx (HITLBridgeClient)
and blocks until the human responds.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ctf_agent.hitl.manager import HITLManager

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_PORT = 9999


class HITLBridgeServer:
    """
    Runs in the MAIN application process (web app or CLI).
    Receives approval requests from the MCP server and routes
    them to the HITLManager.
    """

    def __init__(self, hitl_manager: "HITLManager", port: int = DEFAULT_BRIDGE_PORT):
        self._manager = hitl_manager
        self._port = port
        self._server: asyncio.Server | None = None

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_connection, "127.0.0.1", self._port
        )
        logger.info(f"HITL Bridge server listening on 127.0.0.1:{self._port}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle a single HTTP-like request from the MCP server bridge client."""
        try:
            # Read HTTP request (simplified — we only handle POST)
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            # Read headers
            content_length = 0
            while True:
                header_line = await reader.readline()
                if header_line in (b"\r\n", b"\n", b""):
                    break
                if header_line.lower().startswith(b"content-length:"):
                    content_length = int(header_line.split(b":")[1].strip())

            # Read body
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            data = json.loads(body)

            from ctf_agent.hitl.manager import ApprovalType

            approval_type = ApprovalType(data["type"])
            response = await self._manager.request_approval(approval_type, data)

            response_body = json.dumps({
                "decision": response.decision.value,
                "message": response.message,
            }).encode()

            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(response_body)).encode() + b"\r\n"
                b"\r\n"
                + response_body
            )
            await writer.drain()
        except Exception as e:
            logger.warning(f"HITL Bridge server error: {e}")
            error_body = json.dumps({"error": str(e)}).encode()
            writer.write(
                b"HTTP/1.1 500 Internal Server Error\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(error_body)).encode() + b"\r\n"
                b"\r\n"
                + error_body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


class HITLBridgeClient:
    """
    Runs in the MCP SERVER process.
    Sends approval requests to the bridge server and blocks until response.
    """

    def __init__(self, port: int = DEFAULT_BRIDGE_PORT):
        self._port = port
        self._base_url = f"http://127.0.0.1:{port}"

    async def request_approval(
        self,
        approval_type: str,
        tool_name: str,
        tool_input: dict,
    ) -> dict:
        """
        Send approval request to bridge server and block until response.
        Returns dict with "decision" and "message".
        """
        payload = {
            "type": approval_type,
            "tool_name": tool_name,
            "tool_input": tool_input,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/approval",
                json=payload,
                timeout=None,  # Wait indefinitely for human response
            )
            return resp.json()
