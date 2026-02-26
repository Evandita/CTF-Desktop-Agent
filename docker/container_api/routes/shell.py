from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from services.command_runner import run_command, run_command_async, get_async_result

router = APIRouter()


class ShellCommand(BaseModel):
    command: str
    timeout: int = 30
    working_dir: Optional[str] = None
    visible: bool = True


class ShellResult(BaseModel):
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool
    execution_id: str


@router.post("/exec", response_model=ShellResult)
async def execute_command(cmd: ShellCommand):
    """Execute a shell command and return results."""
    result = run_command(
        command=cmd.command,
        timeout=cmd.timeout,
        working_dir=cmd.working_dir,
        visible=cmd.visible,
    )
    return ShellResult(
        stdout=result.stdout,
        stderr=result.stderr,
        return_code=result.return_code,
        timed_out=result.timed_out,
        execution_id=result.execution_id,
    )


@router.post("/exec/async")
async def execute_command_async(cmd: ShellCommand):
    """Start a long-running command. Returns execution_id for polling."""
    exec_id = await run_command_async(
        command=cmd.command,
        timeout=cmd.timeout,
        working_dir=cmd.working_dir,
        visible=cmd.visible,
    )
    return {"execution_id": exec_id, "status": "started"}


@router.get("/exec/{execution_id}", response_model=ShellResult)
async def get_command_result(execution_id: str):
    """Poll for an async command result."""
    result = get_async_result(execution_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Execution ID not found")
    return ShellResult(
        stdout=result.stdout,
        stderr=result.stderr,
        return_code=result.return_code,
        timed_out=result.timed_out,
        execution_id=result.execution_id,
    )
