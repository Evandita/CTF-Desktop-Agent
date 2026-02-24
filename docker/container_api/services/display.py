import subprocess
import base64
import os

DISPLAY = os.environ.get("DISPLAY", ":1")
_ENV = {**os.environ, "DISPLAY": DISPLAY}


def capture_screenshot() -> tuple[str, int, int]:
    """Capture full screen via scrot. Returns (base64_png, width, height)."""
    tmp_path = "/tmp/screenshot.png"
    subprocess.run(
        ["scrot", "-o", tmp_path],
        env=_ENV,
        check=True,
        timeout=10,
    )
    with open(tmp_path, "rb") as f:
        img_bytes = f.read()

    result = subprocess.run(
        ["identify", "-format", "%w %h", tmp_path],
        capture_output=True,
        text=True,
        timeout=5,
    )
    w, h = map(int, result.stdout.strip().split())
    return base64.b64encode(img_bytes).decode("ascii"), w, h


def capture_region(x: int, y: int, w: int, h: int) -> tuple[str, int, int]:
    """Capture a region of the screen. Returns (base64_png, width, height)."""
    tmp_path = "/tmp/screenshot_region.png"
    subprocess.run(
        [
            "import",
            "-window",
            "root",
            "-crop",
            f"{w}x{h}+{x}+{y}",
            "+repage",
            tmp_path,
        ],
        env=_ENV,
        check=True,
        timeout=10,
    )
    with open(tmp_path, "rb") as f:
        img_bytes = f.read()
    return base64.b64encode(img_bytes).decode("ascii"), w, h
