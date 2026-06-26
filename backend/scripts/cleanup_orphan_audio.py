"""Scan and optionally remove audio files whose session no longer exists.

Usage:
    python -m scripts.cleanup_orphan_audio --report
    python -m scripts.cleanup_orphan_audio --delete

The script only touches files under ``backend/uploads/audio``.  By default it
reports orphans without deleting them; pass ``--delete`` to actually remove
files.
"""

import argparse
import logging
import re
import sys
from pathlib import Path

# Allow running the script directly from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import AUDIO_DIR
from app.core.database import SessionLocal
from app.models import Session

logger = logging.getLogger(__name__)

# Matches a UUID at the start of a filename, optionally followed by "_" or ".".
_SESSION_ID_RE = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})[._]"
)


def _extract_session_id(file_name: str) -> str | None:
    """Return the session UUID embedded in an audio filename, if any."""
    match = _SESSION_ID_RE.match(file_name)
    return match.group(1).lower() if match else None


def _find_orphan_audio_files(db) -> list[Path]:
    """Return audio files whose session id is not present in the database."""
    if not AUDIO_DIR.exists():
        return []

    # Collect all existing session ids once to avoid N+1 queries.
    existing_session_ids = {
        sid for (sid,) in db.query(Session.id).all()
    }

    orphans: list[Path] = []
    for f in AUDIO_DIR.iterdir():
        if not f.is_file():
            continue
        session_id = _extract_session_id(f.name)
        if session_id is None:
            # Unrecognised file; skip but log so operators can inspect.
            logger.warning("unrecognised_audio_file path=%s", f)
            continue
        if session_id not in existing_session_ids:
            orphans.append(f)

    return orphans


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find (and optionally delete) orphaned session audio files.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        default=True,
        help="List orphaned files without deleting them (default).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete orphaned files. Use with caution.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    db = SessionLocal()
    try:
        orphans = _find_orphan_audio_files(db)
    finally:
        db.close()

    if not orphans:
        print("No orphaned audio files found.")
        return 0

    total_bytes = sum(f.stat().st_size for f in orphans)

    if args.delete:
        deleted: list[Path] = []
        failed: list[tuple[Path, Exception]] = []
        for f in orphans:
            try:
                f.unlink()
                deleted.append(f)
                logger.info("deleted_orphan_audio path=%s", f)
            except Exception as exc:
                failed.append((f, exc))
                logger.warning(
                    "delete_orphan_audio_failed path=%s error=%s",
                    f, exc, exc_info=True,
                )
        print(f"Deleted {len(deleted)} orphaned audio files ({total_bytes} bytes).")
        if failed:
            print(f"Failed to delete {len(failed)} files:")
            for f, exc in failed:
                print(f"  {f}: {exc}")
            return 1
    else:
        print(f"Found {len(orphans)} orphaned audio files ({total_bytes} bytes):")
        for f in orphans:
            print(f"  {f}")
        print("Run with --delete to remove them.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
