from .base import Tool, ToolResult
from ctf_agent.container.client import ContainerClient


class TypeTextTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "type_text"

    @property
    def description(self) -> str:
        return (
            "Type text using the keyboard. The text will be typed character "
            "by character as if the user is typing. Use this for filling in "
            "text fields, terminals, etc."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to type"},
            },
            "required": ["text"],
        }

    async def execute(self, text: str, **kwargs) -> ToolResult:
        await self._client.keyboard_action(action="type", text=text)
        return ToolResult(output=f"Typed: {text[:100]}{'...' if len(text) > 100 else ''}")


class PressKeyTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "press_key"

    @property
    def description(self) -> str:
        return (
            "Press a single key or key combination. "
            "For single keys use key names like: Return, Tab, Escape, BackSpace, "
            "space, Up, Down, Left, Right, Home, End, Page_Up, Page_Down, F1-F12. "
            "For combinations, provide a list of keys like ['ctrl', 'c'] or ['alt', 'F4']."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Single key name (e.g., 'Return', 'Tab')",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key combination (e.g., ['ctrl', 'c'])",
                },
            },
        }

    async def execute(
        self, key: str | None = None, keys: list[str] | None = None, **kwargs
    ) -> ToolResult:
        if keys:
            await self._client.keyboard_action(action="key_combo", keys=keys)
            return ToolResult(output=f"Pressed key combo: {'+'.join(keys)}")
        elif key:
            await self._client.keyboard_action(action="key", key=key)
            return ToolResult(output=f"Pressed key: {key}")
        else:
            return ToolResult(
                output="Must provide either 'key' or 'keys'", is_error=True
            )
