"""LAN discovery (contract §11.8) — A: mDNS advertise, B: hub endpoint hint.

Both mechanisms only ever REFRESH a paired desktop's drifting `host:port`; neither carries a
secret or grants trust on its own (the QR-shared `key`/`secret` still gate every wire call).
LAN is an accelerator only — a failure here must never block or crash the caller.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SERVICE_TYPE = "_secondthought._tcp.local."
_DEVICE_ID_FILE = "device_id"

# Module-level handles for the running advertisement (idempotent start/stop).
_zeroconf = None
_service_info = None


def _device_id_path(vault_path: str) -> Path:
    return Path(vault_path) / ".omni_capture" / _DEVICE_ID_FILE


def get_or_create_device_id(vault_path: str) -> str:
    """Stable desktop device-id, persisted under `<vault>/.omni_capture/device_id` (contract
    §11.4's pairing-payload `device` anchor). Created once, reused across restarts/pairings."""
    path = _device_id_path(vault_path)
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except (FileNotFoundError, OSError):
        pass
    new_id = f"desktop-{uuid.uuid4().hex[:12]}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id, encoding="utf-8")
    except OSError as e:
        print(f"[lan_discovery] could not persist device_id: {e}")
    return new_id


# ── A: mDNS advertise ─────────────────────────────────────────────────────────

def start_advertising(device_id: str, port: int) -> None:
    """Advertise `_secondthought._tcp.local.` with TXT {v, device, port} (contract §11.8-A).

    Only meant to be called while `[lan] enabled`. Idempotent (re-calling replaces the prior
    advertisement). Safe no-op if `zeroconf` is unavailable or registration fails — LAN discovery
    is an accelerator only, never a dependency."""
    global _zeroconf, _service_info
    try:
        import socket

        from zeroconf import ServiceInfo, Zeroconf
    except Exception as e:
        print(f"[lan_discovery] zeroconf unavailable, mDNS advertise skipped: {e}")
        return

    try:
        stop_advertising()
        host = socket.gethostbyname(socket.gethostname())
        addr = socket.inet_aton(host)
        name = f"{device_id}.{_SERVICE_TYPE}"
        info = ServiceInfo(
            _SERVICE_TYPE,
            name,
            addresses=[addr],
            port=int(port),
            properties={"v": "1", "device": device_id, "port": str(port)},
        )
        zc = Zeroconf()
        zc.register_service(info)
        _zeroconf = zc
        _service_info = info
        print(f"[lan_discovery] advertising {name} on port {port}")
    except Exception as e:
        print(f"[lan_discovery] mDNS advertise failed (non-fatal): {e}")


def stop_advertising() -> None:
    """Idempotent teardown — safe to call even if nothing is currently advertising."""
    global _zeroconf, _service_info
    if _zeroconf is not None:
        try:
            if _service_info is not None:
                _zeroconf.unregister_service(_service_info)
            _zeroconf.close()
        except Exception as e:
            print(f"[lan_discovery] mDNS teardown error (non-fatal): {e}")
        finally:
            _zeroconf = None
            _service_info = None


# ── B: hub endpoint hint ──────────────────────────────────────────────────────

def write_lan_endpoint(vault_path: str, device_id: str, host: str, port: int) -> Optional[str]:
    """Write `.sync/lan_endpoint.json` (contract §11.8-B) advertising this desktop's current LAN
    `host:port` so the phone can refresh a paired desktop's drifting address on a Drive pull.
    Advisory + local-address only — never authoritative, holds no secret. No-op (returns None)
    if `host` is unset (LAN not yet configured)."""
    if not host:
        return None
    sync_dir = Path(vault_path) / ".sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    path = sync_dir / "lan_endpoint.json"
    payload = {
        "device": device_id,
        "host": host,
        "port": int(port),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)
    return str(path)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        # T1: device id is created once and persisted.
        d1 = get_or_create_device_id(tmp)
        d2 = get_or_create_device_id(tmp)
        assert d1 == d2 and d1.startswith("desktop-")
        print(f"[T1] get_or_create_device_id PASS -> {d1}")

        # T2: write_lan_endpoint shape.
        p = write_lan_endpoint(tmp, d1, "192.168.1.6", 7071)
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        assert data["device"] == d1 and data["host"] == "192.168.1.6" and data["port"] == 7071
        print("[T2] write_lan_endpoint PASS")

        # T3: no host -> no-op.
        assert write_lan_endpoint(tmp, d1, "", 7071) is None
        print("[T3] write_lan_endpoint no-host no-op PASS")

        # T4: start_advertising must never raise even without zeroconf/network.
        start_advertising(d1, 7071)
        stop_advertising()
        stop_advertising()  # idempotent
        print("[T4] start/stop_advertising non-fatal PASS")
