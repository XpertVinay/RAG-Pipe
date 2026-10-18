"""API package export with sub-routers."""

from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.rooms import router as rooms_router
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router
from app.api.memory import router as memory_router
from app.api.settings import router as settings_router
from app.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(rooms_router)
api_router.include_router(documents_router)
api_router.include_router(chat_router)
api_router.include_router(memory_router)
api_router.include_router(settings_router)
api_router.include_router(health_router)

__all__ = ["api_router"]

