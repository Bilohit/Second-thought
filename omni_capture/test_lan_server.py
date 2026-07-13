from fastapi.testclient import TestClient
import lan_server


def _route_paths(routes) -> set:
    """Recursively collect concrete request paths from a FastAPI/Starlette route
    tree. Newer FastAPI versions wrap `include_router()` results in an opaque
    `_IncludedRouter` object (no `.path`, exposes the real routes via either
    `.routes` or `.original_router.routes`) -- walk both shapes so this stays
    correct across FastAPI versions instead of asserting one internal layout."""
    paths = set()
    for r in routes:
        path = getattr(r, "path", None)
        if path is not None:
            paths.add(path)
        sub_router = getattr(r, "routes", None) or getattr(
            getattr(r, "original_router", None), "routes", None
        )
        if sub_router:
            paths |= _route_paths(sub_router)
    return paths


def test_lan_app_exposes_only_lan_routes():
    app = lan_server.build_lan_app()
    paths = _route_paths(app.routes)
    # No GUI routes (/capture, /config, /look/chat, etc.) -- only the LAN endpoints.
    assert {"/lan/push", "/lan/changes"} <= paths
    assert paths & {"/capture", "/config", "/look/chat", "/share", "/inbox"} == set()


def test_lan_app_rejects_gui_routes_at_runtime():
    """Belt-and-suspenders: even if route enumeration ever misses something,
    the actual dispatch must 404 on GUI paths -- this is the security-critical
    assertion (LAN listener must never expose the loopback GUI surface)."""
    client = TestClient(lan_server.build_lan_app())
    for gui_path in ("/capture", "/config", "/look/chat", "/share", "/inbox"):
        assert client.get(gui_path).status_code == 404
        assert client.post(gui_path, json={}).status_code == 404
