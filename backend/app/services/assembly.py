from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, delete, select

from .. import schemas
from .validation import MIN_CHUNK_CHARS
from ..models import (
    Chunk,
    ContentPiece,
    ContentSourceType,
    Course,
    Lecture,
    Resource,
    ResourceStatus,
    Section,
)


def assemble_course_if_ready(session: Session, course_id: int) -> bool:
    """Build sections & chunks when all course resources are succeeded."""
    statuses = session.exec(
        select(Resource.status).where(Resource.course_id == course_id)
    ).all()
    if not statuses or any(status != ResourceStatus.succeeded for status in statuses):
        return False
    _assemble_course_structures(session, course_id)
    return True


def _assemble_course_structures(session: Session, course_id: int) -> None:
    content_pieces = session.exec(select(ContentPiece).where(ContentPiece.course_id == course_id)).all()
    for piece in content_pieces:
        piece.section_id = None
    session.exec(delete(Chunk).where(Chunk.course_id == course_id))
    session.exec(delete(Section).where(Section.course_id == course_id))
    session.commit()

    lectures = session.exec(
        select(Lecture).where(Lecture.course_id == course_id).order_by(Lecture.order_index)
    ).all()

    for lecture in lectures:
        lecture_pieces = [
            piece
            for piece in content_pieces
            if piece.lecture_id == lecture.id and piece.text.strip()
        ]
        lecture_pieces.sort(key=lambda p: (p.order_in_resource, p.id or 0))
        if not lecture_pieces:
            continue
        section_groups = _split_into_sections(lecture_pieces)
        for order_index, group in enumerate(section_groups, start=1):
            section_text = " ".join(piece.text.strip() for piece in group).strip()
            if not section_text:
                continue
            summary = (section_text[:200] + "…") if len(section_text) > 200 else section_text
            approx_start = min(
                (piece.raw_start_time for piece in group if piece.raw_start_time is not None),
                default=None,
            )
            approx_end = max(
                (piece.raw_end_time for piece in group if piece.raw_end_time is not None),
                default=None,
            )
            metadata = {
                "content_piece_count": len(group),
                "total_chars": len(section_text),
            }
            section = Section(
                course_id=course_id,
                lecture_id=lecture.id,
                title=f"{lecture.title or 'Lecture'} - Section {order_index}",
                summary=summary,
                order_in_lecture=order_index,
                approx_start_time=approx_start,
                approx_end_time=approx_end,
                metadata=metadata,
            )
            session.add(section)
            session.flush()
            for piece in group:
                piece.section_id = section.id
            _build_chunks_for_section(session, section, group)
    session.commit()


def _split_into_sections(
    content_pieces: Sequence[ContentPiece],
    min_chars: int = 250,
    max_chars: int = 800,
) -> List[List[ContentPiece]]:
    sections: List[List[ContentPiece]] = []
    current: List[ContentPiece] = []
    char_count = 0

    for piece in content_pieces:
        text_len = len(piece.text)
        if char_count >= max_chars and current:
            sections.append(current)
            current = []
            char_count = 0

        current.append(piece)
        char_count += text_len

        if char_count >= min_chars:
            sections.append(current)
            current = []
            char_count = 0

    if current:
        sections.append(current)
    return sections


