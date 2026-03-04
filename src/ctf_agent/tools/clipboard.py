from .base import Tool, ToolResult
from ctf_agent.container.client import ContainerClient


class ClipboardGetTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "clipboard_get"

    @property
    def description(self) -> str:
        return (
            "Read the current text content from the desktop clipboard. "
            "Useful for extracting text that was copied by the user or "
            "by a GUI application."
        )

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        result = await self._client.clipboard_get()
        if result.get("ok"):
            text = result.get("text", "")
            return ToolResult(
                output=f"Clipboard content: {text}" if text else "Clipboard is empty"
            )
        return ToolResult(
            output=f"Failed to read clipboard: {result.get('error', 'unknown')}",
            is_error=True,
        )


class ClipboardSetTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "clipboard_set"

    @property
    def description(self) -> str:
        return (
            "Set text content to the desktop clipboard. "
            "Useful for pasting text into GUI applications via Ctrl+V."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to copy to the clipboard",
                },
            },
            "required": ["text"],
        }

    async def execute(self, text: str = "", **kwargs) -> ToolResult:
        result = await self._client.clipboard_set(text)
        if result.get("ok"):
            return ToolResult(output=f"Clipboard set ({len(text)} chars)")
        return ToolResult(
            output=f"Failed to set clipboard: {result.get('error', 'unknown')}",
            is_error=True,
        )
