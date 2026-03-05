import docker
import logging
from ctf_agent.config.models import ContainerConfig

logger = logging.getLogger(__name__)


class ContainerManager:
    """Manages Docker container lifecycle for the CTF desktop environment."""

    def __init__(self, config: ContainerConfig):
        self._config = config
        self._docker = docker.from_env()
        self._container = None

    def build_image(self, dockerfile_path: str = "docker") -> None:
        """Build the Docker image from the Dockerfile."""
        logger.info(f"Building image {self._config.image_name}...")
        self._docker.images.build(
            path=dockerfile_path,
            tag=self._config.image_name,
            rm=True,
        )
        logger.info("Image built successfully")

    def start(self) -> str:
        """Start the container, reusing an existing one if possible. Returns the container ID."""
        cfg = self._config

        # Try to reuse an existing container
        try:
            existing = self._docker.containers.get(cfg.container_name)
            existing.reload()
            if existing.status == "running":
                logger.info(f"Reusing running container {cfg.container_name}")
                self._container = existing
                return existing.id
            else:
                logger.info(f"Restarting stopped container {cfg.container_name}")
                existing.start()
                self._container = existing
                return existing.id
        except docker.errors.NotFound:
            pass

        # No existing container — create a new one with persistent volume
        environment = {
            "SCREEN_WIDTH": str(cfg.screen_width),
            "SCREEN_HEIGHT": str(cfg.screen_height),
        }

        ports = {
            "8888/tcp": cfg.api_port,
        }

        volumes = {
            cfg.volume_name: {"bind": "/home/ctfuser", "mode": "rw"},
        }

        self._container = self._docker.containers.run(
            image=cfg.image_name,
            name=cfg.container_name,
            detach=True,
            ports=ports,
            environment=environment,
            mem_limit=cfg.memory_limit,
            nano_cpus=cfg.cpu_count * 1_000_000_000,
            network_mode=cfg.network_mode,
            volumes=volumes,
            remove=False,
        )
        logger.info(f"Container started: {self._container.id[:12]}")
        return self._container.id

    def stop(self) -> None:
        """Stop the container (without removing it, so it can be restarted later)."""
        if self._container:
            self._container.reload()
            if self._container.status == "running":
                logger.info(f"Stopping container {self._container.id[:12]}")
                self._container.stop(timeout=10)
            self._container = None

    def destroy(self) -> None:
        """Stop and permanently remove the container."""
        if self._container:
            self._container.reload()
            if self._container.status == "running":
                logger.info(f"Stopping container {self._container.id[:12]}")
                self._container.stop(timeout=10)
            logger.info(f"Removing container {self._container.id[:12]}")
            self._container.remove()
            self._container = None

    def is_running(self) -> bool:
        if not self._container:
            return False
        self._container.reload()
        return self._container.status == "running"

    def get_api_url(self) -> str:
        return f"http://localhost:{self._config.api_port}"

    def get_logs(self, tail: int = 100) -> str:
        if self._container:
            return self._container.logs(tail=tail).decode("utf-8", errors="replace")
        return ""
