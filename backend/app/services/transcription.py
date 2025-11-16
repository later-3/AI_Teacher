from __future__ import annotations

from functools import lru_cache
from typing import Iterable, List, Tuple

from faster_whisper import WhisperModel

from ..config import get_settings


@lru_cache
def get_whisper_model() -> WhisperModel:
    settings = get_settings()
    return WhisperModel(
        settings.asr_model_size,
        device=settings.asr_device,
        compute_type=settings.asr_compute_type,
    )


def transcribe_audio(audio_path: str) -> Iterable[Tuple[float, float, str]]:
    model = get_whisper_model()
    segments, _ = model.transcribe(audio_path)
    for segment in segments:
        yield segment.start, segment.end, segment.text.strip()
