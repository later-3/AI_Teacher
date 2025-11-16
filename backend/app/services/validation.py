from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from sqlmodel import Session, select

from ..models import Chunk

REQUIRED_FIELDS = [
    "chunk_id",
    "course_id",
    "lecture_id",
    "section_id",
    "text",
    "language",
    "source_type",
    "source_ref",
    "order_in_section",
    "tokens_estimate",
    "metadata",
]


def chunk_to_dict(chunk: Chunk) -> Dict[str, Any]:
    return {
        "chunk_id": chunk.id,
        "course_id": chunk.course_id,
        "lecture_id": chunk.lecture_id,
        "section_id": chunk.section_id,
        "text": chunk.text,
        "language": chunk.language,
        "source_type": chunk.source_type,
        "source_ref": chunk.source_ref,
        "order_in_section": chunk.order_in_section,
        "tokens_estimate": chunk.tokens_estimate,
        "metadata": chunk.meta,
    }


MIN_CHUNK_CHARS = 30


def validate_chunk_dict(chunk: Dict[str, Any]) -> Iterable[str]:
    for field in REQUIRED_FIELDS:
        if field not in chunk:
            yield f"missing field '{field}'"
        elif chunk[field] in (None, ""):
            yield f"field '{field}' is empty"

    source_ref = chunk.get("source_ref") or {}
    if not isinstance(source_ref, dict):
        yield "source_ref must be a dict"

    metadata = chunk.get("metadata", {})
    if not isinstance(metadata, dict):
        yield "metadata must be a dict"

    if not isinstance(chunk.get("tokens_estimate"), int):
        yield "tokens_estimate must be int"

    text_len = len(chunk.get("text", ""))
    if text_len < MIN_CHUNK_CHARS:
        yield f"text is too short (<{MIN_CHUNK_CHARS} chars)"
    if text_len > 3600:
        yield "text is too long (>3600 chars)"


def validate_course_chunks(session: Session, course_id: int) -> Tuple[bool, List[Dict[str, Any]]]:
    statement = select(Chunk).where(Chunk.course_id == course_id)
    chunks = session.exec(statement).all()
    errors: List[Dict[str, Any]] = []
    for chunk in chunks:
        issues = list(validate_chunk_dict(chunk_to_dict(chunk)))
        if issues:
            errors.append({"chunk_id": chunk.id, "errors": issues})
    return len(errors) == 0, errors


def validate_all_chunks(session: Session) -> Tuple[bool, List[Dict[str, Any]]]:
    chunks = session.exec(select(Chunk)).all()
    errors: List[Dict[str, Any]] = []
    for chunk in chunks:
        issues = list(validate_chunk_dict(chunk_to_dict(chunk)))
        if issues:
            errors.append({"chunk_id": chunk.id, "errors": issues})
    return len(errors) == 0, errors
