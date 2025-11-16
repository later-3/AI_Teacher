from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session, delete

from ..logging_utils import StageTimer
from ..models import (
    ContentPiece,
    ContentSourceType,
    ProcessingStage,
    Resource,
    ResourceType,
)
from . import documents, storage, transcription

logger = logging.getLogger(__name__)


def _clear_existing_content(session: Session, resource_id: int) -> None:
    session.exec(delete(ContentPiece).where(ContentPiece.resource_id == resource_id))
    session.commit()


def process_video_resource(session: Session, resource: Resource) -> None:
    """Download, transcribe, and persist ContentPieces for a video resource."""
    if not resource.source_url:
        raise ValueError("Video resource missing source_url")

    logger.info("Processing video resource %s", resource.id)
    _clear_existing_content(session, resource.id)

    with StageTimer(resource.id, "downloading", "Download audio"):
        resource.processing_stage = ProcessingStage.downloading
        session.commit()
        audio_source = storage.download_audio_from_url(resource.id, resource.source_url)
        resource.meta["download_path"] = str(audio_source)
        session.commit()

    with StageTimer(resource.id, "audio_extracting", "Convert to wav"):
        resource.processing_stage = ProcessingStage.audio_extracting
        session.commit()
        wav_path = storage.convert_to_wav(resource.id, audio_source)
        resource.meta["audio_path"] = str(wav_path)
        session.commit()

    with StageTimer(resource.id, "asr", "Run ASR"):
        resource.processing_stage = ProcessingStage.asr
        session.commit()
        segments = list(transcription.transcribe_audio(str(wav_path)))

    with StageTimer(resource.id, "contentpiece_build", "Persist transcript segments"):
        resource.processing_stage = ProcessingStage.contentpiece_build
        session.commit()
        for idx, (start_time, end_time, text) in enumerate(segments):
            clean_text = text.strip()
            if not clean_text:
                continue
            piece = ContentPiece(
                course_id=resource.course_id,
                lecture_id=resource.lecture_id,
                resource_id=resource.id,
                source_type=ContentSourceType.transcript,
                text=clean_text,
                language="zh",
                raw_start_time=float(start_time),
                raw_end_time=float(end_time),
                order_in_resource=idx,
                metadata={"duration": end_time - start_time},
            )
            session.add(piece)
        session.commit()


def process_document_resource(session: Session, resource: Resource) -> None:
    """Parse PPT/PDF/Text resources into ContentPieces."""
    logger.info("Processing document resource %s", resource.id)
    _clear_existing_content(session, resource.id)

    resource.processing_stage = ProcessingStage.doc_parsing
    session.commit()

    local_path_str = resource.meta.get("local_path") or resource.source_url
    if not local_path_str:
        raise ValueError("Document resource missing local path")
    local_path = Path(local_path_str)
    if not local_path.exists():
        raise ValueError(f"Document path does not exist: {local_path}")

    if resource.resource_type == ResourceType.ppt:
        iterator = documents.parse_pptx(local_path)
        source_type = ContentSourceType.slide
    elif resource.resource_type == ResourceType.pdf:
        iterator = documents.parse_pdf(local_path)
        source_type = ContentSourceType.pdf
    elif resource.resource_type == ResourceType.markdown:
        iterator = documents.parse_markdown_file(local_path)
        source_type = ContentSourceType.markdown
    else:
        iterator = documents.parse_text_file(local_path)
        source_type = ContentSourceType.text

    resource.processing_stage = ProcessingStage.contentpiece_build
    session.commit()

    for order, (page_number, text) in enumerate(iterator):
        piece = ContentPiece(
            course_id=resource.course_id,
            lecture_id=resource.lecture_id,
            resource_id=resource.id,
            source_type=source_type,
            text=text,
            language="zh",
            page_number=page_number,
            order_in_resource=order,
        )
        session.add(piece)
    session.commit()
