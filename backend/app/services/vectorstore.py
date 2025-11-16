from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Optional

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@lru_cache(maxsize=1)
def get_chroma_client() -> PersistentClient:
    """Return a cached persistent Chroma client."""
    return PersistentClient(path=str(settings.chroma_db_dir))


def _collection_name(course_id: int) -> str:
    return f"course_{course_id}"


class VectorStoreError(RuntimeError):
    """Raised when Chroma client operations fail."""


def get_course_collection(course_id: int) -> Collection:
    """Fetch (or create) the Chroma collection for a course."""
    client = get_chroma_client()
    name = _collection_name(course_id)
    try:
        return client.get_or_create_collection(name=name)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to initialize collection %s: %s", name, exc)
        raise VectorStoreError(f"collection_init_failed:{name}") from exc


def list_course_collections() -> List[str]:
    """List all course collections (debug/inspection helper)."""
    client = get_chroma_client()
    try:
        return [collection.name for collection in client.list_collections()]
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to list Chroma collections: %s", exc)
        raise VectorStoreError("list_collections_failed") from exc


def delete_course_collection(course_id: int) -> bool:
    """Delete the collection for a course; return True if removed."""
    client = get_chroma_client()
    name = _collection_name(course_id)
    try:
        client.delete_collection(name=name)
        logger.info("Deleted Chroma collection %s", name)
        return True
    except ValueError:
        logger.info("Chroma collection %s not found when deleting", name)
        return False
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to delete collection %s: %s", name, exc)
        raise VectorStoreError(f"delete_collection_failed:{name}") from exc


def count_course_collection(course_id: int) -> int:
    """Return item count for a course collection."""
    client = get_chroma_client()
    name = _collection_name(course_id)
    try:
        collection = client.get_collection(name=name)
    except ValueError:
        return 0
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to fetch collection %s for counting: %s", name, exc)
        raise VectorStoreError("collection_fetch_failed") from exc

    try:
        return collection.count()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to count collection %s: %s", name, exc)
        raise VectorStoreError("collection_count_failed") from exc


@dataclass
class VectorStoreItem:
    chunk_id: int
    text: str
    vector: List[float]
    metadata: Dict[str, int | str]


def upsert_chunks(course_id: int, items: Iterable[VectorStoreItem]) -> int:
    """Upsert chunk vectors into the course collection."""
    batch = list(items)
    if not batch:
        return 0

    collection = get_course_collection(course_id)
    ids = [str(item.chunk_id) for item in batch]
    embeddings = [item.vector for item in batch]
    documents = [item.text for item in batch]
    metadatas = [item.metadata for item in batch]
    try:
        collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to upsert %s vectors into %s: %s", len(batch), _collection_name(course_id), exc)
        raise VectorStoreError("upsert_failed") from exc
    logger.info("Upserted %s chunk vectors into collection %s", len(batch), _collection_name(course_id))
    return len(batch)


def search_course_chunks(
    course_id: int,
    query_vector: List[float],
    top_k: int,
    filters: Optional[Dict[str, int | str]] = None,
) -> List[Dict[str, object]]:
    """Query a course collection and return structured results."""
    collection = get_course_collection(course_id)
    try:
        if collection.count() == 0:
            return []
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to count collection %s before query: %s", _collection_name(course_id), exc)
        raise VectorStoreError("count_failed_before_query") from exc

    where = {k: v for k, v in (filters or {}).items() if v is not None}
    try:
        response = collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where or None,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to query collection %s: %s", _collection_name(course_id), exc)
        raise VectorStoreError("query_failed") from exc
    ids = response.get("ids", [[]])[0]
    documents = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    distances = response.get("distances") or response.get("similarities")
    distance_row = distances[0] if distances else [None] * len(ids)

    results: List[Dict[str, object]] = []
    for chunk_id, text, metadata, distance in zip(ids, documents, metadatas, distance_row):
        score = None
        if distance is not None:
            score = 1 - float(distance)
        results.append(
            {
                "chunk_id": int(chunk_id),
                "text": text,
                "metadata": metadata or {},
                "score": score,
            }
        )
    return results
