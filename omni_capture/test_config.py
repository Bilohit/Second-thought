"""Unit tests for config.py's sync scheduling defaults (ISS-003, 2026-07-22).

Covers: SyncConfig's dataclass defaults (no config.toml at all) and load_config()'s
fallback defaults (a config.toml present but with no [sync] section) both express the
same ruling — interval-based auto-sync OFF until the user picks a real interval,
sync-on-launch ON regardless, master switch on so the launch pass and first-run Drive
wizard actually run out of the box.
"""
from config import Config, SyncConfig, load_config


def test_syncconfig_dataclass_defaults_match_the_iss003_ruling():
    s = SyncConfig()
    assert s.enabled is True, "master switch must default on so the launch pass can fire"
    assert s.interval_minutes == 0, "no interval chosen yet -> the never-auto-sync sentinel"
    assert s.sync_on_launch is True, "on-launch must default on regardless of interval choice"


def test_load_config_defaults_with_no_config_toml_at_all(tmp_path):
    missing = tmp_path / "does-not-exist.toml"
    cfg = load_config(missing)
    assert cfg.sync.enabled is True
    assert cfg.sync.interval_minutes == 0
    assert cfg.sync.sync_on_launch is True


def test_load_config_defaults_with_an_empty_sync_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[vault]\nroot = \".\"\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.sync.enabled is True
    assert cfg.sync.interval_minutes == 0
    assert cfg.sync.sync_on_launch is True


def test_load_config_still_honors_an_explicit_interval_choice(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[sync]\ninterval_minutes = 15\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.sync.interval_minutes == 15, "an explicit user choice must not be overridden"


def test_config_dataclass_top_level_sync_field_uses_syncconfig_defaults():
    cfg = Config()
    assert cfg.sync.enabled is True
    assert cfg.sync.interval_minutes == 0


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    test_syncconfig_dataclass_defaults_match_the_iss003_ruling()
    test_config_dataclass_top_level_sync_field_uses_syncconfig_defaults()
    with tempfile.TemporaryDirectory() as d:
        test_load_config_defaults_with_no_config_toml_at_all(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_load_config_defaults_with_an_empty_sync_section(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_load_config_still_honors_an_explicit_interval_choice(Path(d))
    print("ok")
