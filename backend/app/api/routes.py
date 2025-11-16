import logging
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from .. import schemas
from ..config import PaginationParams, get_settings
from ..database import get_session
from ..models import Course, EmbeddingStatus, Resource, ResourceType
from ..services import (
    assemble_course_if_ready,
    build_course_outline,
    create_course,
    create_resource,
    embed_texts,
    fetch_course_chunks,
    processor,
    retry_resource,
    storage,
    update_section,
)
from ..services.vectorstore import VectorStoreError, search_course_chunks
from .deps import require_internal_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/courses", response_model=schemas.CourseRead, status_code=status.HTTP_201_CREATED)
def create_course_route(payload: schemas.CourseCreate, session=Depends(get_session)):
    course = create_course(session, payload)
    return schemas.CourseRead.model_validate(course)


@router.post("/resources", response_model=schemas.ResourceRead, status_code=status.HTTP_201_CREATED)
def create_resource_route(payload: schemas.ResourceCreate, session=Depends(get_session)):
    resource = create_resource(session, payload)
    processor.enqueue_resource(resource.id)
    return schemas.ResourceRead.model_validate(resource)


@router.post("/resources/upload", response_model=schemas.ResourceRead, status_code=status.HTTP_201_CREATED)
async def upload_resource_route(
    course_id: int = Form(...),
    resource_type: ResourceType = Form(...),
    file: UploadFile = File(...),
    session=Depends(get_session),
):
    if resource_type == ResourceType.video:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Video uploads not supported; use URL.")

    payload = schemas.ResourceCreate(
        course_id=course_id,
        resource_type=resource_type,
        display_name=file.filename,
        original_filename=file.filename,
    )
    resource = create_resource(session, payload)
    saved_path = storage.save_uploaded_file(resource.id, file)
    resource.meta["local_path"] = str(saved_path)
    session.add(resource)
    session.commit()
    session.refresh(resource)
    processor.enqueue_resource(resource.id)
    return schemas.ResourceRead.model_validate(resource)


@router.get("/resources/{resource_id}", response_model=schemas.ResourceRead)
def read_resource(resource_id: int, session=Depends(get_session)):
    resource = session.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return schemas.ResourceRead.model_validate(resource)


@router.post("/resources/{resource_id}/retry", response_model=schemas.ResourceRead)
def retry_resource_route(resource_id: int, session=Depends(get_session)):
    resource = retry_resource(session, resource_id)
    processor.enqueue_resource(resource.id)
    return schemas.ResourceRead.model_validate(resource)


@router.get("/courses/{course_id}/outline", response_model=schemas.CourseOutline)
def get_course_outline(course_id: int, session=Depends(get_session)):
    return build_course_outline(session, course_id)


@router.get("/courses/{course_id}/chunks", response_model=schemas.Pagination)
def list_course_chunks(
    course_id: int,
    pagination: PaginationParams = Depends(),
    session=Depends(get_session),
):
    total, items = fetch_course_chunks(session, course_id, pagination.limit, pagination.offset)
    return schemas.Pagination(
        total=total,
        items=[schemas.ChunkRead.model_validate(item) for item in items],
    )


@router.post("/courses/{course_id}/assemble", response_model=schemas.CourseOutline)
def trigger_course_assembly(course_id: int, session=Depends(get_session)):
    assembled = assemble_course_if_ready(session, course_id)
    if not assembled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course resources not ready for assembly",
        )
    return build_course_outline(session, course_id)


@router.patch("/sections/{section_id}", response_model=schemas.SectionRead)
def update_section_route(section_id: int, payload: schemas.SectionUpdate, session=Depends(get_session)):
    section = update_section(session, section_id, payload)
    return schemas.SectionRead.model_validate(section)
@router.post("/embed", response_model=schemas.EmbeddingResponse)
def embed_texts_route(
    payload: schemas.EmbeddingRequest,
    _: None = Depends(require_internal_token),
):
    settings = get_settings()
    if not payload.texts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="texts must not be empty")
    if len(payload.texts) > settings.embedding_batch_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many texts in one request (max {settings.embedding_batch_size})",
        )
    if payload.model and payload.model != settings.embedding_model_name:
        logger.warning("Client requested model %s but backend configured %s", payload.model, settings.embedding_model_name)
    start = perf_counter()
    vectors = embed_texts(payload.texts)
    elapsed = (perf_counter() - start) * 1000
    logger.info("Handled /embed request texts=%s in %.2f ms", len(payload.texts), elapsed)
    return schemas.EmbeddingResponse(vectors=vectors)


@router.post("/courses/{course_id}/embed", response_model=schemas.EmbeddingStatusResponse, status_code=status.HTTP_202_ACCEPTED)
def start_course_embedding(
    course_id: int,
    session=Depends(get_session),
    _: None = Depends(require_internal_token),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if course.embedding_status in {EmbeddingStatus.pending, EmbeddingStatus.running}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "embedding_already_running"},
        )
    processor.enqueue_course_embedding(course_id)
    session.refresh(course)
    return schemas.EmbeddingStatusResponse(
        course_id=course.id,
        status=course.embedding_status,
        progress=course.embedding_progress,
        error=course.embedding_error,
    )


@router.get("/courses/{course_id}/embedding_status", response_model=schemas.EmbeddingStatusResponse)
def get_course_embedding_status(course_id: int, session=Depends(get_session)):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return schemas.EmbeddingStatusResponse(
        course_id=course.id,
        status=course.embedding_status,
        progress=course.embedding_progress,
        error=course.embedding_error,
    )


@router.post(
    "/courses/{course_id}/search",
    response_model=schemas.SearchResponse,
)
def search_course_chunks_route(
    course_id: int,
    payload: schemas.SearchRequest,
    session=Depends(get_session),
    _: None = Depends(require_internal_token),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if course.embedding_status != EmbeddingStatus.done:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "embedding_not_ready"},
        )
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="query must not be empty")

    search_start = perf_counter()
    try:
        vectors = embed_texts([query])
    except Exception as exc:
        logger.exception("Embedding service unavailable during search for course %s: %s", course_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "embedding_service_unavailable", "message": "embedding service error"},
        ) from exc

    if not vectors:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="embedding_service_unavailable")

    filter_dict = payload.filters.model_dump(exclude_none=True) if payload.filters else {}
    try:
        results = search_course_chunks(course_id, vectors[0], payload.top_k, filter_dict)
    except VectorStoreError as exc:
        logger.exception("Vector store error during search for course %s: %s", course_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "vector_store_error", "message": "vector store unavailable"},
        ) from exc
    elapsed_ms = (perf_counter() - search_start) * 1000
    logger.info(
        "Search course %s query='%s' top_k=%s filters=%s hits=%s took %.2f ms",
        course_id,
        query[:80],
        payload.top_k,
        filter_dict or {},
        len(results),
        elapsed_ms,
    )
    return schemas.SearchResponse(
        results=[
            schemas.SearchResult(
                chunk_id=item["chunk_id"],
                score=item.get("score"),
                text=item["text"],
                metadata=item.get("metadata", {}),
            )
            for item in results
        ]
    )
