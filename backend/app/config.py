import logging

logger = logging.getLogger(__name__)
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

# Load backend/.env first, then repo-level .env. Both use override=False so
# explicit environment variables (e.g. TEST_DATABASE_URL set by pytest, or
# deployment DATABASE_URL) always win. Loading backend/.env first keeps it as
# the local override over the repo-level defaults for normal development runs.
# NEVER override existing environment variables.
load_dotenv(BASE_DIR / ".env", override=False)
load_dotenv(ROOT_DIR / ".env", override=False)

# Prevent Windows system proxy (e.g. Clash/V2Ray on 127.0.0.1:7890) from breaking
# HTTPS API calls.  httpx/requests honour NO_PROXY even when the proxy itself
# comes from the Windows registry.
_no_proxy = os.environ.get("NO_PROXY", "")
for host in ("api.deepseek.com", "localhost", "127.0.0.1"):
    if host not in _no_proxy:
        _no_proxy = f"{_no_proxy},{host}" if _no_proxy else host
os.environ["NO_PROXY"] = _no_proxy

# Ensure ffmpeg is available on PATH for audio.py conversion and FunASR internal loading.
# imageio_ffmpeg bundles a binary deep in site-packages, not on PATH by default.
# We add its directory to PATH and create a 'ffmpeg.exe' alias so subprocess.run(['ffmpeg', ...])
# works everywhere without hard-coding the bundled path.
_ffmpeg_alias_created = False
try:
    import imageio_ffmpeg
    _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    if _ffmpeg_exe and os.path.isfile(_ffmpeg_exe):
        _ffmpeg_dir = os.path.dirname(_ffmpeg_exe)
        # Add bundled binary dir to PATH
        _path = os.environ.get("PATH", "")
        if _ffmpeg_dir not in _path.split(os.pathsep):
            os.environ["PATH"] = f"{_ffmpeg_dir}{os.pathsep}{_path}"
        # Create ffmpeg.exe alias if bundled name is different (e.g. ffmpeg-win-x86_64-v7.1.exe)
        _ffmpeg_alias = os.path.join(_ffmpeg_dir, "ffmpeg.exe")
        if not os.path.exists(_ffmpeg_alias) and os.path.basename(_ffmpeg_exe) != "ffmpeg.exe":
            try:
                shutil.copy2(_ffmpeg_exe, _ffmpeg_alias)
                _ffmpeg_alias_created = True
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)  # binary may be in use; alias is best-effort
except Exception:
    logger.warning("suppressed_exception", exc_info=True)

# Database
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is required. Notero now expects PostgreSQL, for example "
        "postgresql://postgres:postgres@localhost:5432/notero"
    )

# File Storage
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
AUDIO_DIR = UPLOAD_DIR / "audio"
PPT_DIR = UPLOAD_DIR / "ppt"
IMAGE_DIR = OUTPUT_DIR / "images"

SLIDE_DIR = UPLOAD_DIR / "slides"  # PPT slide rendered images
FONTS_DIR = BASE_DIR / "assets" / "fonts"  # Bundled CJK fonts for slide rendering

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
PPT_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
SLIDE_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)

MAX_AUDIO_SIZE = 200 * 1024 * 1024  # 200MB
MAX_PPT_SIZE = 50 * 1024 * 1024  # 50MB

# AI API Keys
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
QWEN_VL_API_KEY = os.getenv("QWEN_VL_API_KEY", "")

# OCR (image text recognition). Enabled by default; silently no-ops when no
# vision key is configured, so the product degrades instead of failing.
OCR_ENABLED = os.getenv("OCR_ENABLED", "1").lower() in ("1", "true", "yes", "on")
OCR_MAX_WIDTH = int(os.getenv("OCR_MAX_WIDTH", "1280"))
OCR_JPEG_QUALITY = int(os.getenv("OCR_JPEG_QUALITY", "90"))
OCR_SKIP_IF_TEXT_LEN = int(os.getenv("OCR_SKIP_IF_TEXT_LEN", "60"))
OCR_MODEL = os.getenv("OCR_MODEL", "qwen-vl-plus")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

# Security
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    _env = os.getenv("NOTERO_ENV", "development").lower()
    if _env in ("production", "prod", "staging", "stg"):
        raise RuntimeError(
            "SECRET_KEY is required in production/staging. "
            "Set a strong random string (e.g. openssl rand -hex 32)."
        )
    import secrets as secrets_mod
    SECRET_KEY = secrets_mod.token_hex(32)
    logger.warning("SECRET_KEY not set; using a random dev key. Do not use this in production!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 60 minutes
REFRESH_TOKEN_EXPIRE_DAYS = 7  # 7 days

# CORS
# Comma-separated list of allowed origins (e.g. "http://localhost:5173,https://myapp.com")
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:5175").split(",") if o.strip()]

# Default Admin Account (for first-run initialization)
ADMIN_DEFAULT_EMAIL = os.getenv("ADMIN_DEFAULT_EMAIL", "admin")
ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD")  # Must be set in production

# FunASR Model Configuration
FUNASR_MODEL_DIR = os.getenv("FUNASR_MODEL_DIR", ROOT_DIR / "models")
FUNASR_MODEL_NAME = os.getenv("FUNASR_MODEL_NAME", "paraformer-zh")
FUNASR_VAD_MODEL = os.getenv("FUNASR_VAD_MODEL", "fsmn-vad")
FUNASR_PUNC_MODEL = os.getenv("FUNASR_PUNC_MODEL", "ct-punc")

# Agent stale-task / heartbeat thresholds
AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT_SECONDS") or 600)
AGENT_HEARTBEAT_SECONDS = int(os.getenv("AGENT_HEARTBEAT_SECONDS") or 60)

def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


# Web search augmentation
# WEB_SEARCH_ENABLED=1 plus a provider key enables optional online context for
# RAG and quiz-bank backfill. Keep keys on the Windows backend; the Mac frontend
# should only call the local /api proxy.
WEB_SEARCH_ENABLED = _bool_env("WEB_SEARCH_ENABLED", False)
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "tavily").strip().lower()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS") or 5)
WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS") or 8)


# PPT insertion matching strategy
# PPT_LLM_MATCHER=1  -> use DeepSeek to generate slide placement anchors (default)
# PPT_LLM_MATCHER=0  -> use the legacy SlideAligner keyword matching only
PPT_LLM_MATCHER = _bool_env("PPT_LLM_MATCHER", True)

# Agent execution mode
# AGENTS_USE_CELERY=1  -> dispatch agent tasks to Celery workers (production must set explicitly)
# AGENTS_USE_CELERY=0  -> run agents in daemon threads (local dev default)
# AGENTS_SYNC=1        -> run agents synchronously inline (tests only)
AGENTS_USE_CELERY = _bool_env("AGENTS_USE_CELERY", False)
AGENTS_SYNC = _bool_env("AGENTS_SYNC", False)
AGENTS_DISPATCH_MODE = "celery" if AGENTS_USE_CELERY else "thread"
