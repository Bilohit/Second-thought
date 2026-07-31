"""
test_notifier.py
-----------------
ISS-045: a notification title over 64 chars must never reach the plyer/NOTIFYICONDATAW
call un-truncated, and send_notification must never raise regardless of title length.
"""

from __future__ import annotations

import notifier


def test_truncate_title_clamps_to_64():
    long_title = "x" * 200
    assert len(notifier._truncate_title(long_title)) == 64


def test_truncate_title_leaves_short_titles_alone():
    short_title = "Second Thought"
    assert notifier._truncate_title(short_title) == short_title


def test_send_notification_does_not_raise_on_long_title(monkeypatch):
    seen = {}

    def fake_plyer_notify(full_title: str, message: str) -> None:
        seen["full_title"] = full_title

    # Force the Windows backend regardless of the host OS running the test.
    monkeypatch.setattr(notifier, "_OS", "Windows")
    monkeypatch.setattr(notifier, "_plyer_notify", fake_plyer_notify)

    long_title = "A" * 200
    notifier.send_notification(title=long_title, message="body", subtitle="")

    assert len(seen["full_title"]) <= 64


def test_send_notification_truncates_title_plus_subtitle(monkeypatch):
    calls = []

    monkeypatch.setattr(notifier, "_OS", "Windows")
    monkeypatch.setattr(notifier, "_plyer_notify", lambda ft, m: calls.append(ft))

    notifier.send_notification(title="T" * 60, message="body", subtitle="S" * 60)

    assert len(calls[0]) <= 64
