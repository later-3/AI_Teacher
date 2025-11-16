from fastapi import APIRouter

from .admin import router as admin_router
from .routes import router as api_router

router = APIRouter()
router.include_router(api_router)
router.include_router(admin_router)

__all__ = ["router"]
