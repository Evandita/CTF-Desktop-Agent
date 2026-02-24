from .base import Tool, ToolResult
from ctf_agent.container.client import ContainerClient


class MouseClickTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "mouse_click"

    @property
    def description(self) -> str:
        return (
            "Click the mouse at the specified (x, y) coordinates on screen. "
            "Optionally specify click_type: 'single', 'double', 'right'."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "click_type": {
                    "type": "string",
                    "enum": ["single", "double", "right"],
                    "default": "single",
                    "description": "Type of mouse click",
                },
            },
            "required": ["x", "y"],
        }

    async def execute(
        self, x: int, y: int, click_type: str = "single", **kwargs
    ) -> ToolResult:
        action_map = {
            "single": "click",
            "double": "double_click",
            "right": "right_click",
        }
        await self._client.mouse_action(action=action_map[click_type], x=x, y=y)
        return ToolResult(output=f"Clicked ({click_type}) at ({x}, {y})")


class MouseMoveTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "mouse_move"

    @property
    def description(self) -> str:
        return "Move the mouse cursor to the specified (x, y) coordinates."

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
            },
            "required": ["x", "y"],
        }

    async def execute(self, x: int, y: int, **kwargs) -> ToolResult:
        await self._client.mouse_action(action="move", x=x, y=y)
        return ToolResult(output=f"Mouse moved to ({x}, {y})")


class MouseDragTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "mouse_drag"

    @property
    def description(self) -> str:
        return "Drag the mouse from (start_x, start_y) to (end_x, end_y)."

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "start_x": {"type": "integer"},
                "start_y": {"type": "integer"},
                "end_x": {"type": "integer"},
                "end_y": {"type": "integer"},
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        }

    async def execute(
        self, start_x: int, start_y: int, end_x: int, end_y: int, **kwargs
    ) -> ToolResult:
        await self._client.mouse_action(
            action="drag", x=start_x, y=start_y, end_x=end_x, end_y=end_y
        )
        return ToolResult(
            output=f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"
        )


class MouseScrollTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "mouse_scroll"

    @property
    def description(self) -> str:
        return "Scroll the mouse wheel at position (x, y) in a given direction."

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                },
                "amount": {"type": "integer", "default": 3},
            },
            "required": ["x", "y", "direction"],
        }

    async def execute(
        self, x: int, y: int, direction: str, amount: int = 3, **kwargs
    ) -> ToolResult:
        await self._client.mouse_action(
            action="scroll",
            x=x,
            y=y,
            scroll_direction=direction,
            scroll_amount=amount,
        )
        return ToolResult(output=f"Scrolled {direction} {amount}x at ({x}, {y})")
