from fastapi import FastAPI
from routes import health, screenshot, input, shell, filesystem

app = FastAPI(title="CTF Container API", version="1.0.0")

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(screenshot.router, prefix="/screenshot", tags=["screenshot"])
app.include_router(input.router, prefix="/input", tags=["input"])
app.include_router(shell.router, prefix="/shell", tags=["shell"])
app.include_router(filesystem.router, prefix="/files", tags=["files"])
