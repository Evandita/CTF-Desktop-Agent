import subprocess
import uuid
import asyncio
import os
import time
import shlex
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Store for async command results
_async_results: dict[str, "CommandResult"] = {}

# Directory for temp files used by visible execution
EXEC_TEMP_DIR = "/tmp/ctf-exec"

# tmux session name and shared socket (root API + ctfuser desktop share this)
TMUX_SESSION = "ctf"
TMUX_SOCKET = "/tmp/ctf-tmux"

# Ensure temp directory exists
os.makedirs(EXEC_TEMP_DIR, exist_ok=True)


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool
    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])


def _tmux_session_exists() -> bool:
    """Check if the ctf tmux session is alive."""
    try:
        result = subprocess.run(
            ["tmux", "-S", TMUX_SOCKET, "has-session", "-t", TMUX_SESSION],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _ensure_tmux_session() -> bool:
    """Ensure the tmux session exists, creating it if necessary."""
    if _tmux_session_exists():
        return True
    try:
        subprocess.run(
            ["tmux", "-S", TMUX_SOCKET, "new-session", "-d", "-s", TMUX_SESSION, "-x", "200", "-y", "50"],
            capture_output=True,
            timeout=10,
        )
        return _tmux_session_exists()
    except Exception as e:
        logger.error(f"Failed to create tmux session: {e}")
        return False


def _read_file_safe(path: str) -> str:
    """Read a file, returning empty string if it doesn't exist or errors."""
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""


def run_command_visible(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
) -> CommandResult:
    """Execute a command visibly in the tmux terminal session.

    The command appears in the terminal window on the desktop (visible via noVNC)
    while stdout/stderr/exitcode are captured via temp files for programmatic use.

    Falls back to run_command_silent() if tmux is unavailable.
    """
    exec_id = uuid.uuid4().hex[:16]

    if not _ensure_tmux_session():
        logger.warning("tmux session unavailable, falling back to silent execution")
        return run_command_silent(command, timeout, working_dir)

    cmd_file = os.path.join(EXEC_TEMP_DIR, f"{exec_id}.cmd")
    stdout_file = os.path.join(EXEC_TEMP_DIR, f"{exec_id}.stdout")
    stderr_file = os.path.join(EXEC_TEMP_DIR, f"{exec_id}.stderr")
    rc_file = os.path.join(EXEC_TEMP_DIR, f"{exec_id}.rc")

    try:
        # Write the command to a file (avoids escaping issues with tmux send-keys)
        with open(cmd_file, "w") as f:
            f.write(command)

        # Build the ctf-exec invocation
        exec_args = [shlex.quote(exec_id), shlex.quote(EXEC_TEMP_DIR)]
        if working_dir:
            exec_args.append(shlex.quote(working_dir))
        exec_cmd = f"/usr/local/bin/ctf-exec {' '.join(exec_args)}"

        # Send the command to tmux
        subprocess.run(
            ["tmux", "-S", TMUX_SOCKET, "send-keys", "-t", TMUX_SESSION, exec_cmd, "Enter"],
            capture_output=True,
            timeout=5,
        )

        # Poll for the .rc file (completion signal)
        poll_interval = 0.2
        elapsed = 0.0

        while elapsed < timeout:
            if os.path.exists(rc_file):
                time.sleep(0.05)  # small delay to ensure file is fully written
                break
            time.sleep(poll_interval)
            elapsed += poll_interval

        # Handle timeout
        if not os.path.exists(rc_file):
            # Send Ctrl+C to kill the running command
            subprocess.run(
                ["tmux", "-S", TMUX_SOCKET, "send-keys", "-t", TMUX_SESSION, "C-c", ""],
                capture_output=True,
                timeout=5,
            )
            time.sleep(0.5)
            subprocess.run(
                ["tmux", "-S", TMUX_SOCKET, "send-keys", "-t", TMUX_SESSION, "C-c", ""],
                capture_output=True,
                timeout=5,
            )
            time.sleep(0.2)
            # Send Enter to reset prompt
            subprocess.run(
                ["tmux", "-S", TMUX_SOCKET, "send-keys", "-t", TMUX_SESSION, "", "Enter"],
                capture_output=True,
                timeout=5,
            )
            return CommandResult(
                stdout=_read_file_safe(stdout_file),
                stderr=f"Command timed out after {timeout} seconds",
                return_code=-1,
                timed_out=True,
                execution_id=exec_id,
            )

        # Read results
        stdout = _read_file_safe(stdout_file)
        stderr = _read_file_safe(stderr_file)
        try:
            return_code = int(_read_file_safe(rc_file).strip())
        except (ValueError, TypeError):
            return_code = -1

        return CommandResult(
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
            timed_out=False,
            execution_id=exec_id,
        )

    except Exception as e:
        logger.error(f"Visible execution error: {e}")
        return CommandResult(
            stdout="",
            stderr=str(e),
            return_code=-1,
            timed_out=False,
            execution_id=exec_id,
        )
    finally:
        # Cleanup temp files
        for suffix in (".cmd", ".stdout", ".stderr", ".rc", ".fifo"):
            path = os.path.join(EXEC_TEMP_DIR, f"{exec_id}{suffix}")
            try:
                os.unlink(path)
            except OSError:
                pass


def run_command_silent(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
) -> CommandResult:
    """Execute a shell command silently via subprocess (original behavior)."""
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


def run_command(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
    visible: bool = True,
) -> CommandResult:
    """Execute a shell command.

    Args:
        command: Shell command to execute.
        timeout: Timeout in seconds.
        working_dir: Working directory for the command.
        visible: If True (default), run in the visible tmux terminal.
                 If False, run silently via subprocess.
    """
    if visible:
        return run_command_visible(command, timeout, working_dir)
    else:
        return run_command_silent(command, timeout, working_dir)


async def run_command_async(
    command: str,
    timeout: int = 300,
    working_dir: Optional[str] = None,
    visible: bool = True,
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

    if visible:
        # run_command_visible blocks (polling), so run in a thread
        async def _run_visible():
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, run_command_visible, command, timeout, working_dir
            )
            result.execution_id = exec_id
            _async_results[exec_id] = result

        asyncio.create_task(_run_visible())
    else:
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
