"""
config.py  --  Centralised configuration loader.

Reads config.toml, merges with env-var overrides, exposes a typed Config.

Priority (highest to lowest):
  1. CLI arguments (applied in main.py before importing this module)
  2. Environment variables  (OMNI_VAULT_ROOT, OLLAMA_MODEL, etc.)
  3. config.toml values
  4. Hard-coded defaults
"""
from __future__ import annotations
import os, sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        raise ImportError("Python < 3.11 requires 'tomli': pip install tomli")

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.toml"
DEFAULT_VAULT_ROOT: Path = Path("~/second-thought-storage").expanduser()


_DEFAULT_VISION_PROMPT = (
    "Describe this image in detail. "
    "If it contains code, a UI screenshot, a diagram, or text, "
    "transcribe or describe that content precisely."
)


@dataclass
class OllamaConfig:
    base_url: str       = "http://localhost:11434"
    model: str          = "llama3.2"
    vision_model: str   = "llava"
    keep_alive: str     = "30m"   # how long Ollama keeps the model resident between calls
    vision_prompt: str  = _DEFAULT_VISION_PROMPT
    image_required: bool = False  # if True, hard-fail captures when the vision model is unavailable


@dataclass
class WhisperConfig:
    model: str  = "base"
    device: str = "auto"


@dataclass
class VaultConfig:
    root: Path = field(default_factory=lambda: DEFAULT_VAULT_ROOT)
    scratchpad_folder: str = "_scratchpad"


@dataclass
class CaptureConfig:
    web_max_chars: int     = 8000
    youtube_max_chars: int = 6000
    llm_max_retries: int   = 3
    llm_temperature: float = 0.1
    filename_max_words: int = 2
    filename_max_chars: int = 40
    youtube_filename_max_chars: int = 80
    note_max_chars: int     = 0  # 0 = unlimited
    # Routing/strictness knobs (user-tunable via the GUI settings panel).
    confidence_threshold: float = 0.6   # captures below this -> scratchpad inbox
    llm_scrutiny: str           = "balanced"  # "relaxed" | "balanced" | "strict"
    # OCR-first fast path for text-heavy image captures (skips the slow LLaVA call).
    ocr_fast_path_enabled: bool = True
    ocr_text_min_chars: int     = 10   # min OCR chars to treat an image as a text capture
    # When a folder is created through the app (inbox approve or Vault Manager
    # "+"), auto-generate an LLM routing description for it. Opt-in.
    auto_describe_new_folders: bool = False
    # Allow fetching private/loopback/intranet URLs (SSRF guard opt-out).
    # Default false; set to true only when capturing from a private wiki or
    # localhost service you control.
    allow_private_hosts: bool = False
    # Map-Reduce token budgeting for the async YouTube summarizer.
    # max_chunk_tokens = summary_model_context_tokens - summary_safety_buffer_tokens - summary_reserved_output_tokens
    summary_model_context_tokens: int   = 8192
    summary_safety_buffer_tokens: int   = 256
    summary_reserved_output_tokens: int = 768
    summary_chunk_overlap_tokens: int   = 80
    summary_max_chunks: int             = 40
    summary_max_concurrency: int        = 3
    reduce_max_depth: int               = 3


@dataclass
class LogConfig:
    path: Path | None = None


@dataclass
class NotificationConfig:
    enabled: bool      = True
    title_prefix: str  = "Second Thought"


@dataclass
class VectorConfig:
    enabled: bool        = True
    embed_model: str     = "all-minilm"
    top_k: int           = 3
    # Candidates below this cosine similarity are dropped from retrieve_related
    # entirely, instead of injecting the nearest noise as "related" context.
    min_similarity: float = 0.4


@dataclass
class YouTubeConfig:
    folder_name: str  = "YouTube"
    description: str  = "Summaries and notes captured from YouTube videos."
    job_ttl_seconds: int = 3600  # how long finished job entries stay in the registry


@dataclass
class OCRConfig:
    enabled: bool = False  # opt-in: runs rapidocr-onnxruntime alongside the vision model