def _build_chunks_for_section(session: Session, section: Section, pieces: Sequence[ContentPiece]) -> None:
    min_chars, max_chars = 200, 500
    current_text: List[str] = []
    chunk_piece_ids: List[int] = []
    chunk_time_ranges: List[Tuple[float, float]] = []
    chunk_pages: List[int] = []
    chunk_sources: List[str] = []
    order = 1
    last_chunk: Optional[Chunk] = None

    def flush_chunk() -> None:
        nonlocal current_text, chunk_piece_ids, chunk_time_ranges, chunk_pages, chunk_sources, order, last_chunk
        if not current_text:
            return
        text = " ".join(current_text).strip()
        if not text:
            return
        first_piece = next((p for p in pieces if p.id in chunk_piece_ids), pieces[0])
        source_ref = {
            "resource_id": first_piece.resource_id if first_piece else None,
            "start_time": chunk_time_ranges[0][0] if chunk_time_ranges else None,
            "end_time": chunk_time_ranges[-1][1] if chunk_time_ranges else None,
            "page_number": chunk_pages[0] if chunk_pages else None,
        }
        metadata = {
            "source_piece_ids": chunk_piece_ids.copy(),
            "time_ranges": chunk_time_ranges.copy(),
            "page_numbers": chunk_pages.copy(),
            "source_types": chunk_sources.copy(),
        }
        if len(text) < MIN_CHUNK_CHARS:
            if last_chunk is not None:
                last_chunk.text = f"{last_chunk.text} {text}".strip()
                last_chunk.tokens_estimate = max(1, math.ceil(len(last_chunk.text) / 4))
                last_meta = last_chunk.meta
                last_meta.setdefault("source_piece_ids", []).extend(chunk_piece_ids.copy())
                last_meta.setdefault("time_ranges", []).extend(chunk_time_ranges.copy())
                last_meta.setdefault("page_numbers", []).extend(chunk_pages.copy())
                last_meta.setdefault("source_types", []).extend(chunk_sources.copy())
                if chunk_time_ranges:
                    last_chunk.source_ref["end_time"] = chunk_time_ranges[-1][1]
                session.add(last_chunk)
            # If no previous chunk, drop this short fragment.
            current_text = []
            chunk_piece_ids = []
            chunk_time_ranges = []
            chunk_pages = []
            chunk_sources = []
            return
        else:
            chunk = Chunk(
                course_id=section.course_id,
                lecture_id=section.lecture_id,
                section_id=section.id,
                text=text,
                language="zh",
                source_type="mixed"
                if len(set(chunk_sources)) > 1
                else (chunk_sources[0] if chunk_sources else "unknown"),
                source_ref=source_ref,
                order_in_section=order,
                tokens_estimate=max(1, math.ceil(len(text) / 4)),
                meta=metadata,
            )
            session.add(chunk)
            last_chunk = chunk
            order += 1
        current_text = []
        chunk_piece_ids = []
        chunk_time_ranges = []
        chunk_pages = []
        chunk_sources = []

    char_count = 0
    for piece in pieces:
        clean_text = piece.text.strip()
        if not clean_text:
            continue
        current_text.append(clean_text)
        if piece.id:
            chunk_piece_ids.append(piece.id)
        if piece.raw_start_time is not None and piece.raw_end_time is not None:
            chunk_time_ranges.append((piece.raw_start_time, piece.raw_end_time))
        if piece.page_number is not None:
            chunk_pages.append(piece.page_number)
        chunk_sources.append(piece.source_type.value)

        char_count += len(clean_text)
        if char_count >= max_chars:
            flush_chunk()
            char_count = 0
        elif char_count >= min_chars:
            flush_chunk()
            char_count = 0

    flush_chunk()
    session.flush()


def build_course_outline(session: Session, course_id: int) -> schemas.CourseOutline:
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    lectures = session.exec(
        select(Lecture).where(Lecture.course_id == course_id).order_by(Lecture.order_index)
    ).all()

    lecture_outlines: List[schemas.LectureOutline] = []
    for lecture in lectures:
        sections = session.exec(
            select(Section)
            .where(Section.lecture_id == lecture.id)
            .order_by(Section.order_in_lecture)
        ).all()
        lecture_outlines.append(
            schemas.LectureOutline(
                lecture=schemas.LectureRead.model_validate(lecture),
                sections=[schemas.SectionRead.model_validate(section) for section in sections],
            )
        )

    return schemas.CourseOutline(
        course=schemas.CourseRead.model_validate(course),
        lectures=lecture_outlines,
    )


def fetch_course_chunks(
    session: Session,
    course_id: int,
    limit: int,
    offset: int,
) -> Tuple[int, List[Chunk]]:
    total = session.exec(select(func.count(Chunk.id)).where(Chunk.course_id == course_id)).one()
    items = session.exec(
        select(Chunk)
        .where(Chunk.course_id == course_id)
        .order_by(Chunk.section_id, Chunk.order_in_section)
        .offset(offset)
        .limit(limit)
    ).all()
    return total, items
