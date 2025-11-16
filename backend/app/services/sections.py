from fastapi import HTTPException, status
from sqlmodel import Session

from .. import schemas
from ..models import Section


def update_section(session: Session, section_id: int, payload: schemas.SectionUpdate) -> Section:
    section = session.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")

    if payload.title is not None:
        section.title = payload.title
    if payload.summary is not None:
        section.summary = payload.summary
    session.add(section)
    session.commit()
    session.refresh(section)
    return section
