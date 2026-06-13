import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import PurePosixPath

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.application.workspaces.access import ensure_workspace_member
from app.domain.documents.entities import SUPPORTED_FILE_TYPES, DocumentStatus, ExtractedDocument, ExtractedPage, OCRResult
from app.infrastructure.db.models import (
    DocumentModel,
    DocumentVersionModel,
    ExtractedDocumentModel,
    WikiAbsorbLogModel,
    WikiLinkModel,
    WikiPageModel,
)
from app.shared.ids import new_id
from app.shared.metrics import metrics
from app.shared.retry import retry_call
from app.shared.user_errors import DOCUMENT_PROCESSING_FAILED, DOCUMENT_PROCESSING_UNAVAILABLE


class DocumentService:
    def __init__(
        self,
        db: Session,
        storage,
        parser_registry,
        ocr=None,
        wiki_generator=None,
    ) -> None:
        self.db = db
        self.storage = storage
        self.parser_registry = parser_registry
        self.ocr = ocr
        if wiki_generator is None:
            raise RuntimeError(DOCUMENT_PROCESSING_UNAVAILABLE)
        self.wiki_generator = wiki_generator

    async def upload(self, user_id: str, workspace_id: str, file: UploadFile) -> dict:
        ensure_workspace_member(self.db, user_id, workspace_id)
        filename = file.filename or "document.txt"
        file_type = _file_type(filename)
        if file_type not in SUPPORTED_FILE_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
        checksum = hashlib.sha256(content).hexdigest()
        document_id = new_id()
        storage_path = str(PurePosixPath("raw") / user_id / workspace_id / document_id / _safe_filename(filename))
        self.storage.save_bytes(storage_path, content)
        document = DocumentModel(
            id=document_id,
            workspace_id=workspace_id,
            uploaded_by=user_id,
            filename=filename,
            file_type=file_type,
            storage_path=storage_path,
            status=DocumentStatus.UPLOADED.value,
            checksum=checksum,
        )
        version = DocumentVersionModel(
            id=new_id(),
            document_id=document_id,
            version_number=1,
            storage_path=storage_path,
            checksum=checksum,
        )
        self.db.add_all([document, version])
        self.db.commit()
        metrics.increment("documents.uploaded")
        return serialize_document(document)

    def list_documents(self, user_id: str, workspace_id: str) -> list[dict]:
        ensure_workspace_member(self.db, user_id, workspace_id)
        rows = (
            self.db.query(DocumentModel)
            .filter(DocumentModel.workspace_id == workspace_id)
            .order_by(DocumentModel.created_at.desc())
            .all()
        )
        return [serialize_document(row) for row in rows]

    def get_document(self, user_id: str, document_id: str) -> dict:
        document = self._get_accessible_document(user_id, document_id)
        return serialize_document(document)

    def delete_document(self, user_id: str, document_id: str) -> dict:
        document = self._get_accessible_document(user_id, document_id)
        self.db.delete(document)
        self.db.commit()
        return {"deleted": True, "document_id": document_id}

    def status(self, user_id: str, document_id: str) -> dict:
        document = self._get_accessible_document(user_id, document_id)
        return {"document_id": document.id, "status": document.status, "error_message": document.error_message}

    def process(self, user_id: str, document_id: str) -> dict:
        document = self._get_accessible_document(user_id, document_id)
        try:
            self._set_status(document, DocumentStatus.EXTRACTING)
            raw_content = retry_call(lambda: self.storage.read_bytes(document.storage_path), attempts=3)
            parser = self.parser_registry.parser_for(document.file_type)
            extracted = metrics.time(
                "document.extraction_seconds",
                lambda: retry_call(
                    lambda: parser.parse(document.id, document.filename, document.file_type, raw_content),
                    attempts=2,
                ),
            )
            extracted = self._apply_pdf_ocr_if_needed(document, raw_content, extracted)
            version = (
                self.db.query(DocumentVersionModel)
                .filter(DocumentVersionModel.document_id == document.id)
                .order_by(DocumentVersionModel.version_number.desc())
                .first()
            )
            extracted_paths = self._save_extracted(document, version.id, extracted)
            self._set_status(document, DocumentStatus.EXTRACTED)

            self._set_status(document, DocumentStatus.GENERATING_WIKI)
            existing_wiki_pages = [
                _wiki_model_to_entity(page)
                for page in self.db.query(WikiPageModel).filter(WikiPageModel.workspace_id == document.workspace_id).all()
            ]
            bundle = metrics.time(
                "document.wiki_generation_seconds",
                lambda: retry_call(
                    lambda: self.wiki_generator.generate(
                        document.workspace_id,
                        extracted,
                        existing_pages=existing_wiki_pages,
                    ),
                    attempts=2,
                ),
            )
            wiki_models = self._save_wiki_bundle(document, bundle)
            self._set_status(document, DocumentStatus.WIKI_READY)

            self._set_status(document, DocumentStatus.READY)
            metrics.increment("documents.processed")
            return {
                "document": serialize_document(document),
                "extracted": extracted_paths,
                "wiki_pages": [serialize_wiki_page(page) for page in wiki_models],
                "wiki_file_count": len(wiki_models) + 2,
            }
        except Exception as exc:
            metrics.increment("documents.processing_failures")
            document.status = DocumentStatus.FAILED.value
            document.error_message = _soft_processing_error(exc)
            self.db.commit()
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=document.error_message) from exc

    def source(self, user_id: str, document_id: str) -> dict:
        document = self._get_accessible_document(user_id, document_id)
        extracted = self.db.query(ExtractedDocumentModel).filter(ExtractedDocumentModel.document_id == document.id).first()
        extracted_payload = {}
        extracted_metadata = {}
        if extracted and self.storage.exists(extracted.text_storage_path):
            extracted_payload = json.loads(self.storage.read_text(extracted.text_storage_path))
        if extracted and self.storage.exists(extracted.metadata_storage_path):
            extracted_metadata = json.loads(self.storage.read_text(extracted.metadata_storage_path))
        wiki_pages = (
            self.db.query(WikiPageModel)
            .filter(WikiPageModel.workspace_id == document.workspace_id)
            .all()
        )
        return {
            "document": serialize_document(document),
            "extracted": extracted_payload,
            "metadata": extracted_metadata,
            "wiki_pages": [serialize_wiki_page(page) for page in wiki_pages if document.id in (page.created_from_document_ids or [])],
        }

    def _get_accessible_document(self, user_id: str, document_id: str) -> DocumentModel:
        document = self.db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        ensure_workspace_member(self.db, user_id, document.workspace_id)
        return document

    def _set_status(self, document: DocumentModel, status_value: DocumentStatus) -> None:
        document.status = status_value.value
        document.error_message = None
        self.db.add(document)
        self.db.commit()

    def _save_extracted(self, document: DocumentModel, version_id: str, extracted: ExtractedDocument) -> dict:
        base_path = PurePosixPath("extracted") / document.id
        text_path = str(base_path / "text.json")
        metadata_path = str(base_path / "metadata.json")
        metadata_payload = dict(extracted.metadata)
        ocr_raw_payload = metadata_payload.pop("_ocr_raw_payload", None)
        if ocr_raw_payload is not None:
            ocr_path = str(base_path / "ocr.json")
            self.storage.save_text(ocr_path, json.dumps(ocr_raw_payload, indent=2, default=str))
            metadata_payload["ocr_output_storage_path"] = ocr_path
        text_payload = {
            "document_id": extracted.document_id,
            "filename": extracted.filename,
            "file_type": extracted.file_type,
            "pages": [asdict(page) for page in extracted.pages],
        }
        self.storage.save_text(text_path, json.dumps(text_payload, indent=2))
        self.storage.save_text(metadata_path, json.dumps(metadata_payload, indent=2))
        existing = self.db.query(ExtractedDocumentModel).filter(ExtractedDocumentModel.document_id == document.id).first()
        if existing:
            existing.text_storage_path = text_path
            existing.metadata_storage_path = metadata_path
            existing.status = "extracted"
        else:
            self.db.add(
                ExtractedDocumentModel(
                    id=new_id(),
                    document_id=document.id,
                    version_id=version_id,
                    text_storage_path=text_path,
                    metadata_storage_path=metadata_path,
                    status="extracted",
                )
            )
        self.db.commit()
        return {"text_storage_path": text_path, "metadata_storage_path": metadata_path}

    def _apply_pdf_ocr_if_needed(self, document: DocumentModel, raw_content: bytes, extracted: ExtractedDocument) -> ExtractedDocument:
        if document.file_type != "pdf":
            return extracted
        required_pages = list(extracted.metadata.get("ocr_required_pages") or [])
        if not required_pages:
            return extracted
        if self.ocr is None:
            raise RuntimeError(DOCUMENT_PROCESSING_FAILED)
        try:
            result = metrics.time(
                "document.ocr_seconds",
                lambda: retry_call(
                    lambda: self.ocr.extract_pdf(document.id, document.filename, raw_content, required_pages),
                    attempts=1,
                ),
            )
        except Exception as exc:
            raise RuntimeError(DOCUMENT_PROCESSING_FAILED) from exc
        if result is None:
            raise RuntimeError(DOCUMENT_PROCESSING_FAILED)
        if result.metadata.get("ocr_status") in {"failed", "empty", "skipped_page_limit"} or not result.pages:
            raise RuntimeError(DOCUMENT_PROCESSING_FAILED)
        return merge_ocr_result(extracted, result)

    def _save_wiki_bundle(self, document: DocumentModel, bundle) -> list[WikiPageModel]:
        wiki_root = PurePosixPath("wiki") / document.workspace_id
        models = []
        decisions = []
        existing_pages = self.db.query(WikiPageModel).filter(WikiPageModel.workspace_id == document.workspace_id).all()
        existing_by_id = {page.id: page for page in existing_pages}
        existing_by_path = {page.path: page for page in existing_pages}
        existing_by_title = {_normalize_title(page.title): page for page in existing_pages}
        for page in bundle.pages:
            existing = (
                existing_by_id.get(page.target_page_id) if getattr(page, "target_page_id", None) else None
            ) or existing_by_path.get(page.path) or existing_by_title.get(_normalize_title(page.title))
            if existing:
                previous_document_ids = list(existing.created_from_document_ids or [])
                previous_path = existing.path
                existing.title = page.title
                existing.content = page.content
                existing.summary = page.summary
                existing.created_from_document_ids = sorted(
                    set(previous_document_ids + (page.created_from_document_ids or []) + [document.id])
                )
                if not getattr(page, "target_page_id", None) and page.path:
                    existing.path = page.path
                models.append(existing)
                existing_by_id[existing.id] = existing
                if previous_path != existing.path:
                    self.storage.delete(str(wiki_root / PurePosixPath(previous_path).name))
                existing_by_path.pop(previous_path, None)
                existing_by_path[existing.path] = existing
                existing_by_title[_normalize_title(existing.title)] = existing
                decisions.append(
                    {
                        "action": "update_page" if document.id not in previous_document_ids else "skip",
                        "page_id": existing.id,
                        "path": existing.path,
                        "title": existing.title,
                        "source_document_id": document.id,
                    }
                )
            else:
                model = WikiPageModel(
                    id=page.id,
                    workspace_id=page.workspace_id,
                    title=page.title,
                    path=page.path,
                    content=page.content,
                    summary=page.summary,
                    created_from_document_ids=page.created_from_document_ids,
                )
                self.db.add(model)
                models.append(model)
                existing_by_path[model.path] = model
                existing_by_title[_normalize_title(model.title)] = model
                decisions.append(
                    {
                        "action": "create_page",
                        "page_id": model.id,
                        "path": model.path,
                        "title": model.title,
                        "source_document_id": document.id,
                    }
                )
        self.db.flush()
        all_pages = (
            self.db.query(WikiPageModel)
            .filter(WikiPageModel.workspace_id == document.workspace_id)
            .order_by(WikiPageModel.title.asc())
            .all()
        )
        for page in models:
            self.storage.save_text(str(wiki_root / PurePosixPath(page.path).name), page.content)
        index_content = workspace_index_content(all_pages)
        backlinks = workspace_backlinks(all_pages, bundle.backlinks)
        self.storage.save_text(str(wiki_root / "INDEX.md"), index_content)
        self.storage.save_text(str(wiki_root / "_backlinks.json"), json.dumps(backlinks, indent=2))
        self._save_absorb_log(document, decisions, bundle.absorb_log)
        self.db.commit()
        if getattr(bundle, "links", None):
            self._save_wiki_links(document.workspace_id, bundle.links)
        return models

    def _save_absorb_log(self, document: DocumentModel, decisions: list[dict], raw_absorb_log: dict) -> None:
        wiki_root = PurePosixPath("wiki") / document.workspace_id
        action_counts = dict(Counter(decision["action"] for decision in decisions))
        payload = {
            "document_id": document.id,
            "filename": document.filename,
            "strategy": raw_absorb_log.get("strategy", "workspace-absorb") if isinstance(raw_absorb_log, dict) else "workspace-absorb",
            "action_counts": action_counts,
            "decisions": decisions,
            "raw_absorb_log": raw_absorb_log,
        }
        log_path = str(wiki_root / "absorb_logs" / f"{document.id}.json")
        self.storage.save_text(log_path, json.dumps(payload, indent=2, default=str))
        self.storage.save_text(str(wiki_root / "_absorb_log.json"), json.dumps(payload, indent=2, default=str))
        self.db.add(
            WikiAbsorbLogModel(
                id=new_id(),
                workspace_id=document.workspace_id,
                document_id=document.id,
                storage_path=log_path,
                decisions_json=decisions,
                action_counts=action_counts,
            )
        )

    def _save_wiki_links(self, workspace_id: str, links) -> None:
        self.db.query(WikiLinkModel).filter(WikiLinkModel.workspace_id == workspace_id).delete()
        for link in links:
            self.db.add(
                WikiLinkModel(
                    id=new_id(),
                    workspace_id=workspace_id,
                    source_page_id=link.source_page_id,
                    target_page_id=link.target_page_id,
                    link_type=link.link_type,
                )
            )
        self.db.commit()


