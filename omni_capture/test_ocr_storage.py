import tempfile
from pathlib import Path
from models import CaptureOutput
from storage_engine import write_to_vault


def test_ocr_fastpath_note_has_extracted_text_and_source_type():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        out = CaptureOutput(
            category="Tech_Notes", suggested_filename="api-handler",
            markdown_content="Notes on a request handler from a screenshot.",
            key_signals=["python", "handler"], confidence=0.9,
            requires_new_category=False,
        )
        p = write_to_vault(
            out, vault_root=vault, scratchpad_folder="_scratchpad",
            source_metadata={
                "source_type": "image_ocr",
                "transcribed_text": "def handler(req): return 200",
                "image_embed": "![[img-x.png]]",
            },
        )
        text = p.read_text(encoding="utf-8")
        assert "source_type: image_ocr" in text          # frontmatter
        assert "## Extracted Text" in text                # OCR label
        assert "## Transcribed Text" not in text
        assert "def handler(req): return 200" in text
        assert "![[img-x.png]]" in text                   # image preserved


def test_vision_ocr_note_still_uses_transcribed_text():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        out = CaptureOutput(
            category="Tech_Notes", suggested_filename="cat-photo",
            markdown_content="A description.", key_signals=["cat"], confidence=0.9,
        )
        p = write_to_vault(
            out, vault_root=vault, scratchpad_folder="_scratchpad",
            source_metadata={"transcribed_text": "incidental ocr", "vision_model": "llava"},
        )
        text = p.read_text(encoding="utf-8")
        assert "## Transcribed Text" in text   # unchanged vision+OCR label
        assert "source_type:" not in text       # no source_type for vision path
