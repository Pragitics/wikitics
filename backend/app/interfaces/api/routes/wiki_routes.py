import json
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.llm.openrouter_wiki_maintenance_adapter import OpenRouterWikiMaintenanceAdapter
from app.application.documents.service import serialize_wiki_page, workspace_backlinks, workspace_index_content
from app.application.workspaces.access import ensure_workspace_member
from app.infrastructure.db.models import (
    CitationModel,
    DocumentModel,
    UserModel,
    WikiAbsorbLogModel,
    WikiLinkModel,
    WikiMaintenanceLogModel,
    WikiPageModel,
    WikiRevisionModel,
)
from app.infrastructure.db.session import get_db
from app.infrastructure.settings import Settings
from app.interfaces.api.dependencies import get_current_user, settings_dependency, storage_dependency
from app.shared.ids import new_id
from app.shared.user_errors import AI_SERVICE_UNAVAILABLE

router = APIRouter(prefix="/api/workspaces/{workspace_id}/wiki", tags=["wiki"])


class WikiPagePatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    content: str | None = Field(default=None, min_length=1)
    summary: str | None = None
    edit_note: str | None = None
    edit_actor: str = "admin"


class WikiPageCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    summary: str | None = None
    path: str | None = None
    created_from_document_ids: list[str] = Field(default_factory=list)
    edit_actor: str = "admin"


class WikiPageRevertRequest(BaseModel):
    revision_id: str
    edit_note: str | None = None


@router.get("")
def list_wiki_pages(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> list[dict]:
    ensure_workspace_member(db, user.id, workspace_id)
    rows = db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id).order_by(WikiPageModel.title).all()
    return [serialize_wiki_page(row) for row in rows]


