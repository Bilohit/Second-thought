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
    request_timeout_s: float = 60  # client-side timeout (seconds) on the structured chat-completion call


@dataclass
class WhisperConfig:
    model: str  = "base"
    device: str = "auto"
    summarize_threshold_tokens: int = 6000


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
    # Text captures whose token count exceeds this get chunked Map-Reduce
    # tagging + a faithful whole-document decide-context instead of a silent
    # single-pass truncation by the model's own context window.
    large_text_token_threshold: int     = 3000


@dataclass
class LogConfig:
    path: Path | None = None


@dataclass
class NotificationConfig:
    enabled: bool      = True
    title_prefix: str  = "Second Thought"


@dataclass
class RemindersConfig:
    delivery: str = "app"
    check_interval_seconds: int = 30


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
class LanConfig:
    """Same-WiFi LAN sync accelerator (contract §11). Never a dependency -- Drive
    remains the sole canonical/version authority; see lan_sync.py / lan_server.py."""
    enabled: bool = False
    host: str     = ""
    port: int     = 7071
    key: str      = ""
    # LAN-17: the LAN-plane credential, distinct from the GUI X-Omni-Secret (contract §11.4). Read
    # per request via get_config().lan.secret, exactly as `key` is; minted into `[lan] secret` by
    # lib.rs alongside `[lan] key`. An empty value is ALWAYS rejected at the listener (never key-only).
    secret: str   = ""


@dataclass
class SyncConfig:
    """Drive batched-sync scheduler (phase-5 §1.1). Interval config is a per-device LOCAL
    preference — deliberately NOT synced.

    ISS-003 ruling (2026-07-22): interval-based auto-sync stays OFF until the user picks a
    real interval (interval_minutes defaults to the 0/never sentinel), but sync-on-launch
    runs one pass at startup ON by default regardless of whether an interval has been
    chosen — see sync_scheduler.py's `_loop()`, which no longer gates sync_on_launch on
    `auto_sync_disabled()`. `enabled` is the system-wide master switch (GUI "Syncing
    system" toggle / manual Sync now); it defaults on so that default on-launch pass and
    the first-run Drive-connect wizard actually run out of the box."""
    enabled: bool            = True
    interval_minutes: int    = 0      # 0 = never auto-sync (sentinel) until the user chooses an interval; min 5 (clamped on read) once they do
    sync_on_launch: bool     = True
    sync_after_capture: bool = False  # a capture burst shouldn't thrash Drive; interval covers it
    mirror_captures: bool    = False  # K-2: opt-in — mirror origin:capture files to the hub


@dataclass
class Config:
    vault: VaultConfig                = field(default_factory=VaultConfig)
    ollama: OllamaConfig              = field(default_factory=OllamaConfig)
    whisper: WhisperConfig            = field(default_factory=WhisperConfig)
    ocr: OCRConfig                    = field(default_factory=OCRConfig)
    capture: CaptureConfig            = field(default_factory=CaptureConfig)
    log: LogConfig                    = field(default_factory=LogConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    reminders: RemindersConfig        = field(default_factory=RemindersConfig)
    vector: VectorConfig              = field(default_factory=VectorConfig)
    youtube: YouTubeConfig            = field(default_factory=YouTubeConfig)
    look: LookConfig                  = field(default_factory=LookConfig)
    lan: LanConfig                    = field(default_factory=LanConfig)
    sync: SyncConfig                  = field(default_factory=SyncConfig)

    def vault_sync_dir(self) -> str:
        """<vault>/.sync -- durable staging root for LAN provisional overlay (contract §11)."""
        return str(self.vault.root / ".sync")


def _resolve_path(raw: str) -> Path | None:
    if not raw:
        return None
    return Path(raw).expanduser()


def _parse_bool(v, default: bool = False) -> bool:
    """Coerce a TOML value that may be a real bool, an int, or a quoted string ("true"/"false")
    into a bool. `bool("false")` is True (non-empty string), so a bare `bool()` on a string config
    value is a bug (B-3). Truthy strings: true/1/yes/on (case-insensitive)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return default


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
    cfg.ollama.request_timeout_s = float(ollama_raw.get("request_timeout_s", 60))

    whisper_raw = raw.get("whisper", {})
    cfg.whisper.model  = whisper_raw.get("model", "base")
    cfg.whisper.device = whisper_raw.get("device", "auto")
    cfg.whisper.summarize_threshold_tokens = whisper_raw.get("summarize_threshold_tokens", 6000)

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
    cfg.capture.large_text_token_threshold     = int(cap_raw.get("large_text_token_threshold", 3000))

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

    reminders_raw = raw.get("reminders", {})
    cfg.reminders.delivery = str(reminders_raw.get("delivery", "app"))
    cfg.reminders.check_interval_seconds = int(reminders_raw.get("check_interval_seconds", 30))

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

    lan_raw = raw.get("lan", {})
    # B-3: `[lan] enabled` may be a STRING ("true"/"false" — the GUI's hand-rolled TOML writer quotes
    # it) or a real bool. `bool("false")` is True (non-empty string), so a user/GUI writing "false"
    # still armed the 0.0.0.0 LAN listener. Parse explicitly. (The Rust writer/reader round-trip the
    # quoted string on their own side; ponytail: emit a bare bool there too if that side is revisited.)
    cfg.lan.enabled = _parse_bool(lan_raw.get("enabled", False))
    cfg.lan.host    = str(lan_raw.get("host", ""))
    cfg.lan.port    = int(lan_raw.get("port", 7071))
    cfg.lan.key     = str(lan_raw.get("key", ""))
    cfg.lan.secret  = str(lan_raw.get("secret", ""))

    sync_raw = raw.get("sync", {})
    # Same string-vs-bool hazard as [lan] (GUI's hand-rolled TOML writer may quote bools) — parse
    # explicitly so a quoted "false" never arms the scheduler. Interval clamped to >=5 min, EXCEPT
    # 0 — the "never auto-sync" sentinel (sync_scheduler.AUTO_SYNC_NEVER). Clamping here would
    # silently turn "never" into "every 5 minutes", so the sentinel passes through unclamped.
    _interval = int(sync_raw.get("interval_minutes", 0))
    cfg.sync.enabled            = _parse_bool(sync_raw.get("enabled", True))
    cfg.sync.interval_minutes   = 0 if _interval <= 0 else max(5, _interval)
    cfg.sync.sync_on_launch     = _parse_bool(sync_raw.get("sync_on_launch", True))
    cfg.sync.sync_after_capture = _parse_bool(sync_raw.get("sync_after_capture", False))
    cfg.sync.mirror_captures    = _parse_bool(sync_raw.get("mirror_captures", False))

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