@dataclass
class LookConfig:
    chat_min_similarity_high: float   = 0.45
    chat_min_similarity_medium: float = 0.35
    chat_min_similarity_floor: float  = 0.32
    chat_top_k: int                   = 8
    chat_temperature: float           = 0.2
    chat_general_temperature: float   = 0.7
    chat_system_prompt: str           = ""


@dataclass
class Config:
    vault: VaultConfig                = field(default_factory=VaultConfig)
    ollama: OllamaConfig              = field(default_factory=OllamaConfig)
    whisper: WhisperConfig            = field(default_factory=WhisperConfig)
    ocr: OCRConfig                    = field(default_factory=OCRConfig)
    capture: CaptureConfig            = field(default_factory=CaptureConfig)
    log: LogConfig                    = field(default_factory=LogConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    vector: VectorConfig              = field(default_factory=VectorConfig)
    youtube: YouTubeConfig            = field(default_factory=YouTubeConfig)
    look: LookConfig                  = field(default_factory=LookConfig)


def _resolve_path(raw: str) -> Path | None:
    if not raw:
        return None
    return Path(raw).expanduser()


def load_config(config_path: Path | None = None) -> Config:
    path = (
        config_path
        or _resolve_path(os.getenv("OMNI_CONFIG", ""))
        or _DEFAULT_CONFIG_PATH
    )
    raw: dict = {}
    if path and path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    else:
        print(f"[Config] config.toml not found at {path}, using defaults.", flush=True)

    cfg = Config()

    vault_raw = raw.get("vault", {})
    cfg.vault.root = Path(
        os.getenv("OMNI_VAULT_ROOT") or vault_raw.get("root", str(DEFAULT_VAULT_ROOT))
    ).expanduser()
    cfg.vault.scratchpad_folder = (
        os.getenv("OMNI_SCRATCHPAD_FOLDER")
        or vault_raw.get("scratchpad_folder", "_scratchpad")
    )

    ollama_raw = raw.get("ollama", {})
    cfg.ollama.base_url     = os.getenv("OLLAMA_BASE_URL") or ollama_raw.get("base_url", "http://localhost:11434")
    cfg.ollama.model        = os.getenv("OLLAMA_MODEL")    or ollama_raw.get("model", "llama3.2")
    cfg.ollama.vision_model = ollama_raw.get("vision_model", "llava")
    cfg.ollama.keep_alive   = ollama_raw.get("keep_alive", "30m")
    cfg.ollama.vision_prompt = ollama_raw.get("vision_prompt", _DEFAULT_VISION_PROMPT)
    cfg.ollama.image_required = bool(ollama_raw.get("image_required", False))

    whisper_raw = raw.get("whisper", {})
    cfg.whisper.model  = whisper_raw.get("model", "base")
    cfg.whisper.device = whisper_raw.get("device", "auto")

    cap_raw = raw.get("capture", {})
    cfg.capture.web_max_chars     = cap_raw.get("web_max_chars", 8000)
    cfg.capture.youtube_max_chars = cap_raw.get("youtube_max_chars", 6000)
    cfg.capture.llm_max_retries   = cap_raw.get("llm_max_retries", 3)
    cfg.capture.llm_temperature   = cap_raw.get("llm_temperature", 0.1)
    cfg.capture.filename_max_words = int(cap_raw.get("filename_max_words", 2))
    cfg.capture.filename_max_chars = int(cap_raw.get("filename_max_chars", 40))
    cfg.capture.youtube_filename_max_chars = int(cap_raw.get("youtube_filename_max_chars", 80))
    cfg.capture.note_max_chars     = int(cap_raw.get("note_max_chars", 0))
    cfg.capture.confidence_threshold = float(cap_raw.get("confidence_threshold", 0.6))
    _scrutiny = str(cap_raw.get("llm_scrutiny", "balanced")).strip().lower()
    cfg.capture.llm_scrutiny = _scrutiny if _scrutiny in ("relaxed", "balanced", "strict") else "balanced"
    cfg.capture.ocr_fast_path_enabled = bool(cap_raw.get("ocr_fast_path_enabled", True))
    cfg.capture.ocr_text_min_chars    = int(cap_raw.get("ocr_text_min_chars", 10))
    cfg.capture.auto_describe_new_folders = bool(cap_raw.get("auto_describe_new_folders", False))
    cfg.capture.allow_private_hosts       = bool(cap_raw.get("allow_private_hosts", False))

    cfg.capture.summary_model_context_tokens   = int(cap_raw.get("summary_model_context_tokens", 8192))
    cfg.capture.summary_safety_buffer_tokens   = int(cap_raw.get("summary_safety_buffer_tokens", 256))
    cfg.capture.summary_reserved_output_tokens = int(cap_raw.get("summary_reserved_output_tokens", 768))
    cfg.capture.summary_chunk_overlap_tokens   = int(cap_raw.get("summary_chunk_overlap_tokens", 80))
    cfg.capture.summary_max_chunks             = int(cap_raw.get("summary_max_chunks", 40))
    cfg.capture.summary_max_concurrency        = int(cap_raw.get("summary_max_concurrency", 3))
    cfg.capture.reduce_max_depth               = int(cap_raw.get("reduce_max_depth", 3))

    # max_chunk_tokens must come out positive and comfortably large, or every
    # chunk's verify step would reject everything. Clamp the buffer/reserved
    # down (proportionally) rather than crash on a user typo.
    headroom = (
        cfg.capture.summary_model_context_tokens
        - cfg.capture.summary_safety_buffer_tokens
        - cfg.capture.summary_reserved_output_tokens
    )
    if headroom < 512:
        print(
            f"[Config] summary_model_context_tokens - summary_safety_buffer_tokens - "
            f"summary_reserved_output_tokens = {headroom} (< 512); clamping "
            "summary_safety_buffer_tokens/summary_reserved_output_tokens down.",
            flush=True,
        )
        cfg.capture.summary_safety_buffer_tokens = 200
        cfg.capture.summary_reserved_output_tokens = max(
            256, cfg.capture.summary_model_context_tokens - 200 - 512
        )

    log_raw = raw.get("log", {})
    _default_log = str(cfg.vault.root / ".omni_capture" / "captures.jsonl")
    log_path_str = log_raw.get("path", _default_log)
    cfg.log.path = _resolve_path(log_path_str) if log_path_str else None

    notif_raw = raw.get("notifications", {})
    cfg.notifications.enabled      = notif_raw.get("enabled", True)
    cfg.notifications.title_prefix = notif_raw.get("title_prefix", "Second Thought")

    vec_raw = raw.get("vector", {})
    cfg.vector.enabled        = vec_raw.get("enabled", True)
    cfg.vector.embed_model    = vec_raw.get("embed_model", "all-minilm")
    cfg.vector.top_k          = int(vec_raw.get("top_k", 3))
    cfg.vector.min_similarity = float(vec_raw.get("min_similarity", 0.4))

    yt_raw = raw.get("youtube", {})
    cfg.youtube.folder_name = (
        os.getenv("OMNI_YOUTUBE_FOLDER") or yt_raw.get("folder_name", "YouTube")
    )
    cfg.youtube.description = yt_raw.get(
        "description", "Summaries and notes captured from YouTube videos."
    )
    cfg.youtube.job_ttl_seconds = int(yt_raw.get("job_ttl_seconds", 3600))

    ocr_raw = raw.get("ocr", {})
    cfg.ocr.enabled = bool(ocr_raw.get("enabled", False))

    look_raw = raw.get("look", {})
    cfg.look.chat_min_similarity_high   = float(look_raw.get("chat_min_similarity_high", 0.45))
    cfg.look.chat_min_similarity_medium = float(look_raw.get("chat_min_similarity_medium", 0.35))
    cfg.look.chat_min_similarity_floor  = float(look_raw.get("chat_min_similarity_floor", 0.32))
    cfg.look.chat_top_k                 = int(look_raw.get("chat_top_k", 8))
    cfg.look.chat_temperature           = float(look_raw.get("chat_temperature", 0.2))
    cfg.look.chat_general_temperature   = float(look_raw.get("chat_general_temperature", 0.7))
    cfg.look.chat_system_prompt         = str(look_raw.get("chat_system_prompt", "") or "")

    return cfg


_cfg: Config | None = None


def get_config() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


def reload_config(config_path: Path | None = None) -> Config:
    global _cfg
    _cfg = load_config(config_path)
    return _cfg