@router.get("/pages/{page_id}")
def get_wiki_page(
    workspace_id: str,
    page_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> dict:
    ensure_workspace_member(db, user.id, workspace_id)
    page = db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id, WikiPageModel.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wiki page not found")
    return serialize_wiki_page(page)


@router.post("/pages", status_code=status.HTTP_201_CREATED)
def create_wiki_page(
    workspace_id: str,
    payload: WikiPageCreateRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
    storage=Depends(storage_dependency),
) -> dict:
    ensure_workspace_member(db, user.id, workspace_id)
    title = payload.title.strip()
    path = _normalized_wiki_path(payload.path, title)
    normalized_title = _normalized_title_key(title)
    existing_pages = db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id).all()
    if any(_normalized_title_key(page.title) == normalized_title for page in existing_pages):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Wiki page title already exists")
    if any(page.path == path for page in existing_pages):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Wiki page path already exists")
    document_ids = _validated_document_ids(db, workspace_id, payload.created_from_document_ids)
    content = _normalized_wiki_content(title, payload.content)
    summary = str(payload.summary or "").strip() or _summary_from_content(content)
    page = WikiPageModel(
        id=new_id(),
        workspace_id=workspace_id,
        title=title,
        path=path,
        content=content,
        summary=summary,
        created_from_document_ids=document_ids,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    _write_wiki_page(storage, workspace_id, page)
    _rebuild_workspace_graph(db, storage, workspace_id)
    return serialize_wiki_page(page)


@router.patch("/pages/{page_id}")
def update_wiki_page(
    workspace_id: str,
    page_id: str,
    payload: WikiPagePatchRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
    storage=Depends(storage_dependency),
) -> dict:
    ensure_workspace_member(db, user.id, workspace_id)
    page = _wiki_page_or_404(db, workspace_id, page_id)
    if payload.title is None and payload.content is None and payload.summary is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No wiki changes provided")
    _save_revision(db, page, user.id, payload.edit_actor, payload.edit_note or "Before wiki edit")
    if payload.title is not None:
        page.title = payload.title.strip()
    if payload.content is not None:
        page.content = payload.content.strip()
    if payload.summary is not None:
        page.summary = payload.summary.strip()
    db.commit()
    db.refresh(page)
    _write_wiki_page(storage, workspace_id, page)
    _rebuild_workspace_graph(db, storage, workspace_id)
    return serialize_wiki_page(page)


@router.delete("/pages/{page_id}")
def delete_wiki_page(
    workspace_id: str,
    page_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
    storage=Depends(storage_dependency),
) -> dict:
    ensure_workspace_member(db, user.id, workspace_id)
    page = _wiki_page_or_404(db, workspace_id, page_id)
    deleted_path = page.path
    db.query(CitationModel).filter(CitationModel.wiki_page_id == page.id).update(
        {CitationModel.wiki_page_id: None},
        synchronize_session=False,
    )
    db.query(WikiRevisionModel).filter(
        WikiRevisionModel.workspace_id == workspace_id,
        WikiRevisionModel.page_id == page.id,
    ).delete(synchronize_session=False)
    db.query(WikiLinkModel).filter(
        WikiLinkModel.workspace_id == workspace_id,
        WikiLinkModel.source_page_id == page.id,
    ).delete(synchronize_session=False)
    db.query(WikiLinkModel).filter(
        WikiLinkModel.workspace_id == workspace_id,
        WikiLinkModel.target_page_id == page.id,
    ).delete(synchronize_session=False)
    db.delete(page)
    db.commit()
    storage.delete(str(PurePosixPath("wiki") / workspace_id / PurePosixPath(deleted_path).name))
    _rebuild_workspace_graph(db, storage, workspace_id)
    return {"deleted": True, "page_id": page_id, "workspace_id": workspace_id}


@router.get("/pages/{page_id}/revisions")
def list_wiki_page_revisions(
    workspace_id: str,
    page_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> list[dict]:
    ensure_workspace_member(db, user.id, workspace_id)
    _wiki_page_or_404(db, workspace_id, page_id)
    rows = (
        db.query(WikiRevisionModel)
        .filter(WikiRevisionModel.workspace_id == workspace_id, WikiRevisionModel.page_id == page_id)
        .order_by(WikiRevisionModel.created_at.desc())
        .all()
    )
    return [serialize_revision(row) for row in rows]


@router.post("/pages/{page_id}/revert")
def revert_wiki_page(
    workspace_id: str,
    page_id: str,
    payload: WikiPageRevertRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
    storage=Depends(storage_dependency),
) -> dict:
    ensure_workspace_member(db, user.id, workspace_id)
    page = _wiki_page_or_404(db, workspace_id, page_id)
    revision = (
        db.query(WikiRevisionModel)
        .filter(
            WikiRevisionModel.workspace_id == workspace_id,
            WikiRevisionModel.page_id == page_id,
            WikiRevisionModel.id == payload.revision_id,
        )
        .first()
    )
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wiki revision not found")
    _save_revision(db, page, user.id, "admin", payload.edit_note or "Before wiki revert")
    page.title = revision.title
    page.content = revision.content
    page.summary = revision.summary
    db.commit()
    db.refresh(page)
    _write_wiki_page(storage, workspace_id, page)
    _rebuild_workspace_graph(db, storage, workspace_id)
    return serialize_wiki_page(page)


@router.get("/index")
def get_wiki_index(workspace_id: str, db: Session = Depends(get_db), user: UserModel = Depends(get_current_user), storage=Depends(storage_dependency)) -> dict:
    ensure_workspace_member(db, user.id, workspace_id)
    path = f"wiki/{workspace_id}/INDEX.md"
    return {"path": path, "content": storage.read_text(path) if storage.exists(path) else ""}


@router.get("/backlinks")
def get_wiki_backlinks(workspace_id: str, db: Session = Depends(get_db), user: UserModel = Depends(get_current_user), storage=Depends(storage_dependency)) -> dict:
    ensure_workspace_member(db, user.id, workspace_id)
    path = f"wiki/{workspace_id}/_backlinks.json"
    return {"path": path, "backlinks": json.loads(storage.read_text(path)) if storage.exists(path) else {}}


@router.get("/absorb-logs")
def list_wiki_absorb_logs(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> list[dict]:
    ensure_workspace_member(db, user.id, workspace_id)
    rows = (
        db.query(WikiAbsorbLogModel)
        .filter(WikiAbsorbLogModel.workspace_id == workspace_id)
        .order_by(WikiAbsorbLogModel.created_at.desc())
        .all()
    )
    return [serialize_absorb_log(row) for row in rows]


@router.post("/maintain")
def maintain_wiki(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
    storage=Depends(storage_dependency),
    settings: Settings = Depends(settings_dependency),
) -> dict:
    ensure_workspace_member(db, user.id, workspace_id)
    pages = db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id).order_by(WikiPageModel.title.asc()).all()
    issues = validate_wiki_pages(pages)
    blocking_issues = [issue for issue in issues if issue["issue"] == "prompt_injection_text"]
    if blocking_issues:
        log = WikiMaintenanceLogModel(
            id=new_id(),
            workspace_id=workspace_id,
            status="quarantined",
            action="validate_wiki",
            details_json={"issues": blocking_issues},
        )
        db.add(log)
        db.commit()
        return {"workspace_id": workspace_id, "status": "quarantined", "issues": blocking_issues, "changed_page_ids": []}

    maintainer = OpenRouterWikiMaintenanceAdapter(
        settings.openrouter_api_key,
        str(settings.openrouter_base_url),
        settings.openrouter_wiki_model,
    )
    repair_result = _repair_wiki_pages(db, storage, user.id, workspace_id, pages, maintainer)
    pages = db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id).order_by(WikiPageModel.title.asc()).all()
    remaining_issues = validate_wiki_pages(pages)
    if remaining_issues:
        log = WikiMaintenanceLogModel(
            id=new_id(),
            workspace_id=workspace_id,
            status="quarantined",
            action="autonomous_repair",
            details_json={**repair_result, "issues": remaining_issues},
        )
        db.add(log)
        db.commit()
        return {
            "workspace_id": workspace_id,
            "status": "quarantined",
            "issues": remaining_issues,
            "changed_page_ids": repair_result["changed_page_ids"],
        }

    _rebuild_workspace_graph(db, storage, workspace_id)
    changed_page_ids = repair_result["changed_page_ids"]
    action = "autonomous_repair" if repair_result["actions"] else "validate_wiki"
    log = WikiMaintenanceLogModel(
        id=new_id(),
        workspace_id=workspace_id,
        status="completed",
        action=action,
        details_json={
            "page_count": len(pages),
            **repair_result,
        },
    )
    db.add(log)
    db.commit()
    return {
        "workspace_id": workspace_id,
        "status": "completed",
        "issues": [],
        "changed_page_ids": changed_page_ids,
        "deleted_page_ids": repair_result["deleted_page_ids"],
        "actions": repair_result["actions"],
    }


@router.get("/maintenance-logs")
def list_wiki_maintenance_logs(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> list[dict]:
    ensure_workspace_member(db, user.id, workspace_id)
    rows = (
        db.query(WikiMaintenanceLogModel)
        .filter(WikiMaintenanceLogModel.workspace_id == workspace_id)
        .order_by(WikiMaintenanceLogModel.created_at.desc())
        .all()
    )
    return [serialize_maintenance_log(row) for row in rows]


def serialize_absorb_log(row: WikiAbsorbLogModel) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "document_id": row.document_id,
        "storage_path": row.storage_path,
        "decisions": row.decisions_json or [],
        "action_counts": row.action_counts or {},
        "created_at": row.created_at.isoformat(),
    }


def serialize_maintenance_log(row: WikiMaintenanceLogModel) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "status": row.status,
        "action": row.action,
        "details": row.details_json or {},
        "created_at": row.created_at.isoformat(),
    }


