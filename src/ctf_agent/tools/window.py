from .base import Tool, ToolResult
from ctf_agent.container.client import ContainerClient


class FocusWindowTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "focus_window"

    @property
    def description(self) -> str:
        return (
            "Bring a window to the foreground and give it focus. "
            "Use this before interacting with a GUI application via mouse/keyboard. "
            "Search by window name (substring match, e.g., 'Firefox', 'Ghidra', "
            "'CTF Agent Terminal') or by class_name or window_id."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Window title to search for (substring match). "
                        "E.g., 'Firefox', 'Ghidra', 'CTF Agent Terminal'"
                    ),
                },
                "class_name": {
                    "type": "string",
                    "description": "Window WM_CLASS to search for",
                },
                "window_id": {
                    "type": "integer",
                    "description": "Specific window ID to activate",
                },
            },
        }

    async def execute(
        self,
        name: str | None = None,
        class_name: str | None = None,
        window_id: int | None = None,
        **kwargs,
    ) -> ToolResult:
        if not name and not class_name and window_id is None:
            return ToolResult(
                output="Must provide 'name', 'class_name', or 'window_id'",
                is_error=True,
            )
        result = await self._client.focus_window(
            name=name, class_name=class_name, window_id=window_id
        )
        return ToolResult(output=result.message, is_error=not result.success)


class ListWindowsTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "list_windows"

    @property
    def description(self) -> str:
        return (
            "List all visible windows on the desktop with their names and IDs. "
            "Use this to discover which windows are open before using focus_window."
        )

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        windows, active_id = await self._client.list_windows()
        if not windows:
            return ToolResult(output="No visible windows found")
        lines = []
        for w in windows:
            marker = " (active)" if active_id and w.window_id == active_id else ""
            lines.append(f"  [{w.window_id}] {w.name}{marker}")
        return ToolResult(output="Open windows:\n" + "\n".join(lines))
