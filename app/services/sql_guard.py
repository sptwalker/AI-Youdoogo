"""Compatibility facade for the Governed Data Query SQL policy."""

from app.contexts.foundations.integration.governed_data_query import SqlRejected, check_sql

__all__ = ["SqlRejected", "check_sql"]
