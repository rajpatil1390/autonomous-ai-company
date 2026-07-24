"""Expose the HTTP adapter without constructing an application globally."""

from autonomous_ai_company.api.app import create_app

__all__ = ["create_app"]
