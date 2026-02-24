from .base import Tool, ToolResult
from ctf_agent.llm.message_types import ToolDefinition


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    async def execute(self, name: str, **kwargs) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(output=f"Unknown tool: {name}", is_error=True)
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(output=f"Tool error: {e}", is_error=True)

    def get_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=t.name,
                description=t.description,
                parameters=t.parameters_schema,
            )
            for t in self._tools.values()
        ]
