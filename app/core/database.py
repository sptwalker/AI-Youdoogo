"""Compatibility facade for the database platform package."""

from app.platform.database import async_session_factory, engine, get_db

__all__ = ["async_session_factory", "engine", "get_db"]
