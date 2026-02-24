from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from services.file_manager import read_file, write_file, list_directory

router = APIRouter()


class FileReadRequest(BaseModel):
    path: str
    encoding: str = "utf-8"
    binary: bool = False


class FileWriteRequest(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"
    binary: bool = False


class FileResponse(BaseModel):
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    size: Optional[int] = None


@router.post("/read", response_model=FileResponse)
async def read_file_route(req: FileReadRequest):
    """Read a file from the container filesystem."""
    result = read_file(req.path, req.encoding, req.binary)
    return FileResponse(
        success=result.success,
        content=result.content,
        error=result.error,
        size=result.size,
    )


@router.post("/write", response_model=FileResponse)
async def write_file_route(req: FileWriteRequest):
    """Write a file to the container filesystem."""
    result = write_file(req.path, req.content, req.encoding, req.binary)
    return FileResponse(
        success=result.success,
        error=result.error,
        size=result.size,
    )


@router.get("/list")
async def list_directory_route(path: str = "/home/ctfuser"):
    """List files in a directory."""
    return list_directory(path)
