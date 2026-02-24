from .base import LLMProvider
from .claude_provider import ClaudeProvider
from .ollama_provider import OllamaProvider
from .claude_code_provider import ClaudeCodeProvider
from ctf_agent.config.models import LLMConfig


def get_provider(config: LLMConfig) -> LLMProvider:
    """Instantiate an LLM provider for the standard agent loop (claude/ollama)."""
    if config.provider == "claude":
        if not config.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for Claude provider. "
                "Set it in .env or as an environment variable."
            )
        return ClaudeProvider(
            api_key=config.api_key,
            model=config.model or "claude-sonnet-4-20250514",
        )
    elif config.provider == "ollama":
        return OllamaProvider(
            model=config.model or "llava",
            host=config.ollama_host,
        )
    elif config.provider == "claude-code":
        raise ValueError(
            "claude-code provider uses a different execution path. "
            "Use get_claude_code_provider() instead."
        )
    else:
        raise ValueError(f"Unknown LLM provider: {config.provider}")


def get_claude_code_provider(
    config: LLMConfig,
    system_prompt: str | None = None,
    max_turns: int | None = None,
    container_api_url: str | None = None,
) -> ClaudeCodeProvider:
    """Instantiate the Claude Code provider (subprocess-based)."""
    return ClaudeCodeProvider(
        model=config.model,
        max_turns=max_turns,
        system_prompt=system_prompt,
        container_api_url=container_api_url,
    )
