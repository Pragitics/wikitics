from dataclasses import dataclass, field
from enum import StrEnum

from app.shared.ids import new_id


class DocumentJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class DocumentProcessingJob:
    document_id: str
    workspace_id: str
    user_id: str
    id: str = field(default_factory=new_id)
    status: DocumentJobStatus = DocumentJobStatus.QUEUED
    error_message: str | None = None


class InMemoryDocumentJobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, DocumentProcessingJob] = {}

    def enqueue(self, document_id: str, workspace_id: str, user_id: str) -> DocumentProcessingJob:
        job = DocumentProcessingJob(document_id=document_id, workspace_id=workspace_id, user_id=user_id)
        self.jobs[job.id] = job
        return job

    def get(self, job_id: str) -> DocumentProcessingJob | None:
        return self.jobs.get(job_id)

    def mark_running(self, job_id: str) -> None:
        if job := self.jobs.get(job_id):
            job.status = DocumentJobStatus.RUNNING

    def mark_complete(self, job_id: str) -> None:
        if job := self.jobs.get(job_id):
            job.status = DocumentJobStatus.COMPLETE

    def mark_failed(self, job_id: str, error_message: str) -> None:
        if job := self.jobs.get(job_id):
            job.status = DocumentJobStatus.FAILED
            job.error_message = error_message
