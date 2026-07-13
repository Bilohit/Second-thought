"""Separate LAN-IP listener (topology decision 2026-07-11). Exposes ONLY /lan/* -- the loopback
GUI/extension server (server.py) is untouched and stays on 127.0.0.1."""
import threading
from typing import Tuple

from fastapi import FastAPI

import lan_sync
from config import get_config


def build_lan_app() -> FastAPI:
    app = FastAPI(title="Second Thought LAN sync")
    app.include_router(lan_sync.router)   # ONLY /lan/* -- no GUI routes, no CORS-open surface
    return app


def lan_config() -> Tuple[bool, str, int]:
    lan = get_config().lan
    return bool(lan.enabled), str(lan.host), int(lan.port)


def start_lan_listener(host: str, port: int) -> threading.Thread:
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(build_lan_app(), host=host, port=port, log_level="warning"))
    t = threading.Thread(target=server.run, name="lan-listener", daemon=True)
    t.start()
    return t
