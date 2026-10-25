"""FastAPI server and WebSocket hub for the JARVIS Visualizer."""

import asyncio
import os
import socket
from pathlib import Path
from typing import Any
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jarvis.utils.logging import logger
from jarvis.visualizer.adapter import VisualizerAdapter


class PermissionResolutionRequest(BaseModel):
    approved: bool


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is currently open and bound on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def create_visualizer_app(adapter: VisualizerAdapter) -> FastAPI:
    """Construct and configure the FastAPI application for the Visualizer."""
    app = FastAPI(title="JARVIS Visualizer HUD", docs_url=None, redoc_url=None)

    static_dir = Path(__file__).parent / "static"

    @app.get("/")
    async def get_index() -> FileResponse:
        index_path = static_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="HUD static assets not found")
        return FileResponse(index_path)

    @app.get("/api/snapshot")
    async def get_snapshot() -> dict[str, Any]:
        """Return the current complete visual snapshot."""
        return adapter.snapshot.to_dict()

    @app.get("/api/health")
    async def get_health() -> dict[str, Any]:
        """Health-check endpoint."""
        return {
            "status": "online",
            "agent_state": adapter.snapshot.agent_state,
            "clients": adapter.client_count,
        }

    @app.post("/api/permission/{request_id}")
    async def resolve_permission(
        request_id: str,
        payload: PermissionResolutionRequest,
    ) -> dict[str, Any]:
        """Resolve a pending permission request.

        Crucial security note: This endpoint does NOT execute tools. It merely returns
        the user's authorization decision to the waiting backend PermissionController.
        """
        success = adapter.resolve_permission(request_id, payload.approved)
        if not success:
            raise HTTPException(status_code=404, detail="Permission request not found or expired")
        return {
            "success": True,
            "request_id": request_id,
            "approved": payload.approved,
        }

    @app.websocket("/ws/telemetry")
    async def telemetry_websocket(websocket: WebSocket) -> None:
        """Bidirectional streaming telemetry channel."""
        await websocket.accept()
        await adapter.register_client(websocket)
        try:
            while True:
                # Keep connection alive and listen for optional client pings
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text('{"type":"pong"}')
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as ex:
            logger.debug("WebSocket client error: %s", ex)
        finally:
            await adapter.unregister_client(websocket)

    # Mount static assets (CSS, JS, icons)
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


class VisualizerServer:
    """Non-blocking background runner managing FastAPI / Uvicorn server lifecycle."""

    def __init__(
        self,
        adapter: VisualizerAdapter,
        host: str = "127.0.0.1",
        port: int = 8000,
        max_port_attempts: int = 5,
    ) -> None:
        self.adapter = adapter
        self.host = host
        self.port = port
        self.max_port_attempts = max_port_attempts
        self.actual_port = port
        self.app = create_visualizer_app(self.adapter)

        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def server_url(self) -> str:
        return f"http://{self.host}:{self.actual_port}"

    async def start(self) -> str:
        """Start Uvicorn in background task on available port."""
        if self._is_running:
            return self.server_url

        # Select available port with fallback
        target_port = self.port
        for i in range(self.max_port_attempts):
            candidate = self.port + i
            if not is_port_in_use(candidate, self.host):
                target_port = candidate
                break

        self.actual_port = target_port

        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.actual_port,
            log_level="warning",
            loop="asyncio",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

        # Launch server in non-blocking background task within current loop
        self._task = asyncio.create_task(self._server.serve())
        self._is_running = True

        # Wait briefly for server to bind
        for _ in range(25):
            if self._server.started:
                break
            await asyncio.sleep(0.04)

        logger.info("JARVIS Visualizer HUD running at %s", self.server_url)
        return self.server_url

    async def stop(self) -> None:
        """Shut down the Uvicorn server cleanly."""
        if not self._is_running:
            return

        self._is_running = False
        if self._server:
            self._server.should_exit = True

        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=1.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                try:
                    await self._task
                except Exception:
                    pass

        self._server = None
        self._task = None
        logger.info("JARVIS Visualizer HUD server stopped.")
