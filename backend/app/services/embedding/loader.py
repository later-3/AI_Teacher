from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Tuple

import torch
from transformers import AutoModel, AutoTokenizer

from ...config import get_settings

logger = logging.getLogger(__name__)


def _resolve_model_source(model_path: Path, model_name: str) -> str:
    """Prefer本地路径，若目录不存在则使用模型名（自动从 HuggingFace/ModelScope 下载）。"""
    return str(model_path) if model_path.exists() else model_name


def _select_device(preference: str) -> str:
    """Return cuda if available, otherwise cpu; respect explicit overrides when feasible."""
    has_cuda = torch.cuda.is_available()
    normalized = (preference or "").lower()

    if normalized not in {"auto", "cpu", "cuda"}:
        logger.warning("Unknown embedding_device %s, falling back to auto", preference)
        normalized = "auto"

    if normalized == "auto":
        return "cuda" if has_cuda else "cpu"

    if normalized == "cuda":
        if has_cuda:
            return "cuda"
        logger.warning("embedding_device set to cuda but GPU unavailable; falling back to cpu")
        return "cpu"

    # Explicit CPU preference; still emit a hint if GPU exists to encourage optimal config.
    if has_cuda:
        logger.info("GPU detected but embedding_device forced to CPU")
    return "cpu"


@lru_cache
def load_embedding_components() -> Tuple[AutoTokenizer, AutoModel, str]:
    """加载 tokenizer + model，并返回使用的 device。"""
    settings = get_settings()
    source = _resolve_model_source(settings.embedding_model_path, settings.embedding_model_name)
    logger.info("Loading embedding model from %s", source)
    tokenizer = AutoTokenizer.from_pretrained(source, trust_remote_code=True)
    model = AutoModel.from_pretrained(source, trust_remote_code=True)

    device = _select_device(settings.embedding_device)
    logger.info("Embedding model moved to device: %s", device)
    model.to(device)
    model.eval()
    return tokenizer, model, device
