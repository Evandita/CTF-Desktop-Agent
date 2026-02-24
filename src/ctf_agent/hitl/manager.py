"""
HITL Manager — central coordinator for Human-in-the-Loop interactions.

The agent loop (or MCP server bridge) calls request_approval() which blocks
on an asyncio.Future until the human responds. The interface layer (web/cli)
calls submit_response() to unblock the waiting coroutine.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from ctf_agent.config.models import HITLConfig

logger = logging.getLogger(__name__)


class ApprovalType(str, Enum):
    TOOL_APPROVAL = "tool_approval"
    CHECKPOINT = "checkpoint"
    AGENT_QUESTION = "agent_question"


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass
class ApprovalRequest:
    """A pending request for human input."""
    request_id: str
    approval_type: ApprovalType
    data: dict[str, Any]
    future: asyncio.Future = field(default=None, repr=False)
    created_at: float = field(default_factory=time.time)


@dataclass
class ApprovalResponse:
    """Human's response to an approval request."""
    request_id: str
    decision: ApprovalDecision
    message: str = ""


class HITLManager:
    """
    Maintains a queue of pending approval requests. The agent loop
    (or MCP bridge) calls request_approval() which blocks until the
    human responds. The interface layer calls submit_response() to
    unblock the waiting coroutine.
    """

    def __init__(self, config: HITLConfig):
        self._config = config
        self._pending: dict[str, ApprovalRequest] = {}
        self._notification_callback: Optional[Callable] = None

    @property
    def config(self) -> HITLConfig:
        return self._config

    def set_notification_callback(self, callback: Callable[[ApprovalRequest], None]):
        """Set callback for notifying UI about new approval requests."""
        self._notification_callback = callback

    def needs_tool_approval(self, tool_name: str) -> bool:
        """Check if a tool requires human approval."""
        if not self._config.enabled or not self._config.tool_approval:
            return False

        # Auto-approved tools are always skipped
        if tool_name in self._config.tools_auto_approved:
            return False

        required = self._config.tools_requiring_approval
        if "all" in required:
            return True
        if "none" in required:
            return False
        return tool_name in required

    def needs_checkpoint(self, iteration: int) -> bool:
        """Check if a checkpoint pause is needed at this iteration."""
        if not self._config.enabled or not self._config.checkpoint_enabled:
            return False
        return iteration > 0 and iteration % self._config.checkpoint_interval == 0

    async def request_approval(
        self,
        approval_type: ApprovalType,
        data: dict[str, Any],
    ) -> ApprovalResponse:
        """
        Create an approval request and block until the human responds.
        Called from the agent loop or MCP bridge server.
        """
        loop = asyncio.get_running_loop()
        request_id = str(uuid.uuid4())
        future = loop.create_future()

        request = ApprovalRequest(
            request_id=request_id,
            approval_type=approval_type,
            data=data,
            future=future,
        )
        self._pending[request_id] = request

        # Notify the UI
        if self._notification_callback:
            self._notification_callback(request)

        logger.info(
            f"HITL: Waiting for {approval_type.value} approval "
            f"(request_id={request_id})"
        )

        try:
            if self._config.approval_timeout > 0:
                response = await asyncio.wait_for(
                    future, timeout=self._config.approval_timeout
                )
            else:
                response = await future
        except asyncio.TimeoutError:
            logger.warning(f"HITL: Approval timed out, auto-approving {request_id}")
            response = ApprovalResponse(
                request_id=request_id,
                decision=ApprovalDecision.APPROVE,
                message="Auto-approved (timeout)",
            )
        finally:
            self._pending.pop(request_id, None)

        return response

    def submit_response(self, request_id: str, response: ApprovalResponse) -> bool:
        """
        Submit human's response to a pending approval request.
        Called from the interface layer (web/cli).
        Returns True if the request was found and resolved.
        """
        request = self._pending.get(request_id)
        if not request or request.future.done():
            return False

        request.future.set_result(response)
        logger.info(
            f"HITL: Response received for {request_id}: {response.decision.value}"
        )
        return True

    def get_pending_requests(self) -> list[ApprovalRequest]:
        """Get all pending approval requests."""
        return list(self._pending.values())

    def cancel_all(self):
        """Cancel all pending requests (e.g., on agent stop)."""
        for request in self._pending.values():
            if not request.future.done():
                request.future.cancel()
        self._pending.clear()
