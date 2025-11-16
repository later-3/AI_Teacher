"""
Backend application package for AI Teacher Stage 1.

This package exposes the FastAPI app along with database models,
services, and routers required for the ingestion & course modeling stage.
"""

from .main import create_app

__all__ = ["create_app"]
