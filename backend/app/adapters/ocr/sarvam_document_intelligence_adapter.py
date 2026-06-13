import json
import time
import zipfile
from io import BytesIO
from typing import Any

import httpx

from app.domain.documents.entities import ExtractedPage, OCRResult


COMPLETED_STATES = {"Completed", "PartiallyCompleted"}
TERMINAL_STATES = COMPLETED_STATES | {"Failed"}


class SarvamDocumentIntelligenceOCRAdapter:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.sarvam.ai/doc-digitization/job/v1",
        language: str = "en-IN",
        output_format: str = "md",
        poll_interval_seconds: float = 2.0,
        timeout_seconds: float = 120.0,
        max_pages: int = 10,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.language = language
        self.output_format = output_format
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages

    def extract_pdf(self, document_id: str, filename: str, content: bytes, page_numbers: list[int]) -> OCRResult | None:
        if not self.api_key or not page_numbers:
            return None
        if max(page_numbers, default=0) > self.max_pages:
            return OCRResult(
                pages=[],
                metadata={
                    "ocr_provider": "sarvam_document_intelligence",
                    "ocr_status": "skipped_page_limit",
                    "ocr_required_pages": page_numbers,
                    "ocr_max_pages": self.max_pages,
                },
                raw_payload={},
            )

        with httpx.Client(timeout=30) as client:
            job = self._create_job(client)
            job_id = job["job_id"]
            upload = self._upload_links(client, job_id, filename)
            self._upload_file(client, upload, filename, content)
            self._start_job(client, job_id)
            status = self._wait_for_completion(client, job_id)
            if status.get("job_state") not in COMPLETED_STATES:
                return OCRResult(
                    pages=[],
                    metadata={
                        "ocr_provider": "sarvam_document_intelligence",
                        "ocr_status": "failed",
                        "ocr_required_pages": page_numbers,
                        "ocr_job_id": job_id,
                        "ocr_error": status.get("error_message") or "Document intelligence job failed",
                    },
                    raw_payload=status,
                )
            downloads = self._download_links(client, job_id)
            raw_payload = self._download_outputs(client, downloads)

        pages = pages_from_document_intelligence_payload(raw_payload)
        completed_pages = [page.page_number for page in pages if page.text.strip()]
        return OCRResult(
            pages=pages,
            metadata={
                "ocr_provider": "sarvam_document_intelligence",
                "ocr_status": "completed" if completed_pages else "empty",
                "ocr_required_pages": page_numbers,
                "ocr_completed_pages": completed_pages,
                "ocr_job_id": job_id,
                "ocr_page_metrics": page_metrics(status),
            },
            raw_payload=raw_payload,
        )

    def _create_job(self, client: httpx.Client) -> dict:
        response = client.post(
            self.base_url,
            headers=self._headers(),
            json={"job_parameters": {"language": self.language, "output_format": self.output_format}},
        )
        response.raise_for_status()
        return response.json()

    def _upload_links(self, client: httpx.Client, job_id: str, filename: str) -> dict:
        response = client.post(
            f"{self.base_url}/upload-files",
            headers=self._headers(),
            json={"job_id": job_id, "files": [filename]},
        )
        response.raise_for_status()
        return response.json()

    def _upload_file(self, client: httpx.Client, upload_payload: dict, filename: str, content: bytes) -> None:
        upload_urls = upload_payload.get("upload_urls") or {}
        upload_entry = upload_urls.get(filename) or next(iter(upload_urls.values()), None)
        upload_url, headers = upload_url_and_headers(upload_entry)
        if not upload_url:
            raise ValueError("Sarvam upload URL missing")
        response = client.put(upload_url, content=content, headers=headers)
        response.raise_for_status()

    def _start_job(self, client: httpx.Client, job_id: str) -> dict:
        response = client.post(f"{self.base_url}/{job_id}/start", headers=self._headers(), json={})
        response.raise_for_status()
        return response.json()

    def _wait_for_completion(self, client: httpx.Client, job_id: str) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        last_status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = client.get(f"{self.base_url}/{job_id}/status", headers=self._headers())
            response.raise_for_status()
            last_status = response.json()
            if last_status.get("job_state") in TERMINAL_STATES:
                return last_status
            time.sleep(self.poll_interval_seconds)
        return {**last_status, "job_state": last_status.get("job_state") or "TimedOut", "error_message": "OCR job timed out"}

    def _download_links(self, client: httpx.Client, job_id: str) -> dict:
        response = client.post(f"{self.base_url}/{job_id}/download-files", headers=self._headers(), json={})
        response.raise_for_status()
        return response.json()

    def _download_outputs(self, client: httpx.Client, download_payload: dict) -> dict:
        outputs = {}
        for filename, entry in (download_payload.get("download_urls") or {}).items():
            file_url, headers = download_url_and_headers(entry)
            if not file_url:
                continue
            response = client.get(file_url, headers=headers)
            response.raise_for_status()
            outputs[filename] = decode_output_file(filename, response.content)
        return {"download_payload": download_payload, "outputs": outputs}

    def _headers(self) -> dict:
        return {"api-subscription-key": self.api_key, "Content-Type": "application/json"}


