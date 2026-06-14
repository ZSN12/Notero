import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

# Load repo-level .env first; keep backend/.env as a local override option.
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=True)

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
    print("[WARN] SECRET_KEY not set; using a random dev key. Do not use this in production!")
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
