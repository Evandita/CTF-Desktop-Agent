from .base import Tool, ToolResult
from ctf_agent.container.client import ContainerClient


class TakeScreenshotTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "take_screenshot"

    @property
    def description(self) -> str:
        return (
            "Capture a screenshot of the current desktop display. "
            "Returns the screenshot as an image. Use this to see what "
            "is currently on screen before deciding on actions."
        )

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        result = await self._client.take_screenshot()
        return ToolResult(
            output=f"Screenshot captured ({result.width}x{result.height})",
            base64_image=result.image_base64,
        )
