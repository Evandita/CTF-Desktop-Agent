import json
import re
import uuid
import ollama as ollama_client
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


class OllamaProvider(LLMProvider):
    """Ollama local model provider with vision and emulated tool calling."""

    VISION_MODELS = {
        "llava", "llava:7b", "llava:13b", "llava:34b",
        "llama3.2-vision", "llama3.2-vision:11b", "llama3.2-vision:90b",
        "moondream",
    }

    def __init__(
        self,
        model: str = "llava",
        host: str = "http://localhost:11434",
    ):
        self._model = model
        self._host = host
        self._ollama = ollama_client.Client(host=host)

    def supports_vision(self) -> bool:
        base_model = self._model.split(":")[0]
        return base_model in self.VISION_MODELS

    def supports_tools(self) -> bool:
        return True  # Emulated via prompt engineering

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
        ollama_messages = self._convert_messages(messages, tools, system_prompt)

        response = self._ollama.chat(
            model=self._model,
            messages=ollama_messages,
            options={"temperature": temperature, "num_predict": max_tokens},
        )

        return self._parse_response(response, tools)

    def _convert_messages(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        system_prompt: str | None,
    ) -> list[dict]:
        ollama_msgs = []

        sys_text = system_prompt or ""
        if tools:
            sys_text = f"{sys_text}\n\n{self._build_tool_prompt(tools)}"
        if sys_text:
            ollama_msgs.append({"role": "system", "content": sys_text})

        for msg in messages:
            if msg.role == "system":
                continue
            images = []
            text_parts = []
            for block in msg.content:
                if isinstance(block, TextContent):
                    text_parts.append(block.text)
                elif isinstance(block, ImageContent):
                    images.append(block.base64_data)
                elif isinstance(block, ToolResultContent):
                    text_parts.append(
                        f'<tool_result name="{block.tool_use_id}">\n'
                        f"{block.content}\n</tool_result>"
                    )
                elif isinstance(block, ToolUseContent):
                    text_parts.append(
                        f'<tool_call name="{block.tool_name}">\n'
                        f"{json.dumps(block.tool_input)}\n</tool_call>"
                    )
            entry: dict = {"role": msg.role, "content": "\n".join(text_parts)}
            if images:
                entry["images"] = images
            ollama_msgs.append(entry)

        return ollama_msgs

    def _build_tool_prompt(self, tools: list[ToolDefinition]) -> str:
        lines = [
            "You have access to the following tools. To use a tool, respond with "
            "EXACTLY this format on its own line:",
            "",
            '<tool_call name="TOOL_NAME">',
            '{"param1": "value1", "param2": "value2"}',
            "</tool_call>",
            "",
            "You may use multiple tools in a single response. "
            "Always include your reasoning before tool calls.",
            "",
            "Available tools:",
        ]
        for t in tools:
            lines.append(f"\n## {t.name}")
            lines.append(t.description)
            lines.append(f"Parameters: {json.dumps(t.parameters, indent=2)}")
        return "\n".join(lines)

    def _parse_response(
        self, response: dict, tools: list[ToolDefinition] | None
    ) -> LLMResponse:
        text = response["message"]["content"]
        blocks: list[ContentBlock] = []

        if tools:
            pattern = r'<tool_call name="(\w+)">\s*(\{.*?\})\s*</tool_call>'
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                remaining = re.sub(pattern, "", text, flags=re.DOTALL).strip()
                if remaining:
                    blocks.append(TextContent(text=remaining))
                for name, params_str in matches:
                    try:
                        params = json.loads(params_str)
                    except json.JSONDecodeError:
                        params = {}
                    blocks.append(ToolUseContent(
                        tool_use_id=f"ollama_{uuid.uuid4().hex[:12]}",
                        tool_name=name,
                        tool_input=params,
                    ))
                return LLMResponse(
                    content=blocks,
                    stop_reason="tool_use",
                    usage={},
                    raw_response=response,
                )

        blocks.append(TextContent(text=text))
        return LLMResponse(
            content=blocks,
            stop_reason="end_turn",
            usage={},
            raw_response=response,
        )
