import subprocess
import uuid
import asyncio
from dataclasses import dataclass, field
from typing import Optional

# Store for async command results
_async_results: dict[str, "CommandResult"] = {}


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool
    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])


def run_command(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
) -> CommandResult:
    """Execute a shell command synchronously with timeout."""
    exec_id = uuid.uuid4().hex[:16]
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )
        return CommandResult(
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
            timed_out=False,
            execution_id=exec_id,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
            return_code=-1,
            timed_out=True,
            execution_id=exec_id,
        )
    except Exception as e:
        return CommandResult(
            stdout="",
            stderr=str(e),
            return_code=-1,
            timed_out=False,
            execution_id=exec_id,
        )


async def run_command_async(
    command: str,
    timeout: int = 300,
    working_dir: Optional[str] = None,
) -> str:
    """Start a command asynchronously. Returns execution_id for polling."""
    exec_id = uuid.uuid4().hex[:16]
    _async_results[exec_id] = CommandResult(
        stdout="",
        stderr="",
        return_code=-999,  # sentinel: still running
        timed_out=False,
        execution_id=exec_id,
    )

    async def _run():
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                _async_results[exec_id] = CommandResult(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    return_code=proc.returncode or 0,
                    timed_out=False,
                    execution_id=exec_id,
                )
            except asyncio.TimeoutError:
                proc.kill()
                _async_results[exec_id] = CommandResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout} seconds",
                    return_code=-1,
                    timed_out=True,
                    execution_id=exec_id,
                )
        except Exception as e:
            _async_results[exec_id] = CommandResult(
                stdout="",
                stderr=str(e),
                return_code=-1,
                timed_out=False,
                execution_id=exec_id,
            )

    asyncio.create_task(_run())
    return exec_id


def get_async_result(execution_id: str) -> Optional[CommandResult]:
    """Get result of an async command. Returns None if not found."""
    return _async_results.get(execution_id)
