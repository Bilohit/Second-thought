"""Job-registry persistence across a simulated server restart.

ROADMAP "Persist the background-job registry": _set_job must write through to
captures.db so that after a restart (in-memory _jobs cleared) load_jobs()
repopulates the cache and GET /jobs/{id} still resolves instead of 404ing.
"""
import tempfile
from pathlib import Path

import config
import jobs


def _use_temp_vault(monkeypatch, tmp: Path) -> None:
    monkeypatch.setenv("OMNI_VAULT_ROOT", str(tmp))
    config.reload_config()


def test_set_job_survives_restart(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        _use_temp_vault(monkeypatch, Path(td))
        jobs._jobs.clear()

        jobs._set_job("j1", status="running", kind="youtube",
                      category="Videos", path=Path(td) / "note.md", error=None)

        # Simulate a restart: wipe the in-memory cache, reload from DB.
        jobs._jobs.clear()
        assert "j1" not in jobs._jobs
        loaded = jobs.load_jobs()
        assert loaded == 1

        got = jobs._get_job("j1")
        assert got is not None
        assert got["status"] == "running"
        assert got["kind"] == "youtube"
        assert got["category"] == "Videos"
        assert got["path"].endswith("note.md")

        config.reload_config()  # restore default singleton for other tests


def test_get_job_db_fallback_before_load(monkeypatch):
    """A poll landing after restart but before load_jobs() still resolves via
    the DB fallback in _get_job."""
    with tempfile.TemporaryDirectory() as td:
        _use_temp_vault(monkeypatch, Path(td))
        jobs._jobs.clear()

        jobs._set_job("j2", status="done", kind="voice", category=None,
                      path=None, error=None)
        jobs._jobs.clear()  # restart, no load_jobs() yet

        got = jobs._get_job("j2")  # cache miss -> DB fallback
        assert got is not None
        assert got["status"] == "done"

        config.reload_config()


def test_stale_eviction_removes_from_db(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        _use_temp_vault(monkeypatch, Path(td))
        jobs._jobs.clear()

        jobs._set_job("old", status="done", kind="voice",
                      category=None, path=None, error=None)
        # Next write with ttl=0 evicts "old" from both cache and DB.
        jobs._set_job("new", ttl_seconds=0, status="running", kind="youtube",
                      category=None, path=None, error=None)

        jobs._jobs.clear()
        jobs.load_jobs()
        assert jobs._get_job("old") is None

        config.reload_config()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
