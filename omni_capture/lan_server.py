"""Separate LAN-IP listener (topology decision 2026-07-11). Exposes ONLY /lan/* -- the loopback
GUI/extension server (server.py) is untouched and stays on 127.0.0.1."""
import ipaddress
import socket
import threading
from typing import Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import lan_sync
from config import get_config


def build_lan_app() -> FastAPI:
    app = FastAPI(title="Second Thought LAN sync")
    app.include_router(lan_sync.router)   # ONLY /lan/* -- no GUI routes, no CORS-open surface

    @app.middleware("http")
    async def _cap_declared_body(request: Request, call_next):
        """LAN-25/LAN-06: an app-wide body ceiling, so a future /lan/* route cannot forget one.
        This is the cheap front door -- it rejects on the declared Content-Length without reading a
        byte. lan_sync's per-route streamed cap is the backstop for the absent or lying header."""
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > lan_sync.MAX_ENVELOPE_LEN:
            return JSONResponse({"detail": "payload too large"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """LAN-25: this app was a bare FastAPI() with no handler, so an unexpected error rendered
        the default 500 -- and with `log_level="warning"` on the uvicorn config below, that was the
        only trace it ever left. Log it here, and answer with an opaque body: the caller may be
        unauthenticated (the /lan/nonce mint is open by design) and must never receive a traceback
        or an internal path."""
        print(f"[LAN] unhandled error on {request.url.path}: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    return app


def lan_config() -> Tuple[bool, str, int]:
    lan = get_config().lan
    return bool(lan.enabled), str(lan.host), int(lan.port)


# ── LAN-05: bind ONE address, and keep it bound ──────────────────────────────
#
# ponytail (REVERSED 2026-07-21, user-approved): this listener used to bind 0.0.0.0. The original
# reasoning is still worth knowing and is still why LAN sync is safe at all -- a multi-homed desktop
# cannot know which NIC the phone shares, and the NaCl key plus the in-envelope secret double-gate
# every /lan/* call, so the bind address was never the security boundary. The reversal is defence in
# depth: an all-interfaces bind also publishes /lan/* on every VPN tunnel, tethered hotspot and
# bridged-VM adapter, and on those the double-gate is the ONLY thing between a hostile network and
# the vault feed. Binding one address costs the rebind path below and buys a much smaller surface.
# The new ceiling: a desktop whose phone is on a SECOND interface (not the default route) is not
# served. That is a deliberate accept -- LAN is an accelerator and Drive still syncs.

_REBIND_POLL_SECONDS = 30.0   # supervisor cadence; one UDP socket per check, no packets sent

_listener_lock = threading.Lock()
_listener: dict = {"server": None, "thread": None, "host": None, "port": None}
_supervisor: Optional[threading.Thread] = None
_stop = threading.Event()


def _validate_lan_host(host: str) -> Optional[str]:
    """Bind allowlist for `[lan] host`. This is the opposite polarity to
    gui/src-tauri/src/lib.rs:validate_bind_host, which keeps the LOOPBACK GUI API off the network
    entirely; here the accelerator must bind exactly one concrete address of this machine. A
    wildcard is rejected -- that is the finding. A hostname is rejected too, because this value is
    machine-written (lib.rs:parse_lan_ip picks the first RFC-1918 IPv4) and a name that resolves
    elsewhere later is a silent rebind we did not ask for. Returns None when unusable."""
    try:
        addr = ipaddress.ip_address(str(host).strip())
    except ValueError:
        return None
    if addr.is_unspecified or addr.is_multicast or addr.is_reserved:
        return None
    return str(addr)


def detect_lan_host() -> str:
    """This machine's current primary IPv4, or "" when offline.

    A UDP `connect()` to an unroutable documentation address (RFC 5737 TEST-NET-1) sends no packet;
    it only makes the OS pick the default route and report its source address -- which is the
    address a phone on the same WiFi would reach us on. Deliberately NOT
    `gethostbyname(gethostname())`, which returns 127.0.0.1 on many Windows configurations."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return str(s.getsockname()[0])
    except OSError:
        return ""
    finally:
        s.close()


def _spawn(host: str, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(build_lan_app(), host=host, port=port, log_level="warning"))
    t = threading.Thread(target=server.run, name="lan-listener", daemon=True)
    t.start()
    return server, t


def _shutdown(server, thread) -> None:
    """uvicorn's cooperative stop: `should_exit` makes `run()` return on its next tick."""
    try:
        server.should_exit = True
    except Exception:
        pass
    if thread is not None:
        thread.join(timeout=5.0)


def start_lan_listener(host: str, port: int, supervise: bool = True) -> Optional[threading.Thread]:
    """Start the LAN listener on `host` (LAN-05). Returns the serving thread, or None when `host`
    is not a bindable concrete address -- LAN is an accelerator, so a bad `[lan] host` disables it
    rather than failing app startup."""
    bind = _validate_lan_host(host)
    if bind is None:
        print(f"[LAN] refusing to bind {host!r}: not a concrete local address", flush=True)
        return None
    _stop.clear()
    with _listener_lock:
        server, t = _spawn(bind, port)
        _listener.update({"server": server, "thread": t, "host": bind, "port": port})
    if supervise:
        _start_supervisor()
    return t


def rebind_if_needed() -> Optional[str]:
    """The other half of LAN-05: a fixed bind rots. A DHCP lease change or a WiFi switch leaves the
    socket open on an address this machine no longer owns, so every phone push hits nothing and LAN
    sync degrades to Drive-only *permanently* -- with no error anywhere, because the listener is
    still "running". Re-bind when the primary address moved or the serving thread died.

    Returns the new host if it rebound, else None. Never raises: the caller is a background loop and
    LAN must never be able to take the app down."""
    with _listener_lock:
        server, thread = _listener["server"], _listener["thread"]
        bound, port = _listener["host"], _listener["port"]
    if server is None or bound is None:
        return None
    alive = thread is not None and thread.is_alive()
    if alive and ipaddress.ip_address(bound).is_loopback:
        return None                     # a deliberate loopback bind is not chasing the LAN
    current = detect_lan_host()
    if alive and (not current or current == bound):
        return None                     # still ours -- or we are offline, in which case keep it
    new_host = current or bound
    _shutdown(server, thread)
    with _listener_lock:
        server, t = _spawn(new_host, port)
        _listener.update({"server": server, "thread": t, "host": new_host, "port": port})
    print(f"[LAN] re-bound listener {bound} -> {new_host}:{port}", flush=True)
    _readvertise(new_host, port)
    return new_host


def _readvertise(host: str, port: int) -> None:
    """After a rebind, an mDNS record and a hub endpoint hint still pointing at the dead address are
    worse than none -- the phone would keep dialling it. Best-effort, never raises."""
    try:
        import lan_discovery
        vault_path = str(get_config().vault.root)
        device_id = lan_discovery.get_or_create_device_id(vault_path)
        lan_discovery.start_advertising(device_id, port)      # idempotent: replaces the old record
        lan_discovery.write_lan_endpoint(vault_path, device_id, host, port)
    except Exception as e:
        print(f"[LAN] re-advertise after rebind skipped: {e}", flush=True)


def _start_supervisor() -> None:
    global _supervisor
    if _supervisor is not None and _supervisor.is_alive():
        return

    def _loop() -> None:
        while not _stop.wait(_REBIND_POLL_SECONDS):
            try:
                rebind_if_needed()
            except Exception as e:
                print(f"[LAN] rebind check failed (non-fatal): {e}", flush=True)

    _supervisor = threading.Thread(target=_loop, name="lan-rebind", daemon=True)
    _supervisor.start()


def listener_status() -> dict:
    """LAN-25: `start_lan_listener`'s Thread was discarded at the call site, so a listener that died
    on a bind error was indistinguishable from one that never started. Cheap liveness for the
    supervisor and for any future health surface."""
    with _listener_lock:
        thread = _listener["thread"]
        return {
            "running": bool(thread is not None and thread.is_alive()),
            "host": _listener["host"],
            "port": _listener["port"],
        }


def stop_lan_listener() -> None:
    """Idempotent teardown (mirrors lan_discovery.stop_advertising)."""
    _stop.set()
    with _listener_lock:
        server, thread = _listener["server"], _listener["thread"]
        _listener.update({"server": None, "thread": None, "host": None, "port": None})
    if server is not None:
        _shutdown(server, thread)
