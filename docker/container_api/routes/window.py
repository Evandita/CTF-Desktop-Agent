from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from services import window_manager

router = APIRouter()


class FocusWindowRequest(BaseModel):
    name: Optional[str] = None
    class_name: Optional[str] = None
    window_id: Optional[int] = None


class FocusWindowResponse(BaseModel):
    success: bool
    message: str
    window_id: Optional[int] = None


class WindowInfo(BaseModel):
    window_id: int
    name: str


class ListWindowsResponse(BaseModel):
    windows: list[WindowInfo]
    active_window_id: Optional[int] = None


@router.post("/focus", response_model=FocusWindowResponse)
async def focus_window(req: FocusWindowRequest):
    """Bring a window to the foreground by name, class, or ID."""
    if req.window_id is not None:
        success = window_manager.activate_window(req.window_id)
        msg = (
            f"Window {req.window_id} activated"
            if success
            else f"Failed to activate window {req.window_id}"
        )
        return FocusWindowResponse(
            success=success,
            message=msg,
            window_id=req.window_id if success else None,
        )
    elif req.name:
        success, msg = window_manager.focus_window_by_name(req.name)
        wid = window_manager.find_window_by_name(req.name) if success else None
        return FocusWindowResponse(success=success, message=msg, window_id=wid)
    elif req.class_name:
        success, msg = window_manager.focus_window_by_class(req.class_name)
        wid = window_manager.find_window_by_class(req.class_name) if success else None
        return FocusWindowResponse(success=success, message=msg, window_id=wid)
    else:
        return FocusWindowResponse(
            success=False,
            message="Must provide name, class_name, or window_id",
        )


@router.get("/list", response_model=ListWindowsResponse)
async def list_windows():
    """List all visible windows."""
    windows = window_manager.list_windows()
    active = window_manager.get_active_window()
    return ListWindowsResponse(
        windows=[WindowInfo(**w) for w in windows],
        active_window_id=active,
    )
