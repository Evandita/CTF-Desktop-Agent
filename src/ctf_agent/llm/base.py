from abc import ABC, abstractmethod
from .message_types import Message, LLMResponse, ToolDefinition


class LLMProvider(ABC):
    """Abstract interface for LLM backends."""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        ...

    @abstractmethod
    def supports_vision(self) -> bool:
        ...

    @abstractmethod
    def supports_tools(self) -> bool:
        ...

    @abstractmethod
    def model_name(self) -> str:
        ...
