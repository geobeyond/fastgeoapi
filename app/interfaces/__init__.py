"""Interfaces module for fastgeoapi.

This module contains Protocol definitions for dependency injection
and loose coupling throughout the application.
"""

from app.interfaces.conformance import (
    FeatureRecordConformance,
    GenericConformance,
)
from app.interfaces.http_client import AsyncHTTPClient
from app.interfaces.providers import AsyncFeatureProvider, AsyncMapProvider, AsyncTileProvider

__all__ = [
    "AsyncFeatureProvider",
    "AsyncHTTPClient",
    "AsyncMapProvider",
    "AsyncTileProvider",
    "FeatureRecordConformance",
    "GenericConformance",
]
