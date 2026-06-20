import sys
import tempfile
from pathlib import Path
import unittest.mock as mock
import types

sys.path.insert(0, str(Path(__file__).parent))

from models import CaptureOutput
import storage_engine as se


def _out(conf):
    return CaptureOutput(
        category="Tech_Notes", suggested_filename="topic-x",
        markdown_content="Some unique content " + str(conf),
        key_signals=["x"], confidence=conf, requires_new_category=False,
    )


def _cfg(threshold):
    return types.SimpleNamespace(capture=types.SimpleNamespace(
        confidence_threshold=threshold, filename_max_words=2,
        filename_max_chars=40, note_max_chars=0,
    ))


def test_high_threshold_routes_mid_confidence_to_scratchpad():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        with mock.patch("config.get_config", return_value=_cfg(0.8)):
            p = se.write_to_vault(_out(0.7), vault_root=vault, scratchpad_folder="_scratchpad")
        assert "_scratchpad" in str(p)   # 0.7 < 0.8 -> inbox


def test_low_threshold_files_same_capture():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        with mock.patch("config.get_config", return_value=_cfg(0.5)):
            p = se.write_to_vault(_out(0.7), vault_root=vault, scratchpad_folder="_scratchpad")
        assert "_scratchpad" not in str(p)  # 0.7 >= 0.5 -> filed
        assert "Tech_Notes" in str(p)
