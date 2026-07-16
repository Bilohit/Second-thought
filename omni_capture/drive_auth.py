"""
drive_auth.py — Google Drive OAuth for the desktop sync agent.

Installed-app flow (google-auth-oauthlib): first call opens a browser once for
consent; the resulting token is cached and refreshed automatically thereafter.
Scope is full drive (user decision 2026-07-10; data-model §10 MVP).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"

# B-4 class: anchored to this module's directory, NEVER CWD-relative. The Tauri shell spawns the
# server with cwd = project root (lib.rs `current_dir(&project_root)`) while the CLI runs from
# omni_capture/ -- so a CWD-relative default made the GUI's scheduler miss the credentials that
# only exist next to this file, fall through to the interactive InstalledAppFlow inside a headless
# daemon thread, and fail every scheduled pass with ok:false. One anchor heals every caller.
_DEFAULT_CLIENT_SECRET_PATH = str(Path(__file__).parent / "client_secret.json")
_DEFAULT_TOKEN_PATH = str(Path(__file__).parent / ".drive_token.json")


def load_credentials(
    client_secret_path: str = _DEFAULT_CLIENT_SECRET_PATH,
    token_path: str = _DEFAULT_TOKEN_PATH,
) -> Credentials:
    """Resolve credentials: cached token → refresh if stale → interactive flow."""
    creds: Optional[Credentials] = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, [DRIVE_SCOPE])

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            client_secret_path, [DRIVE_SCOPE]
        )
        creds = flow.run_local_server(port=0)

    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
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
    try:
        creds = Credentials.from_authorized_user_file(token_path, [DRIVE_SCOPE])
    except Exception:
        return False
    if creds.valid:
        return True
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            return False
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
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
