.PHONY: build run dev web test clean install container container-stop container-destroy container-clean

# Build the Docker image
build:
	docker build -t ctf-desktop-agent:latest docker/

# Run interactive CLI session
run:
	python -m ctf_agent interactive

# Run with Ollama
run-ollama:
	python -m ctf_agent interactive --provider ollama

# Run with existing container (no container management)
dev:
	python -m ctf_agent interactive --no-container

# Start the web UI (optional: make web PROVIDER=claude-code)
PROVIDER ?=
web:
ifdef PROVIDER
	CTF_LLM_PROVIDER=$(PROVIDER) uvicorn ctf_agent.interfaces.web.app:app --host 0.0.0.0 --port 8080 --reload
else
	uvicorn ctf_agent.interfaces.web.app:app --host 0.0.0.0 --port 8080 --reload
endif

# Run just the container (for development), with persistent volume
container:
	docker run -d --name ctf-agent-desktop \
		-p 8888:8888 \
		-e SCREEN_WIDTH=1024 -e SCREEN_HEIGHT=768 \
		-v ctf-agent-userdata:/home/ctfuser \
		ctf-desktop-agent:latest

# Stop the container (preserves state for restart)
container-stop:
	docker stop ctf-agent-desktop

# Stop and remove the container (keeps volume)
container-destroy:
	docker stop ctf-agent-desktop 2>/dev/null; docker rm ctf-agent-desktop 2>/dev/null; true

# Full cleanup: remove container and persistent volume
container-clean:
	docker stop ctf-agent-desktop 2>/dev/null; docker rm ctf-agent-desktop 2>/dev/null; docker volume rm ctf-agent-userdata 2>/dev/null; true

# Install Python dependencies
install:
	pip install -e ".[dev]"

# Run tests
test:
	pytest tests/ -v

# Lint
lint:
	ruff check src/ tests/

# Clean up
clean:
	rm -rf build/ dist/ *.egg-info __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
