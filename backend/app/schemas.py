from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    Chunk,
    ContentPiece,
    ContentSourceType,
    Course,
    EmbeddingStatus,
    Lecture,
    ProcessingStage,
    Resource,
    ResourceStatus,
    ResourceType,
    Section,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CourseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None


class CourseRead(ORMModel):
    id: int
    name: str
    description: Optional[str]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    embedding_status: EmbeddingStatus
    embedding_progress: float
    embedding_error: Optional[str]

class LectureRead(ORMModel):
    id: int
    title: Optional[str]
    order_index: int

class SectionRead(ORMModel):
    id: int
    title: str
    summary: Optional[str]
    order_in_lecture: int
    approx_start_time: Optional[float]
    approx_end_time: Optional[float]
    metadata: dict = Field(alias="meta")


class SectionUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None


class CourseOutline(BaseModel):
    course: CourseRead
    lectures: List["LectureOutline"]


class LectureOutline(BaseModel):
    lecture: LectureRead
    sections: List[SectionRead]


class ResourceCreate(BaseModel):
    course_id: int
    resource_type: ResourceType
    display_name: Optional[str] = None
    source_url: Optional[str] = None
    original_filename: Optional[str] = None


class ResourceRead(ORMModel):
    id: int
    course_id: int
    lecture_id: Optional[int]
    resource_type: ResourceType
    display_name: Optional[str]
    source_url: Optional[str]
    status: ResourceStatus
    processing_stage: ProcessingStage
    retry_count: int
    error_message: Optional[str]
    metadata: dict = Field(alias="meta")
    created_at: datetime
    updated_at: datetime

class ResourceStatusUpdate(BaseModel):
    status: ResourceStatus
    processing_stage: ProcessingStage


class SectionSummary(BaseModel):
    section: SectionRead
    content_piece_count: int
    chunk_count: int


class EmbeddingRequest(BaseModel):
    texts: List[str]
    model: Optional[str] = None


class EmbeddingResponse(BaseModel):
    vectors: List[List[float]]


class EmbeddingStatusResponse(BaseModel):
    course_id: int
    status: EmbeddingStatus
    progress: float
    error: Optional[str]


class SearchFilters(BaseModel):
    section_id: Optional[int] = None
    lecture_id: Optional[int] = None
    source_type: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    filters: Optional[SearchFilters] = None


class SearchResult(BaseModel):
    chunk_id: int
    score: Optional[float] = None
    text: str
    metadata: dict


class SearchResponse(BaseModel):
    results: List[SearchResult]


class ChunkRead(ORMModel):
    id: int
    course_id: int
    lecture_id: int
    section_id: int
    text: str
    language: str
    source_type: str
    source_ref: dict
    order_in_section: int
    tokens_estimate: int
    metadata: dict = Field(alias="meta")
    created_at: datetime

class Pagination(BaseModel):
    total: int
    items: List[ChunkRead]
