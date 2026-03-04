from pydantic import BaseModel, Field
from typing import Optional, Literal


class LLMConfig(BaseModel):
    provider: Literal["claude", "ollama", "claude-code"] = "claude"
    model: Optional[str] = None
    api_key: Optional[str] = None
    ollama_host: str = "http://localhost:11434"
    temperature: float = 0.0
    max_tokens: int = 4096


class ContainerConfig(BaseModel):
    image_name: str = "ctf-desktop-agent:latest"
    container_name: str = "ctf-agent-desktop"
    api_port: int = 8888
    screen_width: int = 1024
    screen_height: int = 768
    memory_limit: str = "4g"
    cpu_count: int = 2
    network_mode: str = "bridge"
    remote_api_url: Optional[str] = None  # Connect to remote target instead of Docker


class AgentConfig(BaseModel):
    max_iterations: int = 50
    max_images_in_context: int = 10
    max_messages: int = 300
    auto_screenshot_after_action: bool = True


class WebUIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class HITLConfig(BaseModel):
    """Human-in-the-Loop configuration."""
    enabled: bool = False
    tool_approval: bool = False
    tools_requiring_approval: list[str] = Field(default_factory=lambda: ["all"])
    tools_auto_approved: list[str] = Field(
        default_factory=lambda: ["ctf_screenshot", "ctf_container_status"]
    )
    checkpoint_enabled: bool = False
    checkpoint_interval: int = 5
    agent_questions: bool = False
    approval_timeout: int = 0  # seconds, 0 = no timeout


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    container: ContainerConfig = Field(default_factory=ContainerConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    web_ui: WebUIConfig = Field(default_factory=WebUIConfig)
    hitl: HITLConfig = Field(default_factory=HITLConfig)
    log_level: str = "INFO"
