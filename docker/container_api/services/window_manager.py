import subprocess
import os
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

DISPLAY = os.environ.get("DISPLAY", ":1")
_ENV = {**os.environ, "DISPLAY": DISPLAY}

TERMINAL_WINDOW_TITLE = "CTF Agent Terminal"


def _run_xdotool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["xdotool", *args],
        env=_ENV,
        capture_output=True,
        text=True,
        timeout=5,
    )


def find_window_by_name(name: str) -> Optional[int]:
    """Find a window by name (substring match). Returns window ID or None."""
    try:
        result = _run_xdotool("search", "--name", name)
        if result.returncode == 0 and result.stdout.strip():
            first_id = result.stdout.strip().splitlines()[0]
            return int(first_id)
    except (ValueError, subprocess.TimeoutExpired):
        pass
    return None


def find_window_by_class(class_name: str) -> Optional[int]:
    """Find a window by WM_CLASS. Returns window ID or None."""
    try:
        result = _run_xdotool("search", "--class", class_name)
        if result.returncode == 0 and result.stdout.strip():
            first_id = result.stdout.strip().splitlines()[0]
            return int(first_id)
    except (ValueError, subprocess.TimeoutExpired):
        pass
    return None


def get_active_window() -> Optional[int]:
    """Get the currently active (focused) window ID."""
    try:
        result = _run_xdotool("getactivewindow")
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        pass
    return None


def activate_window(window_id: int) -> bool:
    """Bring a window to the foreground and focus it."""
    try:
        result = _run_xdotool("windowactivate", "--sync", str(window_id))
        if result.returncode == 0:
            time.sleep(0.15)
            return True
    except subprocess.TimeoutExpired:
        pass
    return False


def focus_window_by_name(name: str) -> tuple[bool, str]:
    """Find and activate a window by name. Returns (success, message)."""
    window_id = find_window_by_name(name)
    if window_id is None:
        return False, f"No window found matching name: {name}"
    if activate_window(window_id):
        return True, f"Window '{name}' (id={window_id}) activated"
    return False, f"Failed to activate window id={window_id}"


def focus_window_by_class(class_name: str) -> tuple[bool, str]:
    """Find and activate a window by class. Returns (success, message)."""
    window_id = find_window_by_class(class_name)
    if window_id is None:
        return False, f"No window found matching class: {class_name}"
    if activate_window(window_id):
        return True, f"Window class '{class_name}' (id={window_id}) activated"
    return False, f"Failed to activate window id={window_id}"


def raise_terminal() -> bool:
    """Bring the CTF Agent Terminal to the foreground. Fail-safe: never raises."""
    try:
        window_id = find_window_by_name(TERMINAL_WINDOW_TITLE)
        if window_id is None:
            logger.warning("Terminal window not found: %s", TERMINAL_WINDOW_TITLE)
            return False
        return activate_window(window_id)
    except Exception as e:
        logger.warning("Failed to raise terminal window: %s", e)
        return False


def list_windows() -> list[dict]:
    """List all visible windows with their IDs and titles."""
    try:
        result = _run_xdotool("search", "--onlyvisible", "--name", "")
        if result.returncode != 0 or not result.stdout.strip():
            return []
    except subprocess.TimeoutExpired:
        return []

    windows = []
    for line in result.stdout.strip().splitlines():
        try:
            wid = int(line.strip())
            name_result = _run_xdotool("getwindowname", str(wid))
            name = name_result.stdout.strip() if name_result.returncode == 0 else ""
            if name:
                windows.append({"window_id": wid, "name": name})
        except (ValueError, subprocess.TimeoutExpired):
            continue
    return windows
