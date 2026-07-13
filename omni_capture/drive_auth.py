"""
drive_auth.py — Google Drive OAuth for the desktop sync agent.

Installed-app flow (google-auth-oauthlib): first call opens a browser once for
consent; the resulting token is cached and refreshed automatically thereafter.
Scope is full drive (user decision 2026-07-10; data-model §10 MVP).
"""
from __future__ import annotations

import os
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def load_credentials(
    client_secret_path: str = "client_secret.json",
    token_path: str = ".drive_token.json",
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
    client_secret_path: str = "client_secret.json",
    token_path: str = ".drive_token.json",
) -> Resource:
    """Return an authorized Drive v3 service."""
    creds = load_credentials(client_secret_path, token_path)
    return build("drive", "v3", credentials=creds, cache_discovery=False)
