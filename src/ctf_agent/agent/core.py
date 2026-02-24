import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from ctf_agent.llm.base import LLMProvider
from ctf_agent.llm.message_types import (
    Message,
    TextContent,
    ImageContent,
    ToolUseContent,
    ToolResultContent,
    ContentBlock,
)
from ctf_agent.tools.registry import ToolRegistry
from ctf_agent.agent.context import ConversationContext
from ctf_agent.agent.prompts import build_system_prompt

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """Event emitted during agent execution for UI consumption."""
    event_type: str  # "thinking", "tool_call", "tool_result", "text", "error", "done"
    data: dict = field(default_factory=dict)


class AgentCore:
    """
    The main agent loop. Sends messages to the LLM, executes tool calls,
    and iterates until the task is complete or limits are reached.
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        screen_width: int = 1024,
        screen_height: int = 768,
        max_iterations: int = 50,
        max_images_in_context: int = 10,
    ):
        self._llm = llm
        self._tools = tools
        self._context = ConversationContext(
            max_images=max_images_in_context,
            max_messages=300,
        )
        self._system_prompt = build_system_prompt(screen_width, screen_height)
        self._max_iterations = max_iterations
        self._running = False

    @property
    def context(self) -> ConversationContext:
        return self._context

    async def run(
        self,
        user_message: str,
        event_callback: Optional[Callable[[AgentEvent], None]] = None,
    ) -> str:
        """
        Run the agent loop for a user message.
        Returns the final text response from the agent.
        """
        self._running = True

        self._context.add_message(
            Message(role="user", content=[TextContent(text=user_message)])
        )

        final_text = ""
        iteration = 0

        while self._running and iteration < self._max_iterations:
            iteration += 1
            logger.info(f"Agent iteration {iteration}/{self._max_iterations}")

            if event_callback:
                event_callback(AgentEvent("thinking", {"iteration": iteration}))

            response = await self._llm.chat(
                messages=self._context.get_messages_for_api(),
                tools=self._tools.get_definitions(),
                system_prompt=self._system_prompt,
            )

            self._context.add_message(
                Message(role="assistant", content=response.content)
            )

            tool_results: list[ContentBlock] = []
            for block in response.content:
                if isinstance(block, TextContent):
                    final_text = block.text
                    if event_callback:
                        event_callback(
                            AgentEvent("text", {"text": block.text})
                        )

                elif isinstance(block, ToolUseContent):
                    logger.info(
                        f"Tool call: {block.tool_name}({block.tool_input})"
                    )
                    if event_callback:
                        event_callback(AgentEvent("tool_call", {
                            "tool": block.tool_name,
                            "input": block.tool_input,
                        }))

                    result = await self._tools.execute(
                        block.tool_name, **block.tool_input
                    )

                    logger.info(f"Tool result: {result.output[:200]}")
                    if event_callback:
                        event_callback(AgentEvent("tool_result", {
                            "tool": block.tool_name,
                            "output": result.output,
                            "has_image": result.base64_image is not None,
                            "is_error": result.is_error,
                        }))

                    tool_result_block = ToolResultContent(
                        tool_use_id=block.tool_use_id,
                        content=result.output,
                        image=(
                            ImageContent(base64_data=result.base64_image)
                            if result.base64_image
                            else None
                        ),
                        is_error=result.is_error,
                    )
                    tool_results.append(tool_result_block)

            # If no tools were used, the agent is done
            if response.stop_reason != "tool_use" or not tool_results:
                if event_callback:
                    event_callback(AgentEvent("done", {"text": final_text}))
                break

            # Add tool results and continue the loop
            self._context.add_message(
                Message(role="user", content=tool_results)
            )

        self._running = False
        return final_text

    def stop(self) -> None:
        """Signal the agent to stop after the current iteration."""
        self._running = False
