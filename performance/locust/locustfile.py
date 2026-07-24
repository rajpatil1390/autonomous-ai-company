"""Expose the production performance user classes to Locust discovery."""

from users import Analyst, Manager, Viewer


__all__ = ["Analyst", "Manager", "Viewer"]
