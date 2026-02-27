"""Recording manager — captures agent events + screenshots during task execution."""

import base64
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_RECORDINGS_DIR = Path("recordings")

# Event types that trigger a screenshot capture
SCREENSHOT_EVENTS = {"tool_call", "tool_result", "text", "done", "error"}


class RecordingSession:
    """Records a single task execution as a timeline of events + screenshots."""

    def __init__(self, client=None, recordings_dir: Optional[Path] = None):
        self._client = client  # ContainerClient for screenshots
        self._recordings_dir = recordings_dir or DEFAULT_RECORDINGS_DIR
        self._session_id: str = ""
        self._session_dir: Path = Path()
        self._screenshots_dir: Path = Path()
        self._events_file = None
        self._event_index: int = 0
        self._started_at: float = 0
        self._task: str = ""
        self._provider: str = ""
        self._active: bool = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def active(self) -> bool:
        return self._active

    def start(self, task: str, provider: str) -> str:
        """Begin recording a new session. Returns session_id."""
        self._session_id = uuid.uuid4().hex[:12]
        self._task = task
        self._provider = provider
        self._started_at = time.time()
        self._event_index = 0

        self._session_dir = self._recordings_dir / self._session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)

        self._screenshots_dir = self._session_dir / "screenshots"
        self._screenshots_dir.mkdir(exist_ok=True)

        meta = {
            "session_id": self._session_id,
            "task": self._task,
            "provider": self._provider,
            "started_at": self._started_at,
            "ended_at": None,
        }
        (self._session_dir / "meta.json").write_text(json.dumps(meta, indent=2))

        self._events_file = open(self._session_dir / "events.jsonl", "a")
        self._active = True

        logger.info(f"Recording started: {self._session_id} — {task[:80]}")
        return self._session_id

    def record_event(self, event_type: str, data: dict) -> None:
        """Record an event to the JSONL log. Screenshot file saved separately."""
        if not self._active:
            return

        clean_data = _strip_large_values(data)

        entry = {
            "index": self._event_index,
            "timestamp": time.time(),
            "event_type": event_type,
            "data": clean_data,
            "screenshot": None,
        }
        self._event_index += 1

        if self._events_file:
            self._events_file.write(json.dumps(entry) + "\n")
            self._events_file.flush()

    async def capture_screenshot(self, event_index: int) -> None:
        """Take a screenshot and save it as a PNG file for the given event."""
        if not self._active or not self._client:
            return
        try:
            result = await self._client.take_screenshot()
            png_data = base64.b64decode(result.image_base64)
            filename = f"{event_index:04d}.png"
            (self._screenshots_dir / filename).write_bytes(png_data)

            # Update the last event entry to reference the screenshot
            self._patch_last_event_screenshot(event_index, filename)
        except Exception:
            logger.debug("Screenshot capture failed", exc_info=True)

    def _patch_last_event_screenshot(self, event_index: int, filename: str) -> None:
        """Rewrite the JSONL entry for event_index to include screenshot ref."""
        events_path = self._session_dir / "events.jsonl"
        if not events_path.exists():
            return
        lines = events_path.read_text().strip().split("\n")
        for i, line in enumerate(lines):
            try:
                entry = json.loads(line)
                if entry.get("index") == event_index:
                    entry["screenshot"] = filename
                    lines[i] = json.dumps(entry)
                    break
            except json.JSONDecodeError:
                continue
        events_path.write_text("\n".join(lines) + "\n")

    def stop(self) -> None:
        """Stop recording and finalize the session."""
        if not self._active:
            return

        self._active = False

        if self._events_file:
            self._events_file.close()
            self._events_file = None

        meta_path = self._session_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["ended_at"] = time.time()
            meta["duration_seconds"] = round(meta["ended_at"] - meta["started_at"], 1)
            meta["total_events"] = self._event_index
            meta_path.write_text(json.dumps(meta, indent=2))

        self._update_index()

        logger.info(
            f"Recording stopped: {self._session_id} — {self._event_index} events"
        )

    def _update_index(self) -> None:
        """Update the global recordings index.json."""
        index_path = self._recordings_dir / "index.json"

        sessions = []
        if index_path.exists():
            try:
                sessions = json.loads(index_path.read_text())
            except (json.JSONDecodeError, OSError):
                sessions = []

        meta_path = self._session_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            sessions = [s for s in sessions if s.get("session_id") != self._session_id]
            sessions.append(meta)

        sessions.sort(key=lambda s: s.get("started_at", 0), reverse=True)
        index_path.write_text(json.dumps(sessions, indent=2))


def _strip_large_values(data: dict) -> dict:
    """Remove base64 images and other large values from event data."""
    clean = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > 2000:
            if v.startswith("iVBOR") or v.startswith("/9j/"):
                clean[k] = "<image>"
            else:
                clean[k] = v[:2000] + f"... ({len(v)} chars)"
        elif isinstance(v, dict):
            clean[k] = _strip_large_values(v)
        else:
            clean[k] = v
    return clean


def get_screenshot_path(
    session_id: str, filename: str, recordings_dir: Optional[Path] = None
) -> Optional[Path]:
    """Get the filesystem path for a recording screenshot."""
    rd = recordings_dir or DEFAULT_RECORDINGS_DIR
    path = rd / session_id / "screenshots" / filename
    if path.exists():
        return path
    return None


def list_recordings(recordings_dir: Optional[Path] = None) -> list[dict]:
    """List all recorded sessions from the index."""
    rd = recordings_dir or DEFAULT_RECORDINGS_DIR
    index_path = rd / "index.json"
    if not index_path.exists():
        return []
    try:
        return json.loads(index_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def get_recording(session_id: str, recordings_dir: Optional[Path] = None) -> Optional[dict]:
    """Get a recording's metadata + event timeline."""
    rd = recordings_dir or DEFAULT_RECORDINGS_DIR
    session_dir = rd / session_id
    meta_path = session_dir / "meta.json"
    events_path = session_dir / "events.jsonl"

    if not meta_path.exists():
        return None

    meta = json.loads(meta_path.read_text())

    events = []
    if events_path.exists():
        for line in events_path.read_text().strip().split("\n"):
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return {**meta, "events": events}


def delete_recording(session_id: str, recordings_dir: Optional[Path] = None) -> bool:
    """Delete a recording session and its files."""
    import shutil

    rd = recordings_dir or DEFAULT_RECORDINGS_DIR
    session_dir = rd / session_id
    if not session_dir.exists():
        return False

    shutil.rmtree(session_dir)

    index_path = rd / "index.json"
    if index_path.exists():
        try:
            sessions = json.loads(index_path.read_text())
            sessions = [s for s in sessions if s.get("session_id") != session_id]
            index_path.write_text(json.dumps(sessions, indent=2))
        except (json.JSONDecodeError, OSError):
            pass

    return True
