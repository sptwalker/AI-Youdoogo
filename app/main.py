"""Compatibility ASGI import path; composition lives in :mod:`app.bootstrap`."""

from app.bootstrap.app import app, create_app

__all__ = ["app", "create_app"]
