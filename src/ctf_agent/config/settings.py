import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from .models import AppConfig

CONFIG_PATHS = [
    Path("config/default.yaml"),
    Path.home() / ".ctf-agent" / "config.yaml",
    Path("config.yaml"),
]


def load_config() -> AppConfig:
    """
    Load configuration with precedence:
    1. Environment variables (highest)
    2. Config file
    3. Defaults (lowest)
    """
    # Load .env file if present (does not override existing env vars)
    load_dotenv()

    config_data = {}

    for path in CONFIG_PATHS:
        if path.exists():
            with open(path) as f:
                config_data = yaml.safe_load(f) or {}
            break

    config = AppConfig(**config_data)

    # Override with environment variables
    if os.environ.get("CTF_LLM_PROVIDER"):
        config.llm.provider = os.environ["CTF_LLM_PROVIDER"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        config.llm.api_key = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("CTF_LLM_MODEL"):
        config.llm.model = os.environ["CTF_LLM_MODEL"]
    if os.environ.get("CTF_OLLAMA_HOST"):
        config.llm.ollama_host = os.environ["CTF_OLLAMA_HOST"]
    if os.environ.get("CTF_SCREEN_WIDTH"):
        config.container.screen_width = int(os.environ["CTF_SCREEN_WIDTH"])
    if os.environ.get("CTF_SCREEN_HEIGHT"):
        config.container.screen_height = int(os.environ["CTF_SCREEN_HEIGHT"])
    if os.environ.get("CTF_MAX_ITERATIONS"):
        config.agent.max_iterations = int(os.environ["CTF_MAX_ITERATIONS"])
    if os.environ.get("CTF_LOG_LEVEL"):
        config.log_level = os.environ["CTF_LOG_LEVEL"]

    # HITL overrides
    if os.environ.get("CTF_HITL_ENABLED"):
        config.hitl.enabled = os.environ["CTF_HITL_ENABLED"].lower() == "true"
    if os.environ.get("CTF_HITL_TOOL_APPROVAL"):
        config.hitl.tool_approval = os.environ["CTF_HITL_TOOL_APPROVAL"].lower() == "true"
    if os.environ.get("CTF_HITL_CHECKPOINT_INTERVAL"):
        config.hitl.checkpoint_enabled = True
        config.hitl.checkpoint_interval = int(os.environ["CTF_HITL_CHECKPOINT_INTERVAL"])

    return config
