from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter, sleep
from typing import Iterable, List, Sequence

from sqlmodel import Session, select

from ..models import Chunk, Course, EmbeddingStatus
from .embedding import embed_texts
from .vectorstore import VectorStoreError, VectorStoreItem, upsert_chunks

logger = logging.getLogger(__name__)

MAX_EMBED_RETRIES = 3


def _chunk_batches(items: Sequence[Chunk], size: int) -> Iterable[Sequence[Chunk]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def run_course_embedding(session: Session, course_id: int, batch_size: int) -> None:
    """Embed all chunks for a course and push them to the vector store."""
    course = session.get(Course, course_id)
    if not course:
        raise ValueError(f"Course {course_id} not found")

    chunks: List[Chunk] = session.exec(
        select(Chunk)
        .where(Chunk.course_id == course_id)
        .order_by(Chunk.section_id, Chunk.order_in_section, Chunk.id)
    ).all()
    if not chunks:
        _mark_failed(session, course, "No chunks available for embedding")
        return

    logger.info("Starting embedding pipeline for course %s with %s chunks", course_id, len(chunks))
    _mark_running(session, course)

    total = len(chunks)
    processed = 0
    success_vectors = 0
    batches = 0
    try:
        for batch in _chunk_batches(chunks, batch_size):
            batches += 1
            texts = [chunk.text or "" for chunk in batch]
            batch_start = perf_counter()
            vectors = _embed_with_retry(texts)
            embed_elapsed = (perf_counter() - batch_start) * 1000
            logger.info(
                "Embedded batch %s for course %s with %s chunks in %.2f ms",
                batches,
                course_id,
                len(batch),
                embed_elapsed,
            )
            payload = []
            for chunk_obj, vector in zip(batch, vectors):
                if chunk_obj.id is None:
                    continue
                metadata = {
                    "course_id": chunk_obj.course_id,
                    "lecture_id": chunk_obj.lecture_id,
                    "section_id": chunk_obj.section_id,
                    "source_type": chunk_obj.source_type,
                }
                metadata = {k: v for k, v in metadata.items() if v is not None}
                payload.append(
                    VectorStoreItem(
                        chunk_id=chunk_obj.id,
                        text=chunk_obj.text,
                        vector=vector,
                        metadata=metadata,
                    )
                )
            upsert_chunks(course_id, payload)
            processed += len(batch)
            success_vectors += len(payload)
            _update_progress(session, course, processed, total)
            logger.info(
                "Finished batch %s for course %s (%s/%s chunks, %.2f%%)",
                batches,
                course_id,
                processed,
                total,
                course.embedding_progress,
            )
    except VectorStoreError as exc:
        logger.exception("Embedding pipeline for course %s failed due to vector store error: %s", course_id, exc)
        session.rollback()
        _mark_failed(session, session.get(Course, course_id), f"vector_store_error: {exc}")
        return
    except Exception as exc:
        logger.exception("Embedding pipeline for course %s failed: %s", course_id, exc)
        session.rollback()
        _mark_failed(session, session.get(Course, course_id), str(exc))
        return

    _mark_done(session, course)
    logger.info(
        "Embedding pipeline for course %s finished: %s chunks embedded across %s batches",
        course_id,
        success_vectors,
        batches,
    )


def _mark_running(session: Session, course: Course) -> None:
    course.embedding_status = EmbeddingStatus.running
    course.embedding_progress = 0.0
    course.embedding_error = None
    course.updated_at = datetime.utcnow()
    session.add(course)
    session.commit()


def _update_progress(session: Session, course: Course, processed: int, total: int) -> None:
    progress = 100.0 if total == 0 else round(processed / total * 100, 2)
    course.embedding_progress = min(progress, 100.0)
    course.updated_at = datetime.utcnow()
    session.add(course)
    session.commit()


def _mark_done(session: Session, course: Course) -> None:
    course.embedding_status = EmbeddingStatus.done
    course.embedding_progress = 100.0
    course.embedding_error = None
    course.updated_at = datetime.utcnow()
    session.add(course)
    session.commit()


def _mark_failed(session: Session, course: Course | None, error: str) -> None:
    if not course:
        return
    course.embedding_status = EmbeddingStatus.failed
    course.embedding_progress = 0.0
    course.embedding_error = error
    course.updated_at = datetime.utcnow()
    session.add(course)
    session.commit()


def _embed_with_retry(texts: List[str]) -> List[List[float]]:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_EMBED_RETRIES + 1):
        try:
            return embed_texts(texts)
        except Exception as exc:  # pragma: no cover - defensive logging
            last_exc = exc
            logger.warning(
                "Embedding batch failed attempt %s/%s: %s",
                attempt,
                MAX_EMBED_RETRIES,
                exc,
            )
            if attempt < MAX_EMBED_RETRIES:
                sleep(0.5)
    assert last_exc is not None
    raise RuntimeError("embedding_batch_failed") from last_exc
