from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.db.session import get_db
from app.infrastructure.settings import Settings
from app.interfaces.api.dependencies import settings_dependency, storage_dependency
from app.ports.storage import DocumentStoragePort
from app.shared.metrics import metrics

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "wikitics-backend"}


@router.get("/health/details")
def detailed_health(
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
    storage: DocumentStoragePort = Depends(storage_dependency),
) -> dict:
    checks = {
        "database": _check_database(db),
        "storage": _check_storage(storage, settings.storage_backend),
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


def _check_storage(storage: DocumentStoragePort, backend: str) -> dict:
    probe_path = f".health/{uuid4().hex}.txt"
    try:
        storage.save_text(probe_path, "ok")
        ok = storage.read_text(probe_path) == "ok"
        storage.delete(probe_path)
        return {"ok": ok, "backend": backend}
    except Exception as exc:
        return {"ok": False, "backend": backend, "error": str(exc)}
