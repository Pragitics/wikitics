from pathlib import Path
from socket import create_connection
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.db.session import get_db
from app.infrastructure.settings import Settings
from app.interfaces.api.dependencies import settings_dependency
from app.shared.metrics import metrics

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "wikitics-backend"}


@router.get("/health/details")
def detailed_health(db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)) -> dict:
    checks = {
        "database": _check_database(db),
        "redis": _check_tcp_url(settings.redis_url),
        "storage": _check_storage(settings.local_storage_root),
    }
    status = "ok" if all(check["ok"] for check in checks.values()) else "degraded"
    return {"status": status, "service": "wikitics-backend", "checks": checks}


@router.get("/metrics/json")
def metrics_json() -> dict:
    return metrics.snapshot()


def _check_database(db: Session) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _check_tcp_url(url: str) -> dict:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with create_connection((host, port), timeout=0.5):
            return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _check_storage(root: str) -> dict:
    try:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".health"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
