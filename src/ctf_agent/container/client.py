import httpx
import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScreenshotResult:
    image_base64: str
    width: int
    height: int
    timestamp: float


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool
    execution_id: str


class ContainerClient:
    """Async HTTP client for communicating with the container API."""

    def __init__(self, base_url: str = "http://localhost:8888", timeout: float = 60.0):
        self._base_url = base_url
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def wait_until_ready(self, max_wait: float = 60.0) -> bool:
        """Poll the health endpoint until the container API is up."""
        elapsed = 0.0
        while elapsed < max_wait:
            try:
                resp = await self._http.get("/health/")
                if resp.status_code == 200:
                    return True
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
                pass
            await asyncio.sleep(1.0)
            elapsed += 1.0
        return False

    async def take_screenshot(self) -> ScreenshotResult:
        resp = await self._http.get("/screenshot/")
        resp.raise_for_status()
        data = resp.json()
        return ScreenshotResult(**data)

    async def mouse_action(
        self,
        action: str,
        x: int,
        y: int,
        button: int = 1,
        end_x: int | None = None,
        end_y: int | None = None,
        scroll_direction: str | None = None,
        scroll_amount: int = 3,
    ) -> None:
        payload = {
            "action": action,
            "x": x,
            "y": y,
            "button": button,
            "end_x": end_x,
            "end_y": end_y,
            "scroll_direction": scroll_direction,
            "scroll_amount": scroll_amount,
        }
        resp = await self._http.post("/input/mouse", json=payload)
        resp.raise_for_status()

    async def keyboard_action(
        self,
        action: str,
        text: str | None = None,
        key: str | None = None,
        keys: list[str] | None = None,
    ) -> None:
        payload = {"action": action, "text": text, "key": key, "keys": keys}
        resp = await self._http.post("/input/keyboard", json=payload)
        resp.raise_for_status()

    async def execute_command(
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
    ) -> ShellResult:
        payload = {
            "command": command,
            "timeout": timeout,
            "working_dir": working_dir,
        }
        resp = await self._http.post("/shell/exec", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return ShellResult(**data)

    async def read_file(self, path: str, binary: bool = False) -> str:
        resp = await self._http.post(
            "/files/read", json={"path": path, "binary": binary}
        )
        resp.raise_for_status()
        return resp.json()["content"]

    async def write_file(
        self, path: str, content: str, binary: bool = False
    ) -> None:
        resp = await self._http.post(
            "/files/write",
            json={"path": path, "content": content, "binary": binary},
        )
        resp.raise_for_status()

    async def close(self) -> None:
        await self._http.aclose()
