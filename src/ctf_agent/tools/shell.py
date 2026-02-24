from .base import Tool, ToolResult
from ctf_agent.container.client import ContainerClient


class ExecuteCommandTool(Tool):
    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return "execute_command"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the container's terminal. "
            "This is a Kali Linux environment with security tools pre-installed: "
            "nmap, gobuster, john, hashcat, binwalk, steghide, pwntools, "
            "gdb+pwndbg, radare2, sqlmap, wireshark-cli, hydra, netcat, and more. "
            "Returns stdout, stderr, and the return code. "
            "Prefer this over GUI interaction when possible."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                    "default": 30,
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the command",
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        result = await self._client.execute_command(
            command=command, timeout=timeout, working_dir=working_dir
        )
        output_parts = []
        if result.stdout:
            output_parts.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")
        output_parts.append(f"Return code: {result.return_code}")
        if result.timed_out:
            output_parts.append("WARNING: Command timed out")

        return ToolResult(
            output="\n".join(output_parts),
            is_error=result.return_code != 0,
        )
