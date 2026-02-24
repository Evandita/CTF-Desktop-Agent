import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.display import capture_screenshot, capture_region

router = APIRouter()


class ScreenshotResponse(BaseModel):
    image_base64: str
    width: int
    height: int
    timestamp: float


@router.get("/", response_model=ScreenshotResponse)
async def take_screenshot():
    """Capture the full current display."""
    try:
        b64, w, h = capture_screenshot()
        return ScreenshotResponse(
            image_base64=b64, width=w, height=h, timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/region", response_model=ScreenshotResponse)
async def take_screenshot_region(x: int, y: int, width: int, height: int):
    """Capture a specific region of the display."""
    try:
        b64, w, h = capture_region(x, y, width, height)
        return ScreenshotResponse(
            image_base64=b64, width=w, height=h, timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
