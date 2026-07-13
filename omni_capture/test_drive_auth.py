import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import drive_auth


def test_scope_is_full_drive():
    assert drive_auth.DRIVE_SCOPE == "https://www.googleapis.com/auth/drive"


def test_load_credentials_uses_cached_valid_token(tmp_path):
    """A valid cached token is used directly — no interactive flow, no refresh."""
    token_file = tmp_path / ".drive_token.json"
    token_file.write_text("{}")  # contents irrelevant; from_authorized_user_file is mocked

    fake_creds = MagicMock(valid=True)
    with patch(
        "drive_auth.Credentials.from_authorized_user_file", return_value=fake_creds
    ) as from_file, patch("drive_auth.InstalledAppFlow") as flow:
        creds = drive_auth.load_credentials(
            client_secret_path=str(tmp_path / "client_secret.json"),
            token_path=str(token_file),
        )

    assert creds is fake_creds
    from_file.assert_called_once()
    flow.from_client_secrets_file.assert_not_called()  # no browser


def test_load_credentials_runs_flow_when_no_token(tmp_path):
    """No cached token → run the installed-app flow and persist the result."""
    token_path = tmp_path / ".drive_token.json"
    fake_creds = MagicMock(valid=True)
    fake_creds.to_json.return_value = '{"token": "x"}'

    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds

    with patch("drive_auth.InstalledAppFlow") as flow_cls:
        flow_cls.from_client_secrets_file.return_value = fake_flow
        creds = drive_auth.load_credentials(
            client_secret_path=str(tmp_path / "client_secret.json"),
            token_path=str(token_path),
        )

    assert creds is fake_creds
    assert token_path.exists()
    assert json.loads(token_path.read_text()) == {"token": "x"}
