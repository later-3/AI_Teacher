from fastapi import Header, HTTPException, status

from ..config import get_settings


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    """确保内部 API 只被信任方调用。"""
    settings = get_settings()
    if not settings.internal_api_token:
        return
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")
