import subprocess
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

DISPLAY = ":1"


class ClipboardContent(BaseModel):
    text: str


@router.post("/set")
async def set_clipboard(content: ClipboardContent):
    """Set the X CLIPBOARD selection using xclip."""
    try:
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=content.text.encode("utf-8"),
            capture_output=True,
            timeout=5,
            env={"DISPLAY": DISPLAY},
        )
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr.decode()}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/get")
async def get_clipboard():
    """Get the X CLIPBOARD selection using xclip."""
    try:
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            timeout=5,
            env={"DISPLAY": DISPLAY},
        )
        return {"ok": True, "text": proc.stdout.decode("utf-8", errors="replace")}
    except Exception as e:
        return {"ok": False, "text": "", "error": str(e)}
