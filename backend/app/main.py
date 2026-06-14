import asyncio
import logging
import os
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import auth, notebooks, sessions, process, notes, public, vector, mindmap, quiz, agents, rag
from app.api.process.asr_ws import router as asr_ws_router
from app.core.database import get_db, SessionLocal
from app.core.auth import hash_password, get_current_user
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.request_log import RequestIdMiddleware
from app.middleware.csp import CSPMiddleware
from app.middleware.metrics import PrometheusMiddleware, metrics_response
from app.models import Base, Notebook, Session as DBSession, User
from app.core.database import engine
from app.config import SLIDE_DIR, AUDIO_DIR, ALLOWED_ORIGINS, ADMIN_DEFAULT_EMAIL, ADMIN_DEFAULT_PASSWORD

# ── Logging ──
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()

if _LOG_FORMAT == "json":
    # JSON structured logging for production / log aggregation systems
    try:
        from pythonjsonlogger import jsonlogger
        log_formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "%(request_id)s %(method)s %(path)s %(status_code)s %(latency_ms)s"
        )
    except ImportError:
        log_formatter = logging.Formatter(
            '%(asctime)s %(levelname)-5s [%(name)s] [req:%(request_id)s] %(message)s'
        )
else:
    log_formatter = logging.Formatter(
        '%(asctime)s %(levelname)-5s [%(name)s] [req:%(request_id)s] %(message)s',
        datefmt='%H:%M:%S',
    )

_root_handler = logging.StreamHandler()
_root_handler.setFormatter(log_formatter)
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    handlers=[_root_handler],
)

# Lower noisy third-party logs
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

app = FastAPI(title="AI Notebook", version="0.1.0")


# Ensure CORS headers are present even on 500/exception responses.
# CORSMiddleware normally only wraps successful paths; custom handlers
# fill the gap when upstream middlewares or route handlers raise.
from fastapi.responses import JSONResponse  # noqa: E402


@app.exception_handler(HTTPException)
async def _http_exception_handler(request, exc):
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


@app.exception_handler(Exception)
async def _general_exception_handler(request, exc):
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    logging.getLogger("notero.errors").exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )


