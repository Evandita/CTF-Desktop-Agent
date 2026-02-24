import os
import base64
from dataclasses import dataclass
from typing import Optional


@dataclass
class FileResult:
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    size: Optional[int] = None


def read_file(
    path: str,
    encoding: str = "utf-8",
    binary: bool = False,
) -> FileResult:
    """Read a file. If binary=True, returns base64-encoded content."""
    try:
        if binary:
            with open(path, "rb") as f:
                data = f.read()
            return FileResult(
                success=True,
                content=base64.b64encode(data).decode("ascii"),
                size=len(data),
            )
        else:
            with open(path, "r", encoding=encoding) as f:
                content = f.read()
            return FileResult(
                success=True,
                content=content,
                size=len(content),
            )
    except Exception as e:
        return FileResult(success=False, error=str(e))


def write_file(
    path: str,
    content: str,
    encoding: str = "utf-8",
    binary: bool = False,
) -> FileResult:
    """Write a file. If binary=True, content is base64-encoded."""
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        if binary:
            data = base64.b64decode(content)
            with open(path, "wb") as f:
                f.write(data)
            return FileResult(success=True, size=len(data))
        else:
            with open(path, "w", encoding=encoding) as f:
                f.write(content)
            return FileResult(success=True, size=len(content))
    except Exception as e:
        return FileResult(success=False, error=str(e))


def list_directory(path: str = "/home/ctfuser") -> dict:
    """List files and directories at the given path."""
    try:
        entries = []
        for entry in os.scandir(path):
            entries.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
            })
        return {"success": True, "path": path, "entries": entries}
    except Exception as e:
        return {"success": False, "error": str(e)}
