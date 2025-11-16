#!/usr/bin/env python3
"""
Simple utility to ensure阶段二新增字段已经添加到 Course 表。

目前项目使用 sqlite，通过 SQLModel.create_all 无法自动为 existing 表补列，
因此提供一个幂等脚本来执行 ALTER TABLE。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.app.config import get_settings


def _ensure_column(cursor: sqlite3.Cursor, column: str, ddl: str) -> None:
    cursor.execute("PRAGMA table_info(course)")
    existing = {row[1] for row in cursor.fetchall()}
    if column in existing:
        return
    cursor.execute(f"ALTER TABLE course ADD COLUMN {ddl}")


def main() -> None:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite:///"):
        raise RuntimeError("当前迁移脚本仅支持 sqlite 数据库")

    db_path = Path(settings.database_url.replace("sqlite:///", ""))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        _ensure_column(cursor, "embedding_status", "embedding_status TEXT DEFAULT 'not_started'")
        _ensure_column(cursor, "embedding_progress", "embedding_progress REAL DEFAULT 0")
        _ensure_column(cursor, "embedding_error", "embedding_error TEXT")
        conn.commit()


if __name__ == "__main__":
    main()
