"""Conformance interfaces for OGC API compliance.

This module defines Protocol interfaces for conformance class providers,
enabling loose coupling with pygeoapi modules and potential third-party
extensions.

These Protocols follow the Static Duck Typing pattern from the project
guidelines, allowing any object with the required attributes to satisfy
the interface without explicit inheritance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class GenericConformance(Protocol):
    """Protocol for objects that provide conformance classes.

    Use this Protocol when accepting any object that can provide
    conformance classes. This enables loose coupling with pygeoapi
    modules (coverages, tiles, maps, etc.) and potential third-party
    extensions.

    Example usage:
        ```python
        def get_conformance(provider: GenericConformance) -> list[str]:
            return list(provider.CONFORMANCE_CLASSES)
        ```

    Compatible with pygeoapi modules:
        - pygeoapi.api.coverages
        - pygeoapi.api.tiles
        - pygeoapi.api.maps
        - pygeoapi.api.processes
        - pygeoapi.api.environmental_data_retrieval
        - pygeoapi.api.pubsub
    """

    @property
    def CONFORMANCE_CLASSES(self) -> Sequence[str]:
        """Return the conformance classes for this provider.

        Returns
        -------
        Sequence[str]
            A sequence of OGC conformance class URIs.
        """
        ...


class FeatureRecordConformance(Protocol):
    """Protocol for the itemtypes module with separate feature/record classes.

    The pygeoapi itemtypes module is special because it provides separate
    conformance class lists for OGC API Features and OGC API Records.
    This Protocol captures that specific interface.

    Example usage:
        ```python
        def get_feature_conformance(
            provider: FeatureRecordConformance,
        ) -> list[str]:
            return list(provider.CONFORMANCE_CLASSES_FEATURES)
        ```

    Compatible with:
        - pygeoapi.api.itemtypes
    """

    @property
    def CONFORMANCE_CLASSES_FEATURES(self) -> Sequence[str]:
        """Return the conformance classes for OGC API Features.

        Returns
        -------
        Sequence[str]
            A sequence of OGC API Features conformance class URIs.
        """
        ...

    @property
    def CONFORMANCE_CLASSES_RECORDS(self) -> Sequence[str]:
        """Return the conformance classes for OGC API Records.

        Returns
        -------
        Sequence[str]
            A sequence of OGC API Records conformance class URIs.
        """
        ...