def upload_url_and_headers(entry: Any) -> tuple[str | None, dict]:
    if isinstance(entry, str):
        return entry, {}
    if not isinstance(entry, dict):
        return None, {}
    return entry.get("file_url") or entry.get("upload_url") or entry.get("url"), entry.get("headers") or {}


def download_url_and_headers(entry: Any) -> tuple[str | None, dict]:
    if isinstance(entry, str):
        return entry, {}
    if not isinstance(entry, dict):
        return None, {}
    return entry.get("file_url") or entry.get("download_url") or entry.get("url"), entry.get("headers") or {}


def decode_output_file(filename: str, content: bytes) -> Any:
    lowered = filename.lower()
    if lowered.endswith(".zip") or zipfile.is_zipfile(BytesIO(content)):
        with zipfile.ZipFile(BytesIO(content)) as archive:
            return {
                name: decode_output_file(name, archive.read(name))
                for name in archive.namelist()
                if not name.endswith("/")
            }
    if lowered.endswith(".json"):
        return json.loads(content.decode("utf-8", errors="replace"))
    return content.decode("utf-8", errors="replace")


def pages_from_document_intelligence_payload(payload: Any) -> list[ExtractedPage]:
    page_payloads = _find_page_payloads(payload)
    if not page_payloads:
        text = "\n\n".join(_find_text_payloads(payload))
        return [ExtractedPage(page_number=1, text=text, headings=[])] if text.strip() else []
    pages = []
    for fallback_number, page_payload in enumerate(page_payloads, start=1):
        if not isinstance(page_payload, dict):
            continue
        page_number = int(
            page_payload.get("page_number")
            or page_payload.get("page")
            or page_payload.get("page_no")
            or page_payload.get("index")
            or fallback_number
        )
        text = page_text(page_payload)
        tables = page_payload.get("tables") if isinstance(page_payload.get("tables"), list) else []
        pages.append(ExtractedPage(page_number=page_number, text=text, headings=[], tables=tables))
    return pages


def page_text(page_payload: dict) -> str:
    parts = []
    for key in ("text", "content", "markdown", "md", "html"):
        value = page_payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if not parts:
        parts.extend(_find_text_payloads(page_payload))
    return "\n\n".join(dict.fromkeys(parts))


def _find_page_payloads(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        for key in ("pages", "page_data", "pageData", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for value in payload.values():
            found = _find_page_payloads(value)
            if found:
                return found
    if isinstance(payload, list):
        if payload and all(isinstance(item, dict) and any(key in item for key in ("page_number", "page", "text", "markdown")) for item in payload):
            return payload
        for item in payload:
            found = _find_page_payloads(item)
            if found:
                return found
    return []


def _find_text_payloads(payload: Any) -> list[str]:
    texts = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"text", "content", "markdown", "md"} and isinstance(value, str) and value.strip():
                texts.append(value.strip())
            elif isinstance(value, (dict, list)):
                texts.extend(_find_text_payloads(value))
    elif isinstance(payload, list):
        for item in payload:
            texts.extend(_find_text_payloads(item))
    return texts


def page_metrics(status_payload: dict) -> dict:
    if isinstance(status_payload.get("page_metrics"), dict):
        return status_payload["page_metrics"]
    details = status_payload.get("job_details")
    if isinstance(details, list) and details:
        first = details[0]
        return {
            key: first.get(key)
            for key in ("total_pages", "pages_processed", "pages_succeeded", "pages_failed", "page_errors")
            if key in first
        }
    return {}
