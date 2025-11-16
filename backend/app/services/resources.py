from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlmodel import Session, select

from .. import schemas
from ..models import (
    Course,
    Lecture,
    ProcessingStage,
    Resource,
    ResourceStatus,
    ResourceType,
)


def create_course(session: Session, payload: schemas.CourseCreate) -> Course:
    course = Course(
        name=payload.name,
        description=payload.description,
        created_by=payload.created_by,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _get_next_lecture_order(session: Session, course_id: int) -> int:
    result = session.exec(
        select(Lecture.order_index).where(Lecture.course_id == course_id).order_by(Lecture.order_index.desc())
    ).first()
    return (result or 0) + 1


def _ensure_default_lecture(session: Session, course_id: int, title: Optional[str] = None) -> Lecture:
    lecture = Lecture(
        course_id=course_id,
        title=title or "Lecture",
        order_index=_get_next_lecture_order(session, course_id),
    )
    session.add(lecture)
    session.flush()
    return lecture


def _bind_lecture_for_resource(session: Session, course_id: int, resource_type: ResourceType, display_name: Optional[str]) -> Lecture:
    if resource_type == ResourceType.video:
        title = display_name or f"Lecture {_get_next_lecture_order(session, course_id)}"
        return _ensure_default_lecture(session, course_id, title=title)

    lecture = session.exec(
        select(Lecture).where(Lecture.course_id == course_id).order_by(Lecture.order_index.desc())
    ).first()
    if lecture:
        return lecture
    return _ensure_default_lecture(session, course_id, title="Lecture 1 (Auto)")


def create_resource(session: Session, payload: schemas.ResourceCreate) -> Resource:
    course = session.get(Course, payload.course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    lecture = _bind_lecture_for_resource(session, course.id, payload.resource_type, payload.display_name)

    resource = Resource(
        course_id=course.id,
        lecture_id=lecture.id,
        resource_type=payload.resource_type,
        display_name=payload.display_name,
        source_url=payload.source_url,
        original_filename=payload.original_filename,
        status=ResourceStatus.pending,
        processing_stage=ProcessingStage.waiting,
    )

    session.add(resource)
    course.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(resource)
    return resource


def retry_resource(session: Session, resource_id: int) -> Resource:
    resource = session.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    if resource.status != ResourceStatus.failed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resource is not in failed state")

    resource.status = ResourceStatus.queued
    resource.processing_stage = ProcessingStage.waiting
    resource.retry_count = 0
    resource.error_message = None
    resource.updated_at = datetime.utcnow()
    session.add(resource)
    session.commit()
    session.refresh(resource)
    return resource
