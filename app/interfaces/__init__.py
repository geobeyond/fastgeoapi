"""Interfaces module for fastgeoapi.

This module contains Protocol definitions for dependency injection
and loose coupling throughout the application.
"""

from app.interfaces.conformance import (
    FeatureRecordConformance,
    GenericConformance,
)
from app.interfaces.http_client import AsyncHTTPClient

__all__ = [
    "AsyncHTTPClient",
    "FeatureRecordConformance",
    "GenericConformance",
]
