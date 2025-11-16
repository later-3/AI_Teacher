from __future__ import annotations

import logging
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from queue import Empty, Queue
from threading import Event, Thread
from typing import Optional

from ..config import get_settings
from ..database import session_context
from ..models import (
    Course,
    EmbeddingStatus,
    ProcessingStage,
    Resource,
    ResourceStatus,
    ResourceType,
)
from . import assembly, pipelines, validation
from .embedding_pipeline import run_course_embedding

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    process_resource = "process_resource"
    embed_course = "embed_course"


@dataclass
class WorkerTask:
    type: TaskType
    resource_id: Optional[int] = None
    course_id: Optional[int] = None


class ResourceProcessor:
    """Background worker that processes ingestion resources sequentially."""

    def __init__(self) -> None:
        self.queue: "Queue[WorkerTask]" = Queue()
        self.stop_event = Event()
        self.worker = Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

    def enqueue_resource(self, resource_id: int) -> None:
        """Queue a resource for processing and mark it as queued."""
        with session_context() as session:
            resource = session.get(Resource, resource_id)
            if not resource:
                logger.warning("Resource %s not found when enqueuing", resource_id)
                return
            resource.status = ResourceStatus.queued
            resource.processing_stage = ProcessingStage.waiting
            resource.updated_at = datetime.utcnow()
            session.add(resource)
            session.commit()

        self.queue.put(WorkerTask(type=TaskType.process_resource, resource_id=resource_id))

    def enqueue_course_embedding(self, course_id: int) -> None:
        """Queue a course-level embedding任务."""
        with session_context() as session:
            course = session.get(Course, course_id)
            if not course:
                logger.warning("Course %s not found when scheduling embedding", course_id)
                return
            if course.embedding_status == EmbeddingStatus.running:
                logger.info("Course %s embedding already running; skip enqueue", course_id)
                return
            course.embedding_status = EmbeddingStatus.pending
            course.embedding_progress = 0.0
            course.embedding_error = None
            session.add(course)
            session.commit()
        self.queue.put(WorkerTask(type=TaskType.embed_course, course_id=course_id))

    def _worker_loop(self) -> None:
        logger.info("Resource processor worker started")
        while not self.stop_event.is_set():
            try:
                task = self.queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                if task.type == TaskType.process_resource and task.resource_id is not None:
                    self._process_resource(task.resource_id)
                elif task.type == TaskType.embed_course and task.course_id is not None:
                    self._process_course_embedding(task.course_id)
                else:
                    logger.warning("Received invalid worker task: %s", task)
            finally:
                self.queue.task_done()

    def _process_course_embedding(self, course_id: int) -> None:
        """Trigger the embedding pipeline for a course."""
        settings = get_settings()
        with session_context() as session:
            try:
                run_course_embedding(session, course_id, settings.embedding_batch_size)
            except ValueError as exc:
                logger.warning("Embedding job for course %s skipped: %s", course_id, exc)

    def _process_resource(self, resource_id: int) -> None:
        with session_context() as session:
            resource = session.get(Resource, resource_id)
            if not resource:
                logger.warning("Resource %s missing during processing", resource_id)
                return

            try:
                resource.status = ResourceStatus.running
                resource.processing_stage = (
                    ProcessingStage.downloading
                    if resource.resource_type == ResourceType.video
                    else ProcessingStage.doc_parsing
                )
                resource.updated_at = datetime.utcnow()
                session.add(resource)
                session.commit()

                if resource.resource_type == ResourceType.video:
                    pipelines.process_video_resource(session, resource)
                else:
                    pipelines.process_document_resource(session, resource)

                resource.status = ResourceStatus.succeeded
                resource.processing_stage = ProcessingStage.sectioning
                resource.retry_count = 0
                resource.error_message = None
                resource.updated_at = datetime.utcnow()
                session.add(resource)
                session.commit()

                assembled = assembly.assemble_course_if_ready(session, resource.course_id)
                if assembled:
                    valid, issues = validation.validate_course_chunks(session, resource.course_id)
                    if not valid:
                        raise ValueError(
                            f"Chunk schema validation failed for course {resource.course_id}: {issues[:3]}"
                        )
                resource.processing_stage = ProcessingStage.done
                session.add(resource)
                session.commit()
            except Exception as exc:  # pragma: no cover - debug logging
                logger.exception("Resource %s failed: %s", resource_id, exc)
                resource.status = ResourceStatus.failed
                resource.error_message = str(exc)
                resource.retry_count += 1
                resource.updated_at = datetime.utcnow()
                session.add(resource)
                session.commit()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.worker.join(timeout=1)


processor = ResourceProcessor()