def _file_type(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return "md" if suffix == "markdown" else suffix


def _safe_filename(filename: str) -> str:
    return "".join(character if character.isalnum() or character in {".", "-", "_"} else "_" for character in filename)


def _soft_processing_error(exc: Exception) -> str:
    message = str(exc)
    if message in {DOCUMENT_PROCESSING_FAILED, DOCUMENT_PROCESSING_UNAVAILABLE}:
        return message
    return DOCUMENT_PROCESSING_FAILED


def _wiki_model_to_entity(model: WikiPageModel):
    from app.domain.wiki.entities import WikiPage

    return WikiPage(
        id=model.id,
        workspace_id=model.workspace_id,
        title=model.title,
        path=model.path,
        content=model.content,
        summary=model.summary,
        created_from_document_ids=model.created_from_document_ids or [],
    )


def merge_ocr_result(extracted: ExtractedDocument, result: OCRResult) -> ExtractedDocument:
    ocr_pages = {page.page_number: page for page in result.pages}
    merged_pages = []
    completed_pages = []
    for page in extracted.pages:
        ocr_page = ocr_pages.get(page.page_number)
        if ocr_page and ocr_page.text.strip() and not page.text.strip():
            merged_pages.append(ocr_page)
            completed_pages.append(page.page_number)
        elif ocr_page and ocr_page.text.strip() and len(ocr_page.text.strip()) > len(page.text.strip()) * 1.5:
            merged_pages.append(
                ExtractedPage(
                    page_number=page.page_number,
                    text=ocr_page.text,
                    headings=page.headings or ocr_page.headings,
                    tables=ocr_page.tables or page.tables,
                )
            )
            completed_pages.append(page.page_number)
        else:
            merged_pages.append(page)
    existing_page_numbers = {page.page_number for page in merged_pages}
    for page in result.pages:
        if page.page_number not in existing_page_numbers and page.text.strip():
            merged_pages.append(page)
            completed_pages.append(page.page_number)

    required_pages = list(extracted.metadata.get("ocr_required_pages") or [])
    failed_pages = [page for page in required_pages if page not in completed_pages]
    metadata = {
        **extracted.metadata,
        **result.metadata,
        "ocr_completed_pages": sorted(set(completed_pages or result.metadata.get("ocr_completed_pages") or [])),
        "ocr_failed_pages": failed_pages,
        "_ocr_raw_payload": result.raw_payload,
    }
    if completed_pages and failed_pages:
        metadata["ocr_status"] = "partial"
    elif completed_pages:
        metadata["ocr_status"] = result.metadata.get("ocr_status") or "completed"
    elif result.metadata.get("ocr_status") not in {"skipped_page_limit", "failed"}:
        metadata["ocr_status"] = "empty"
    return ExtractedDocument(
        document_id=extracted.document_id,
        filename=extracted.filename,
        file_type=extracted.file_type,
        pages=sorted(merged_pages, key=lambda page: page.page_number),
        metadata=metadata,
    )


def workspace_index_content(pages: list[WikiPageModel]) -> str:
    lines = ["# Wikitics Index", ""]
    for page in pages:
        lines.append(f"- [{page.title}]({page.path}) - {page.summary}")
    return "\n".join(lines).rstrip() + "\n"


def workspace_backlinks(pages: list[WikiPageModel], generated_backlinks: dict | None = None) -> dict[str, list[str]]:
    backlinks = {page.path: [] for page in pages}
    if isinstance(generated_backlinks, dict):
        known_paths = set(backlinks)
        title_lookup = {_normalize_title(page.title): page.path for page in pages}
        for target, sources in generated_backlinks.items():
            normalized_target = _normalize_backlink_reference(target, known_paths, title_lookup)
            if normalized_target is None or not isinstance(sources, list):
                continue
            normalized_sources = {
                normalized_source
                for source in sources
                if (normalized_source := _normalize_backlink_reference(source, known_paths, title_lookup))
                and normalized_source != normalized_target
            }
            backlinks[normalized_target] = sorted(normalized_sources)
    return backlinks


def _normalize_title(title: str) -> str:
    return " ".join(str(title or "").lower().split())


def _normalize_backlink_reference(
    value: object,
    known_paths: set[str],
    title_lookup: dict[str, str],
) -> str | None:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate in known_paths:
            return candidate
        return title_lookup.get(_normalize_title(candidate))
    if isinstance(value, dict):
        for key in ("path", "page_path", "source_path", "target_path", "source", "target", "page", "title", "name"):
            normalized = _normalize_backlink_reference(value.get(key), known_paths, title_lookup)
            if normalized:
                return normalized
    return None


def serialize_document(document: DocumentModel) -> dict:
    return {
        "id": document.id,
        "workspace_id": document.workspace_id,
        "uploaded_by": document.uploaded_by,
        "filename": document.filename,
        "file_type": document.file_type,
        "storage_path": document.storage_path,
        "status": document.status,
        "checksum": document.checksum,
        "error_message": document.error_message,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def serialize_wiki_page(page: WikiPageModel) -> dict:
    return {
        "id": page.id,
        "workspace_id": page.workspace_id,
        "title": page.title,
        "path": page.path,
        "content": page.content,
        "summary": page.summary,
        "created_from_document_ids": page.created_from_document_ids or [],
        "created_at": page.created_at.isoformat(),
        "updated_at": page.updated_at.isoformat(),
    }
