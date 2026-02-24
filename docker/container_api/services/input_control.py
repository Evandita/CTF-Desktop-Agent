import subprocess
import os

DISPLAY = os.environ.get("DISPLAY", ":1")
_ENV = {**os.environ, "DISPLAY": DISPLAY}


def _run_xdotool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["xdotool", *args],
        env=_ENV,
        capture_output=True,
        text=True,
        timeout=5,
    )


def mouse_move(x: int, y: int) -> None:
    _run_xdotool("mousemove", str(x), str(y))


def mouse_click(x: int, y: int, button: int = 1) -> None:
    _run_xdotool("mousemove", str(x), str(y), "click", str(button))


def mouse_double_click(x: int, y: int) -> None:
    _run_xdotool("mousemove", str(x), str(y), "click", "--repeat", "2", "1")


def mouse_right_click(x: int, y: int) -> None:
    _run_xdotool("mousemove", str(x), str(y), "click", "3")


def mouse_drag(x1: int, y1: int, x2: int, y2: int) -> None:
    _run_xdotool(
        "mousemove", str(x1), str(y1),
        "mousedown", "1",
        "mousemove", str(x2), str(y2),
        "mouseup", "1",
    )


def mouse_scroll(x: int, y: int, direction: str, amount: int = 3) -> None:
    button = {"up": "4", "down": "5", "left": "6", "right": "7"}[direction]
    _run_xdotool(
        "mousemove", str(x), str(y),
        "click", "--repeat", str(amount), button,
    )


def type_text(text: str) -> None:
    _run_xdotool("type", "--clearmodifiers", "--delay", "12", text)


def press_key(key: str) -> None:
    _run_xdotool("key", "--clearmodifiers", key)


def key_combo(keys: list[str]) -> None:
    combo = "+".join(keys)
    _run_xdotool("key", "--clearmodifiers", combo)
