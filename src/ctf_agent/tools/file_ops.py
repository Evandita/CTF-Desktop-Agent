from .base import Tool, ToolResult
from ctf_agent.container.client import ContainerClient


class ReadFileTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file in the container. "
            "Provide the absolute path to the file."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            content = await self._client.read_file(path)
            return ToolResult(output=content)
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)


class WriteFileTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file in the container. "
            "Provide the absolute path and the content to write."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs) -> ToolResult:
        try:
            await self._client.write_file(path, content)
            return ToolResult(output=f"File written: {path}")
        except Exception as e:
            return ToolResult(output=f"Error writing file: {e}", is_error=True)