def validate_wiki_pages(pages: list[WikiPageModel]) -> list[dict]:
    injection_patterns = [
        "ignore previous instructions",
        "ignore all previous instructions",
        "system prompt",
        "developer message",
    ]
    issues = []
    for page in pages:
        lowered = page.content.lower()
        matched = [pattern for pattern in injection_patterns if pattern in lowered]
        if matched:
            issues.append({"page_id": page.id, "path": page.path, "issue": "prompt_injection_text", "matches": matched})
        if not page.created_from_document_ids:
            issues.append({"page_id": page.id, "path": page.path, "issue": "missing_source_provenance"})
        if not page.content.strip().startswith("#"):
            issues.append({"page_id": page.id, "path": page.path, "issue": "invalid_markdown_heading"})
    return issues


def serialize_revision(row: WikiRevisionModel) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "page_id": row.page_id,
        "title": row.title,
        "content": row.content,
        "summary": row.summary,
        "edited_by": row.edited_by,
        "edit_actor": row.edit_actor,
        "edit_note": row.edit_note,
        "created_at": row.created_at.isoformat(),
    }


def _validated_document_ids(db: Session, workspace_id: str, document_ids: list[str]) -> list[str]:
    requested = sorted({document_id for document_id in document_ids if document_id})
    if not requested:
        return []
    existing = {
        row.id
        for row in db.query(DocumentModel.id)
        .filter(DocumentModel.workspace_id == workspace_id, DocumentModel.id.in_(requested))
        .all()
    }
    missing = [document_id for document_id in requested if document_id not in existing]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid document ids for workspace wiki page")
    return requested


