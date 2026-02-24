import anthropic
from .base import LLMProvider
from .message_types import (
    Message,
    LLMResponse,
    ToolDefinition,
    TextContent,
    ImageContent,
    ToolUseContent,
    ToolResultContent,
    ContentBlock,
)


class ClaudeProvider(LLMProvider):
    """Anthropic Claude API provider with tool use and vision support."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def supports_vision(self) -> bool:
        return True

    def supports_tools(self) -> bool:
        return True

    def model_name(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        api_messages = self._convert_messages(messages)
        api_tools = self._convert_tools(tools) if tools else []

        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": api_messages,
            "temperature": temperature,
        }
        if api_tools:
            kwargs["tools"] = api_tools
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self._client.messages.create(**kwargs)
        return self._parse_response(response)

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        api_msgs = []
        for msg in messages:
            if msg.role == "system":
                continue
            content_blocks = []
            for block in msg.content:
                if isinstance(block, TextContent):
                    content_blocks.append({"type": "text", "text": block.text})
                elif isinstance(block, ImageContent):
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": block.media_type,
                            "data": block.base64_data,
                        },
                    })
                elif isinstance(block, ToolResultContent):
                    result_content: list[dict] = [
                        {"type": "text", "text": block.content}
                    ]
                    if block.image:
                        result_content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": block.image.media_type,
                                "data": block.image.base64_data,
                            },
                        })
                    content_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": block.tool_use_id,
                        "content": result_content,
                        "is_error": block.is_error,
                    })
                elif isinstance(block, ToolUseContent):
                    content_blocks.append({
                        "type": "tool_use",
                        "id": block.tool_use_id,
                        "name": block.tool_name,
                        "input": block.tool_input,
                    })
            api_msgs.append({"role": msg.role, "content": content_blocks})
        return api_msgs

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    def _parse_response(self, response) -> LLMResponse:
        blocks: list[ContentBlock] = []
        for block in response.content:
            if block.type == "text":
                blocks.append(TextContent(text=block.text))
            elif block.type == "tool_use":
                blocks.append(ToolUseContent(
                    tool_use_id=block.id,
                    tool_name=block.name,
                    tool_input=block.input,
                ))
        stop = "tool_use" if response.stop_reason == "tool_use" else "end_turn"
        return LLMResponse(
            content=blocks,
            stop_reason=stop,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            raw_response=response,
        )
