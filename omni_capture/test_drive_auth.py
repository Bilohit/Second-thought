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


def test_load_credentials_refreshes_expired_token_without_a_browser(tmp_path):
    """An expired-but-refreshable cached token must refresh silently and
    re-cache. Falling through to the interactive flow here would pop a consent
    browser on a routine background sync pass."""
    token_file = tmp_path / ".drive_token.json"
    token_file.write_text("{}")
    fake_creds = MagicMock(valid=False, expired=True, refresh_token="r")
    fake_creds.to_json.return_value = '{"token": "refreshed"}'

    with patch(
        "drive_auth.Credentials.from_authorized_user_file", return_value=fake_creds
    ), patch("drive_auth.Request"), patch("drive_auth.InstalledAppFlow") as flow:
        creds = drive_auth.load_credentials(
            client_secret_path=str(tmp_path / "client_secret.json"),
            token_path=str(token_file),
        )

    assert creds is fake_creds
    fake_creds.refresh.assert_called_once()
    flow.from_client_secrets_file.assert_not_called()  # no browser
    assert json.loads(token_file.read_text()) == {"token": "refreshed"}


# -- has_cached_credentials -------------------------------------------------
#
# §3.4 cold spot: drive_auth.py:64-80 was entirely uncovered. This function
# exists solely so optional Drive-backed features (F-3 version history) can be
# gated OFF without triggering consent, so the contract under every branch is
# the same: answer the question, never open a browser, never raise.


def _token(tmp_path, name=".drive_token.json"):
    f = tmp_path / name
    f.write_text("{}")  # contents irrelevant; from_authorized_user_file is mocked
    return f


def test_has_cached_credentials_false_when_no_token_file(tmp_path):
    """Never-authorized user: answer False rather than prompting for consent."""
    with patch("drive_auth.InstalledAppFlow") as flow:
        assert drive_auth.has_cached_credentials(str(tmp_path / "absent.json")) is False
    flow.from_client_secrets_file.assert_not_called()


