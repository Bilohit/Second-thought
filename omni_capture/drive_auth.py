"""
drive_auth.py — Google Drive OAuth for the desktop sync agent.

Installed-app flow (google-auth-oauthlib): first call opens a browser once for
consent; the resulting token is cached and refreshed automatically thereafter.
Scope is drive.file — least-privilege, app sees only files it creates (decision
2026-07-19; spike verdict PER-PROJECT so the two OAuth clients share per-file grants).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

# B-4 class: anchored to this module's directory, NEVER CWD-relative. The Tauri shell spawns the
# server with cwd = project root (lib.rs `current_dir(&project_root)`) while the CLI runs from
# omni_capture/ -- so a CWD-relative default made the GUI's scheduler miss the credentials that
# only exist next to this file, fall through to the interactive InstalledAppFlow inside a headless
# daemon thread, and fail every scheduled pass with ok:false. One anchor heals every caller.
_DEFAULT_CLIENT_SECRET_PATH = str(Path(__file__).parent / "client_secret.json")
_DEFAULT_TOKEN_PATH = str(Path(__file__).parent / ".drive_token.json")


def _write_token(token_path: str, creds: Credentials) -> None:
    """LAN-08: persist the refresh token 0600.

    The cached token is a long-lived Drive credential; a plain `open()` wrote it
    with the process umask (world-readable on a shared box). Both write sites go
    through here so they cannot drift. Best-effort: on Windows the POSIX mode is
    largely advisory, so the chmod is not allowed to fail the write."""
    data = creds.to_json()
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
    finally:
        try:
            os.chmod(token_path, 0o600)   # pre-existing file keeps its old mode otherwise
        except OSError:
            pass


def _load_cached(token_path: str) -> Optional[Credentials]:
    """LAN-23: read the cached token WITHOUT overriding its recorded scopes.

    `from_authorized_user_file(path, [DRIVE_SCOPE])` *asserts* the scope list
    rather than reading it, so a token minted under the superseded broad `drive`
    grant read back as if it were narrowly `drive.file` — the app then believed
    it held least privilege while actually wielding full-Drive access.

    Reading the real scopes and checking them explicitly also preserves OF-34's
    outcome by a deterministic path: a stale-scope token used to surface as an
    `invalid_scope` exception on refresh, which load_credentials caught and
    turned into fresh consent. Now the mismatch is detected here (returns None →
    same fresh-consent branch) instead of depending on which error Google
    happens to raise."""
    try:
        creds = Credentials.from_authorized_user_file(token_path)
    except Exception:  # noqa: BLE001 — an unreadable/corrupt cache is just "no cache"
        return None
    if DRIVE_SCOPE not in (creds.scopes or []):
        return None
    return creds


def load_credentials(
    client_secret_path: str = _DEFAULT_CLIENT_SECRET_PATH,
    token_path: str = _DEFAULT_TOKEN_PATH,
) -> Credentials:
    """Resolve credentials: cached token → refresh if stale → interactive flow."""
    creds: Optional[Credentials] = None
    if os.path.exists(token_path):
        creds = _load_cached(token_path)

    if creds and creds.valid:
        return creds

    refreshed = False
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            refreshed = True
        except Exception as exc:  # noqa: BLE001 — any refresh failure falls back to consent
            # OF-34: a refresh can fail permanently — a token minted under a superseded scope
            # (the drive→drive.file migration) is rejected with `invalid_scope`, or the refresh
            # token was revoked. This is the interactive Connect path (unlike has_cached_credentials,
            # which must stay browser-free), so drop to a fresh consent instead of propagating and
            # wedging Connect until the cached token file is manually deleted.
            # LAN-22: the exception text can carry the token/client id and the
            # raw Google error body straight into the unified log file. The type
            # name is all that is actionable here.
            print(f"[drive_auth] token refresh failed ({type(exc).__name__}); running interactive consent")
    if not refreshed:
        flow = InstalledAppFlow.from_client_secrets_file(
            client_secret_path, [DRIVE_SCOPE]
        )
        creds = flow.run_local_server(port=0)

    _write_token(token_path, creds)
    return creds


def get_drive_service(
    client_secret_path: str = _DEFAULT_CLIENT_SECRET_PATH,
    token_path: str = _DEFAULT_TOKEN_PATH,
) -> Resource:
    """Return an authorized Drive v3 service."""
    creds = load_credentials(client_secret_path, token_path)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def has_cached_credentials(token_path: str = _DEFAULT_TOKEN_PATH) -> bool:
    """True iff a usable (valid, or expired-but-refreshable) cached token exists --
    checked WITHOUT ever triggering the interactive consent flow (that opens a
    browser window and would hang a GUI request). Used to gate optional
    Drive-backed features (F-3 version history) off entirely when the user has
    never authorized, rather than surfacing an auth error mid-feature.

    A refreshable-but-expired token is refreshed here (cheap, non-interactive,
    same as get_drive_service would do) and the refreshed token re-cached."""
    if not os.path.exists(token_path):
        return False
    creds = _load_cached(token_path)
    if creds is None:
        return False
    if creds.valid:
        return True
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            return False
        _write_token(token_path, creds)
        return True
    return False


def client_secret_present(client_secret_path: str = _DEFAULT_CLIENT_SECRET_PATH) -> bool:
    """True iff an OAuth client file exists, checked without opening consent.

    Separates the two causes of "not connected" that the user must act on differently: no OAuth
    client configured at all (a setup problem no button can fix) vs configured-but-never-authorized
    (one click). Without this the GUI would offer a Connect button whose only possible outcome is
    FileNotFoundError."""
    return os.path.exists(client_secret_path)


def forget_credentials(token_path: str = _DEFAULT_TOKEN_PATH) -> bool:
    """Delete the cached token. True if one was removed, False if there was none.

    Local-only: this revokes nothing server-side at Google, it just makes this device forget --
    which is what a Disconnect button in a local-first app means."""
    if not os.path.exists(token_path):
        return False
    os.remove(token_path)
    return True


if __name__ == "__main__":
    import tempfile

    # T1: no token file at all -> False, no exception, no interactive flow triggered.
    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "nope.json")
        assert has_cached_credentials(missing) is False
    print("[T1] has_cached_credentials absent-file  PASS")

    # T2: a corrupt/garbage token file -> False, not an exception.
    with tempfile.TemporaryDirectory() as tmp:
        bad = os.path.join(tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("not json")
        assert has_cached_credentials(bad) is False
    print("[T2] has_cached_credentials corrupt-file  PASS")

    print("\nAll drive_auth.py smoke tests passed.")
