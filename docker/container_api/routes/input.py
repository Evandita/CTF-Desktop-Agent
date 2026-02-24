from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional
from services import input_control

router = APIRouter()


class MouseAction(BaseModel):
    action: Literal["click", "double_click", "right_click", "move", "drag", "scroll"]
    x: int
    y: int
    button: int = 1
    end_x: Optional[int] = None
    end_y: Optional[int] = None
    scroll_direction: Optional[Literal["up", "down", "left", "right"]] = None
    scroll_amount: int = 3


class KeyboardAction(BaseModel):
    action: Literal["type", "key", "key_combo"]
    text: Optional[str] = None
    key: Optional[str] = None
    keys: Optional[list[str]] = None


class ActionResponse(BaseModel):
    success: bool
    error: Optional[str] = None


@router.post("/mouse", response_model=ActionResponse)
async def mouse_action(action: MouseAction):
    """Execute a mouse action using xdotool."""
    try:
        if action.action == "click":
            input_control.mouse_click(action.x, action.y, action.button)
        elif action.action == "double_click":
            input_control.mouse_double_click(action.x, action.y)
        elif action.action == "right_click":
            input_control.mouse_right_click(action.x, action.y)
        elif action.action == "move":
            input_control.mouse_move(action.x, action.y)
        elif action.action == "drag":
            if action.end_x is None or action.end_y is None:
                return ActionResponse(
                    success=False, error="end_x and end_y required for drag"
                )
            input_control.mouse_drag(
                action.x, action.y, action.end_x, action.end_y
            )
        elif action.action == "scroll":
            if not action.scroll_direction:
                return ActionResponse(
                    success=False, error="scroll_direction required for scroll"
                )
            input_control.mouse_scroll(
                action.x, action.y, action.scroll_direction, action.scroll_amount
            )
        return ActionResponse(success=True)
    except Exception as e:
        return ActionResponse(success=False, error=str(e))


@router.post("/keyboard", response_model=ActionResponse)
async def keyboard_action(action: KeyboardAction):
    """Execute a keyboard action using xdotool."""
    try:
        if action.action == "type":
            if not action.text:
                return ActionResponse(
                    success=False, error="text required for type action"
                )
            input_control.type_text(action.text)
        elif action.action == "key":
            if not action.key:
                return ActionResponse(
                    success=False, error="key required for key action"
                )
            input_control.press_key(action.key)
        elif action.action == "key_combo":
            if not action.keys:
                return ActionResponse(
                    success=False, error="keys required for key_combo action"
                )
            input_control.key_combo(action.keys)
        return ActionResponse(success=True)
    except Exception as e:
        return ActionResponse(success=False, error=str(e))
