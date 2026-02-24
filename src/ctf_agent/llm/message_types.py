from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class ImageContent:
    """Base64-encoded image for vision models."""
    base64_data: str
    media_type: str = "image/png"


@dataclass
class TextContent:
    """Plain text content."""
    text: str


@dataclass
class ToolUseContent:
    """Model requests a tool call."""
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass
class ToolResultContent:
    """Result returned after executing a tool."""
    tool_use_id: str
    content: str
    image: Optional[ImageContent] = None
    is_error: bool = False


ContentBlock = TextContent | ImageContent | ToolUseContent | ToolResultContent


@dataclass
class Message:
    role: Literal["user", "assistant", "system"]
    content: list[ContentBlock]


@dataclass
class ToolDefinition:
    """Defines a tool the model can call."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    content: list[ContentBlock]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens"]
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: Any = None
