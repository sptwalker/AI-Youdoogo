"""Compatibility facade for the database platform model base."""

from app.platform.database.model import Base, CommonMixin

__all__ = ["Base", "CommonMixin"]