def _normalized_title_key(title: str) -> str:
    return " ".join(str(title or "").strip().lower().split())


def _normalized_wiki_path(path: str | None, title: str) -> str:
    candidate = str(path or "").strip()
    if not candidate:
        candidate = _slugify(title)
    if candidate.endswith(".md"):
        candidate = candidate[:-3]
    candidate = candidate.strip("/")
    if candidate.startswith("wiki/"):
        candidate = candidate[5:]
    return candidate or _slugify(title)


def _normalized_wiki_content(title: str, content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("#"):
        return cleaned
    return f"# {title}\n\n{cleaned}"


def _summary_from_content(content: str) -> str:
    normalized = " ".join(content.replace("#", " ").split())
    return normalized[:1000]


def _slugify(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in str(value or ""))
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "page"


def _wiki_page_or_404(db: Session, workspace_id: str, page_id: str) -> WikiPageModel:
    page = db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id, WikiPageModel.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wiki page not found")
    return page


def _save_revision(db: Session, page: WikiPageModel, edited_by: str, edit_actor: str, edit_note: str) -> None:
    db.add(
        WikiRevisionModel(
            id=new_id(),
            workspace_id=page.workspace_id,
            page_id=page.id,
            title=page.title,
            content=page.content,
            summary=page.summary,
            edited_by=edited_by,
            edit_actor=edit_actor,
            edit_note=edit_note,
        )
    )


def _write_wiki_page(storage, workspace_id: str, page: WikiPageModel) -> None:
    storage.save_text(str(PurePosixPath("wiki") / workspace_id / PurePosixPath(page.path).name), page.content)


def _rebuild_workspace_graph(db: Session, storage, workspace_id: str) -> None:
    pages = db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id).order_by(WikiPageModel.title.asc()).all()
    wiki_root = PurePosixPath("wiki") / workspace_id
    storage.save_text(str(wiki_root / "INDEX.md"), workspace_index_content(pages))
    storage.save_text(str(wiki_root / "_backlinks.json"), json.dumps(workspace_backlinks(pages), indent=2))


