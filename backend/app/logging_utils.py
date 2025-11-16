import logging
from time import perf_counter
from typing import Any, Dict, Optional

logger = logging.getLogger("ai_teacher")


def log_event(resource_id: int, stage: str, message: str, **extra: Any) -> None:
    payload: Dict[str, Any] = {"resource_id": resource_id, "stage": stage, "message": message}
    payload.update(extra)
    logger.info(payload)


class StageTimer:
    """Context manager to measure elapsed time for a processing stage."""

    def __init__(self, resource_id: int, stage: str, message: str) -> None:
        self.resource_id = resource_id
        self.stage = stage
        self.message = message
        self._start: Optional[float] = None

    def __enter__(self) -> "StageTimer":  # pragma: no cover - trivial
        self._start = perf_counter()
        log_event(self.resource_id, self.stage, f"{self.message} - start")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - trivial
        elapsed = None
        if self._start is not None:
            elapsed = round((perf_counter() - self._start) * 1000, 2)
        status = "failed" if exc else "done"
        log_event(
            self.resource_id,
            self.stage,
            f"{self.message} - {status}",
            elapsed_ms=elapsed,
            error=str(exc) if exc else None,
        )
