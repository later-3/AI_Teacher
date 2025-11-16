from __future__ import annotations

import logging
from time import perf_counter
from typing import Iterable, List

import torch
import torch.nn.functional as F

from ...config import get_settings
from .loader import load_embedding_components

logger = logging.getLogger(__name__)
settings = get_settings()


def _chunk(items: List[str], size: int) -> Iterable[List[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def embed_texts(texts: List[str]) -> List[List[float]]:
    """将文本批量转换为向量，自动按 batch 切分。"""
    if not texts:
        return []

    cleaned = [text or "" for text in texts]
    tokenizer, model, device = load_embedding_components()
    max_batch = settings.embedding_batch_size
    vectors: List[List[float]] = []
    start = perf_counter()

    for batch in _chunk(cleaned, max_batch):
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=settings.embedding_max_tokens,
            return_tensors="pt",
        )
        encoded = {k: v.to(device) for k, v in encoded.items()}
        with torch.no_grad():
            outputs = model(**encoded)

        if hasattr(outputs, "pooler_output") and outputs.pooler_output is not None:
            embeddings = outputs.pooler_output
        else:
            last_hidden = outputs.last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1)
            summed = (last_hidden * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1e-9)
            embeddings = summed / counts

        embeddings = F.normalize(embeddings, p=2, dim=1)
        vectors.extend(embeddings.cpu().tolist())

    elapsed = (perf_counter() - start) * 1000
    logger.info("Embedded %s texts in %.2f ms", len(texts), elapsed)
    return vectors
