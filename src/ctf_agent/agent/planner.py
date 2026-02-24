from ctf_agent.llm.base import LLMProvider
from ctf_agent.llm.message_types import Message, TextContent

PLANNING_PROMPT = """You are a CTF challenge planning assistant. Given the following task, break it down into a numbered list of concrete steps to solve it. Each step should be specific and actionable.

Consider:
- What information do you need to gather first?
- What tools should be used at each stage?
- What order makes the most logical sense?
- Are there alternative approaches if one fails?

Task: {task}

Provide your plan as a numbered list. Be specific about commands, tools, and techniques."""


class TaskPlanner:
    """Uses the LLM to break a high-level task into a step-by-step plan."""

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    async def create_plan(self, task_description: str) -> str:
        prompt = PLANNING_PROMPT.format(task=task_description)
        response = await self._llm.chat(
            messages=[Message(role="user", content=[TextContent(text=prompt)])],
            system_prompt=(
                "You are an expert CTF strategist. Provide clear, "
                "actionable plans for solving cybersecurity challenges."
            ),
            max_tokens=2048,
        )
        for block in response.content:
            if isinstance(block, TextContent):
                return block.text
        return "Could not generate plan."
