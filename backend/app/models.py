from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship
from sqlmodel import Column, Field, Relationship, SQLModel


class ResourceType(str, Enum):
    video = "video"
    ppt = "ppt"
    pdf = "pdf"
    text = "text"
    markdown = "markdown"


class ResourceStatus(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ProcessingStage(str, Enum):
    waiting = "waiting"
    downloading = "downloading"
    audio_extracting = "audio_extracting"
    asr = "asr"
    doc_parsing = "doc_parsing"
    contentpiece_build = "contentpiece_build"
    sectioning = "sectioning"
    chunking = "chunking"
    done = "done"


class EmbeddingStatus(str, Enum):
    not_started = "not_started"
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Course(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    meta: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False, default={})
    )
    embedding_status: EmbeddingStatus = Field(default=EmbeddingStatus.not_started)
    embedding_progress: float = Field(default=0.0)
    embedding_error: Optional[str] = None

    lectures: List["Lecture"] = Relationship(back_populates="course")


class Lecture(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    title: Optional[str] = None
    order_index: int = Field(default=1)
    description: Optional[str] = None
    meta: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False, default={})
    )

    course: Optional["Course"] = Relationship(back_populates="lectures")
    resources: List["Resource"] = Relationship(back_populates="lecture")
    sections: List["Section"] = Relationship(back_populates="lecture")


class Resource(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    lecture_id: Optional[int] = Field(default=None, foreign_key="lecture.id", index=True)
    resource_type: ResourceType
    display_name: Optional[str] = None
    source_url: Optional[str] = None
    original_filename: Optional[str] = None
    status: ResourceStatus = Field(default=ResourceStatus.pending)
    processing_stage: ProcessingStage = Field(default=ProcessingStage.waiting)
    retry_count: int = Field(default=0)
    error_message: Optional[str] = None
    meta: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False, default={})
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    course: Optional[Course] = Relationship()
    lecture: Optional[Lecture] = Relationship(back_populates="resources")
    content_pieces: List["ContentPiece"] = Relationship(back_populates="resource")


class ContentSourceType(str, Enum):
    transcript = "transcript"
    slide = "slide"
    pdf = "pdf"
    text = "text"
    markdown = "markdown"


class ContentPiece(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    lecture_id: Optional[int] = Field(default=None, foreign_key="lecture.id", index=True)
    resource_id: int = Field(foreign_key="resource.id", index=True)
    section_id: Optional[int] = Field(default=None, foreign_key="section.id", index=True)
    source_type: ContentSourceType
    text: str
    language: Optional[str] = Field(default="zh")
    raw_start_time: Optional[float] = None
    raw_end_time: Optional[float] = None
    page_number: Optional[int] = None
    order_in_resource: int = Field(default=0)
    meta: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False, default={})
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    resource: Optional[Resource] = Relationship(back_populates="content_pieces")
    section: Optional["Section"] = Relationship(back_populates="content_pieces")


class Section(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    lecture_id: int = Field(foreign_key="lecture.id", index=True)
    title: str
    summary: Optional[str] = None
    order_in_lecture: int = Field(default=1)
    approx_start_time: Optional[float] = None
    approx_end_time: Optional[float] = None
    meta: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False, default={})
    )

    lecture: Optional[Lecture] = Relationship(back_populates="sections")
    content_pieces: List[ContentPiece] = Relationship(back_populates="section")
    chunks: List["Chunk"] = Relationship(back_populates="section")


class Chunk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    lecture_id: int = Field(foreign_key="lecture.id", index=True)
    section_id: int = Field(foreign_key="section.id", index=True)
    text: str
    language: str = Field(default="zh")
    source_type: str = Field(default="transcript")
    source_ref: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default={})
    )
    order_in_section: int = Field(default=1)
    tokens_estimate: int = Field(default=0)
    meta: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False, default={})
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    section: Optional[Section] = Relationship(back_populates="chunks")
