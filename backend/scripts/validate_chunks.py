#!/usr/bin/env python3
"""
Validate generated chunks against Ready-to-Embed schema.

Usage:
    python backend/scripts/validate_chunks.py --course-id 1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable

from sqlalchemy import func
from sqlmodel import Session, select

from app.database import engine, init_db
from app.models import Chunk
from app.services import validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate chunk schema.")
    parser.add_argument("--course-id", type=int, required=False, help="Course ID to validate")
    args = parser.parse_args()

    init_db()

    with Session(engine) as session:
        if args.course_id:
            ok, errors = validation.validate_course_chunks(session, args.course_id)
            count = session.exec(
                select(func.count(Chunk.id)).where(Chunk.course_id == args.course_id)
            ).one()
        else:
            ok, errors = validation.validate_all_chunks(session)
            count = session.exec(select(func.count(Chunk.id))).one()

    if not ok:
        print(json.dumps({"status": "failed", "issues": errors}, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    print(json.dumps({"status": "ok", "count": count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