app.add_middleware(RequestIdMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(CSPMiddleware)
app.add_middleware(PrometheusMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Origin", "Accept", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

app.include_router(auth.router)
app.include_router(notebooks.router)
app.include_router(sessions.router)
app.include_router(process.router)
app.include_router(notes.router)
app.include_router(public.router)
app.include_router(vector.router)
app.include_router(mindmap.router)
app.include_router(quiz.router)
app.include_router(agents.router)
app.include_router(rag.router)
app.include_router(asr_ws_router)


def _require_user_session(session_id: str, user: User, db: Session) -> DBSession:
    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Media not found")
    return session


def _safe_media_path(base_dir: Path, *parts: str) -> Path:
    base = base_dir.resolve()
    target = (base / Path(*parts)).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(status_code=404, detail="Media not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return target


@app.get("/api/media/slides/{session_id}/{slide_path:path}")
def get_slide_media(
    session_id: str,
    slide_path: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_user_session(session_id, current_user, db)
    return FileResponse(_safe_media_path(SLIDE_DIR, session_id, slide_path))


@app.get("/api/media/audio/{filename}")
def get_audio_media(
    filename: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not filename.endswith(".wav"):
        raise HTTPException(status_code=404, detail="Media not found")
    session_id = filename[:-4]
    _require_user_session(session_id, current_user, db)
    return FileResponse(_safe_media_path(AUDIO_DIR, filename))

@app.on_event("startup")
async def on_startup():
    # Run database migrations via Alembic in a background thread so that
    # long-running migrations do not block the event loop / health checks.
    alembic_ok = False
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command

        def _run_migrations():
            alembic_cfg = AlembicConfig(Path(__file__).resolve().parents[1] / "alembic.ini")
            alembic_command.upgrade(alembic_cfg, "head")

        await asyncio.to_thread(_run_migrations)
        logging.getLogger("notero.startup").info("Database migrations applied.")
        alembic_ok = True
    except Exception as e:
        logging.getLogger("notero.startup").warning("Alembic upgrade failed: %s", e)

    # Fallback to create_all ONLY in local dev / test environments.
    # Production must use Alembic; failing migration is a fatal error.
    if not alembic_ok:
        allow_fallback = os.getenv("ALLOW_CREATE_ALL_FALLBACK", "false").lower() in ("1", "true", "yes")
        if allow_fallback:
            try:
                await asyncio.to_thread(Base.metadata.create_all, bind=engine)
                logging.getLogger("notero.startup").info(
                    "Tables created via Base.metadata.create_all (dev/test fallback)."
                )
            except Exception as ce:
                logging.getLogger("notero.startup").error("create_all fallback also failed: %s", ce)
                raise RuntimeError("Database initialization failed. Check your DATABASE_URL and PostgreSQL setup.") from ce
        else:
            logging.getLogger("notero.startup").error(
                "Alembic migration failed and ALLOW_CREATE_ALL_FALLBACK is not enabled. "
                "Set ALLOW_CREATE_ALL_FALLBACK=1 only for local development."
            )
            raise RuntimeError("Alembic migration failed. Run 'alembic upgrade head' manually or check your setup.")

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == ADMIN_DEFAULT_EMAIL).first()
        if not admin:
            password = ADMIN_DEFAULT_PASSWORD
            if not password:
                logging.getLogger("notero.startup").warning("ADMIN_DEFAULT_PASSWORD not set; skipping default admin creation.")
            else:
                admin = User(
                    username=ADMIN_DEFAULT_EMAIL,
                    email=ADMIN_DEFAULT_EMAIL,
                    password_hash=hash_password(password),
                )
                db.add(admin)
                try:
                    db.commit()
                    logging.getLogger("notero.startup").info("Admin user created (%s).", ADMIN_DEFAULT_EMAIL)
                    logging.getLogger("notero.startup").info("Please change the password immediately after first login.")
                except IntegrityError:
                    db.rollback()
                    logging.getLogger("notero.startup").info("Admin user already exists (%s).", ADMIN_DEFAULT_EMAIL)
    finally:
        db.close()
    logging.getLogger("notero.startup").info("Database ready.")

    # Preload FunASR model in background
    if os.getenv("SKIP_ASR_PRELOAD") != "1":
        asyncio.create_task(_preload_asr_model())


async def _preload_asr_model():
    """Preload FunASR model in background on startup."""
    try:
        import asyncio
        from app.services.transcriber import transcriber
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, transcriber._load_model)
        logging.getLogger("notero.startup").info("FunASR model preloaded successfully")
    except Exception as e:
        logging.getLogger("notero.startup").warning("FunASR preload failed (will retry on first request): %s", e)

@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    data, content_type = metrics_response()
    return Response(content=data, media_type=content_type)


@app.get("/api/health")
def health_check():
    from sqlalchemy import text
    from app.core.database import engine

    checks = {}
    # Database
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis (reuse singleton to avoid creating short-lived connections)
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if r:
            r.ping()
            checks["redis"] = "connected"
        else:
            checks["redis"] = "error: Redis client unavailable"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Celery (lightweight check via broker connectivity)
    try:
        from app.core.celery_app import celery_app
        # inspect() returns None if no workers are running, which is acceptable
        inspector = celery_app.control.inspect(timeout=1)
        stats = inspector.stats()
        checks["celery"] = {
            "broker": "connected",
            "workers_online": len(stats) if stats else 0,
        }
    except Exception as e:
        checks["celery"] = f"broker_error: {e}"

    all_ok = all(v == "connected" or (isinstance(v, dict) and v.get("broker") == "connected") for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        **checks,
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8003, reload=True)