def test_has_cached_credentials_false_on_corrupt_token(tmp_path):
    """A garbage/truncated token file must degrade to False, not raise into
    the GUI request that asked whether the feature is available."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with patch("drive_auth.InstalledAppFlow") as flow:
        assert drive_auth.has_cached_credentials(str(bad)) is False
    flow.from_client_secrets_file.assert_not_called()


def test_has_cached_credentials_true_for_valid_token(tmp_path):
    token_file = _token(tmp_path)
    fake_creds = MagicMock(valid=True)
    with patch(
        "drive_auth.Credentials.from_authorized_user_file", return_value=fake_creds
    ), patch("drive_auth.InstalledAppFlow") as flow:
        assert drive_auth.has_cached_credentials(str(token_file)) is True
    flow.from_client_secrets_file.assert_not_called()
    fake_creds.refresh.assert_not_called()  # valid token must not be refreshed


def test_has_cached_credentials_refreshes_expired_token_and_recaches(tmp_path):
    """Expired-but-refreshable is still "usable": refresh non-interactively and
    persist the new token so the next call is a cheap valid-token hit."""
    token_file = _token(tmp_path)
    fake_creds = MagicMock(valid=False, expired=True, refresh_token="r")
    fake_creds.to_json.return_value = '{"token": "refreshed"}'

    with patch(
        "drive_auth.Credentials.from_authorized_user_file", return_value=fake_creds
    ), patch("drive_auth.Request"), patch("drive_auth.InstalledAppFlow") as flow:
        assert drive_auth.has_cached_credentials(str(token_file)) is True

    fake_creds.refresh.assert_called_once()
    flow.from_client_secrets_file.assert_not_called()
    assert json.loads(token_file.read_text()) == {"token": "refreshed"}


def test_has_cached_credentials_false_when_refresh_fails(tmp_path):
    """Revoked grant / offline: the refresh raises. Answer False and leave the
    cached token file untouched — do not fall through to interactive consent."""
    token_file = _token(tmp_path)
    fake_creds = MagicMock(valid=False, expired=True, refresh_token="r")
    fake_creds.refresh.side_effect = Exception("invalid_grant")

    with patch(
        "drive_auth.Credentials.from_authorized_user_file", return_value=fake_creds
    ), patch("drive_auth.Request"), patch("drive_auth.InstalledAppFlow") as flow:
        assert drive_auth.has_cached_credentials(str(token_file)) is False

    flow.from_client_secrets_file.assert_not_called()
    assert token_file.read_text() == "{}", "failed refresh must not rewrite the token cache"


def test_has_cached_credentials_false_when_expired_without_refresh_token(tmp_path):
    """Expired with no refresh token is unusable — only consent could fix it,
    and consent is exactly what this function must never trigger."""
    token_file = _token(tmp_path)
    fake_creds = MagicMock(valid=False, expired=True, refresh_token=None)

    with patch(
        "drive_auth.Credentials.from_authorized_user_file", return_value=fake_creds
    ), patch("drive_auth.InstalledAppFlow") as flow:
        assert drive_auth.has_cached_credentials(str(token_file)) is False

    fake_creds.refresh.assert_not_called()
    flow.from_client_secrets_file.assert_not_called()


# -- default path anchoring (B-4 class) -------------------------------------
#
# The Tauri shell spawns the server with cwd = project root, while the CLI runs
# from omni_capture/. CWD-relative defaults therefore resolved to a directory
# where no credentials exist, so the GUI scheduler fell through to the
# interactive InstalledAppFlow inside a headless daemon thread and failed every
# pass with ok:false -- while the same call from the CLI worked. Same class as
# B-4 (the vault-anchored sync-state sidecar); the auth path had never been
# anchored. These pin the anchor, not the literal path.


def test_default_paths_are_module_anchored_not_cwd_relative():
    """Defaults must resolve next to drive_auth.py regardless of the caller's cwd."""
    here = Path(drive_auth.__file__).parent
    assert Path(drive_auth._DEFAULT_CLIENT_SECRET_PATH) == here / "client_secret.json"
    assert Path(drive_auth._DEFAULT_TOKEN_PATH) == here / ".drive_token.json"
    for p in (drive_auth._DEFAULT_CLIENT_SECRET_PATH, drive_auth._DEFAULT_TOKEN_PATH):
        assert Path(p).is_absolute(), f"{p} is cwd-dependent"


def test_has_cached_credentials_default_token_is_not_cwd_relative(tmp_path, monkeypatch):
    """The GUI's connected/not-connected answer must not change with cwd.

    Red before the fix: the default was the bare string ".drive_token.json", so
    chdir'ing anywhere without a token made this report not-connected.
    """
    monkeypatch.chdir(tmp_path)  # a cwd with no credentials, like the server's
    seen = {}

    def _spy(path, scopes):
        seen["path"] = path
        raise ValueError("stop here; only the resolved path matters")

    with patch("drive_auth.Credentials.from_authorized_user_file", side_effect=_spy), \
         patch("drive_auth.os.path.exists", return_value=True), \
         patch("drive_auth.InstalledAppFlow") as flow:
        drive_auth.has_cached_credentials()

    assert Path(seen["path"]).parent == Path(drive_auth.__file__).parent
    flow.from_client_secrets_file.assert_not_called()


# -- client_secret_present / forget_credentials -----------------------------


def test_client_secret_present_answers_without_consent(tmp_path):
    secret = tmp_path / "client_secret.json"
    with patch("drive_auth.InstalledAppFlow") as flow:
        assert drive_auth.client_secret_present(str(secret)) is False
        secret.write_text("{}")
        assert drive_auth.client_secret_present(str(secret)) is True
    flow.from_client_secrets_file.assert_not_called()


def test_forget_credentials_removes_token_and_is_idempotent(tmp_path):
    """Disconnect twice (or on a never-connected device) must not raise."""
    token = tmp_path / ".drive_token.json"
    token.write_text("{}")
    assert drive_auth.forget_credentials(str(token)) is True
    assert not token.exists()
    assert drive_auth.forget_credentials(str(token)) is False  # already gone
