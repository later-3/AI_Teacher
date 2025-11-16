import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import select

from .. import schemas
from ..database import get_session
from ..models import Chunk, Course, EmbeddingStatus, Resource, ResourceType, Section
from ..services import create_course, create_resource, processor, storage
from ..services.vectorstore import VectorStoreError, count_course_collection

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


def _get_vector_count(course_id: int) -> Optional[int]:
    try:
        return count_course_collection(course_id)
    except VectorStoreError as exc:
        logger.warning("Failed to fetch vector count for course %s: %s", course_id, exc)
        return None


@router.get("/courses")
def list_courses(request: Request, session=Depends(get_session)):
    courses = session.exec(select(Course).order_by(Course.created_at.desc())).all()
    course_stats = []
    for course in courses:
        resource_count = session.exec(
            select(func.count(Resource.id)).where(Resource.course_id == course.id)
        ).one()
        section_count = session.exec(
            select(func.count(Section.id)).where(Section.course_id == course.id)
        ).one()
        vector_count = _get_vector_count(course.id)
        course_stats.append(
            {
                "course": course,
                "resource_count": resource_count,
                "section_count": section_count,
                "vector_count": vector_count,
            }
        )
    return templates.TemplateResponse(
        "admin/courses.html",
        {
            "request": request,
            "course_stats": course_stats,
        },
    )


@router.post("/courses")
def create_course_from_form(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    session=Depends(get_session),
):
    payload = schemas.CourseCreate(name=name, description=description or None)
    create_course(session, payload)
    return RedirectResponse(request.url_for("list_courses"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/courses/{course_id}")
def course_detail(course_id: int, request: Request, session=Depends(get_session)):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    resources = session.exec(
        select(Resource).where(Resource.course_id == course_id).order_by(Resource.created_at.desc())
    ).all()
    sections = session.exec(
        select(Section).where(Section.course_id == course_id).order_by(Section.order_in_lecture)
    ).all()
    chunks = session.exec(
        select(Chunk)
        .where(Chunk.course_id == course_id)
        .order_by(Chunk.section_id, Chunk.order_in_section)
        .limit(100)
    ).all()

    vector_count = _get_vector_count(course_id)
    embedding_busy = course.embedding_status in {EmbeddingStatus.pending, EmbeddingStatus.running}

    return templates.TemplateResponse(
        "admin/course_detail.html",
        {
            "request": request,
            "course": course,
            "resources": resources,
            "sections": sections,
            "chunks": chunks,
            "resource_types": list(ResourceType),
            "vector_count": vector_count,
            "embedding_busy": embedding_busy,
        },
    )


@router.post("/courses/{course_id}/resource-url")
def add_resource_by_url(
    course_id: int,
    request: Request,
    display_name: str = Form(...),
    source_url: str = Form(...),
    resource_type: ResourceType = Form(ResourceType.video),
    session=Depends(get_session),
):
    payload = schemas.ResourceCreate(
        course_id=course_id,
        resource_type=resource_type,
        display_name=display_name,
        source_url=source_url,
    )
    resource = create_resource(session, payload)
    processor.enqueue_resource(resource.id)
    return RedirectResponse(
        request.url_for("course_detail", course_id=course_id), status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/courses/{course_id}/trigger-embedding")
def trigger_course_embedding_admin(course_id: int, request: Request, session=Depends(get_session)):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    if course.embedding_status in {EmbeddingStatus.pending, EmbeddingStatus.running}:
        status_flag = "busy"
    else:
        processor.enqueue_course_embedding(course_id)
        status_flag = "enqueued"
    redirect_url = str(request.url_for("course_detail", course_id=course_id))
    redirect_url = f"{redirect_url}?embedding={status_flag}"
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/courses/{course_id}/resource-upload")
async def add_resource_by_upload(
    course_id: int,
    request: Request,
    display_name: str = Form(...),
    resource_type: ResourceType = Form(ResourceType.pdf),
    file: UploadFile = File(...),
    session=Depends(get_session),
):
    if resource_type == ResourceType.video:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use URL upload for video.")

    payload = schemas.ResourceCreate(
        course_id=course_id,
        resource_type=resource_type,
        display_name=display_name or file.filename,
        original_filename=file.filename,
    )
    resource = create_resource(session, payload)
    saved_path = storage.save_uploaded_file(resource.id, file)
    resource.meta["local_path"] = str(saved_path)
    session.add(resource)
    session.commit()
    processor.enqueue_resource(resource.id)
    return RedirectResponse(
        request.url_for("course_detail", course_id=course_id), status_code=status.HTTP_303_SEE_OTHER
    )