def _repair_wiki_pages(
    db: Session,
    storage,
    user_id: str,
    workspace_id: str,
    pages: list[WikiPageModel],
    maintainer=None,
) -> dict:
    changed_page_ids: set[str] = set()
    deleted_page_ids: list[str] = []
    actions: list[dict] = []
    document_ids = [
        row.id
        for row in db.query(DocumentModel.id)
        .filter(DocumentModel.workspace_id == workspace_id)
        .order_by(DocumentModel.created_at.asc())
        .all()
    ]

    for group in _duplicate_page_groups(pages):
        primary = sorted(group, key=lambda page: (page.created_at, page.id))[0]
        duplicates = [page for page in group if page.id != primary.id]
        _save_revision(db, primary, user_id, "llm_maintenance", "Before autonomous duplicate merge")
        for duplicate in duplicates:
            merge_plan = _safe_merge_plan(maintainer, primary, duplicate)
            if not merge_plan:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=AI_SERVICE_UNAVAILABLE)
            primary.content = merge_plan["content"]
            primary.summary = merge_plan["summary"] or _merge_text(primary.summary, duplicate.summary)
            primary.created_from_document_ids = sorted(
                set((primary.created_from_document_ids or []) + (duplicate.created_from_document_ids or []))
            )
            _save_revision(db, duplicate, user_id, "llm_maintenance", "Before autonomous duplicate removal")
            if duplicate.path != primary.path:
                storage.delete(str(PurePosixPath("wiki") / workspace_id / PurePosixPath(duplicate.path).name))
            db.delete(duplicate)
            deleted_page_ids.append(duplicate.id)
        changed_page_ids.add(primary.id)
        actions.append(
            {
                "action": "merge_duplicate_pages",
                "page_id": primary.id,
                "merged_page_ids": [page.id for page in duplicates],
                "strategy": "llm",
            }
        )

    db.flush()
    active_pages = db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id).order_by(WikiPageModel.title.asc()).all()
    for page in active_pages:
        repaired = False
        if not page.content.strip().startswith("#"):
            _save_revision(db, page, user_id, "llm_maintenance", "Before autonomous heading repair")
            page.content = f"# {page.title}\n\n{page.content.strip()}".strip()
            changed_page_ids.add(page.id)
            actions.append({"action": "repair_markdown_heading", "page_id": page.id})
            repaired = True
        if not page.created_from_document_ids and len(document_ids) == 1:
            if not repaired:
                _save_revision(db, page, user_id, "llm_maintenance", "Before autonomous provenance repair")
            page.created_from_document_ids = [document_ids[0]]
            changed_page_ids.add(page.id)
            actions.append({"action": "repair_missing_provenance", "page_id": page.id, "document_id": document_ids[0]})

    db.commit()
    for page in db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id, WikiPageModel.id.in_(changed_page_ids)).all():
        _write_wiki_page(storage, workspace_id, page)

    return {
        "changed_page_ids": sorted(changed_page_ids),
        "deleted_page_ids": deleted_page_ids,
        "actions": actions,
    }


def _duplicate_page_groups(pages: list[WikiPageModel]) -> list[list[WikiPageModel]]:
    groups: dict[str, list[WikiPageModel]] = {}
    for page in pages:
        key = " ".join(page.title.lower().split())
        groups.setdefault(key, []).append(page)
    return [group for group in groups.values() if len(group) > 1]


def _safe_merge_plan(maintainer, primary: WikiPageModel, duplicate: WikiPageModel) -> dict | None:
    if maintainer is None:
        return None
    try:
        plan = maintainer.merge_pages(primary, duplicate)
    except Exception:
        return None
    if not plan or _content_has_prompt_injection(plan.get("content", "")):
        return None
    return plan


def _content_has_prompt_injection(content: str) -> bool:
    lowered = str(content or "").lower()
    return any(
        pattern in lowered
        for pattern in [
            "ignore previous instructions",
            "ignore all previous instructions",
            "system prompt",
            "developer message",
        ]
    )


def _merge_text(first: str, second: str) -> str:
    first_value = " ".join(str(first or "").split())
    second_value = " ".join(str(second or "").split())
    if not second_value or second_value in first_value:
        return first_value
    if not first_value:
        return second_value[:1000]
    return f"{first_value} {second_value}"[:1000]
