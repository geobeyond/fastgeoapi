"""Tests for conformance endpoint filtering based on configuration.

These tests verify that the conformance endpoint returns only the conformance
classes that correspond to the API types actually configured in the server,
rather than returning all possible conformance classes statically.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.pygeoapi.api.conformance import (
    ConformanceResponse,
    build_conformance_list,
)

# Base OGC API Common conformance classes (always present)
BASE_CONFORMANCE = {
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-common-2/1.0/conf/collections",
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/landing-page",
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/json",
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/html",
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30",
}

# OGC API Features conformance classes
FEATURES_CONFORMANCE = {
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/html",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
    "http://www.opengis.net/spec/ogcapi-features-2/1.0/conf/crs",
    "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/queryables",
    "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/queryables-query-parameters",
    "http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/create-replace-delete",
    "http://www.opengis.net/spec/ogcapi-features-5/1.0/conf/schemas",
    "http://www.opengis.net/spec/ogcapi-features-5/1.0/conf/core-roles-features",
}

# OGC API Processes conformance classes
PROCESSES_CONFORMANCE = {
    "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/ogc-process-description",
    "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/json",
    "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/callback",
}

# OGC API Coverages conformance classes
COVERAGES_CONFORMANCE = {
    "http://www.opengis.net/spec/ogcapi-coverages-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-coverages-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-coverages-1/1.0/conf/html",
    "http://www.opengis.net/spec/ogcapi-coverages-1/1.0/conf/geodata-coverage",
    "http://www.opengis.net/spec/ogcapi-coverages-1/1.0/conf/coverage-subset",
    "http://www.opengis.net/spec/ogcapi-coverages-1/1.0/conf/coverage-rangesubset",
    "http://www.opengis.net/spec/ogcapi-coverages-1/1.0/conf/coverage-bbox",
    "http://www.opengis.net/spec/ogcapi-coverages-1/1.0/conf/coverage-datetime",
}

# OGC API Tiles conformance classes
TILES_CONFORMANCE = {
    "http://www.opengis.net/spec/ogcapi-tiles-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-tiles-1/1.0/conf/mvt",
    "http://www.opengis.net/spec/ogcapi-tiles-1/1.0/conf/tileset",
    "http://www.opengis.net/spec/ogcapi-tiles-1/1.0/conf/tilesets-list",
    "http://www.opengis.net/spec/ogcapi-tiles-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-tiles-1/1.0/conf/geodata-tilesets",
}

# OGC API Maps conformance classes
MAPS_CONFORMANCE = {
    "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf/core",
}

# OGC API Records conformance classes
RECORDS_CONFORMANCE = {
    "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/sorting",
    "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/opensearch",
    "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json",
    "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/html",
}

# OGC API EDR conformance classes
EDR_CONFORMANCE = {
    "http://www.opengis.net/spec/ogcapi-edr-1/1.0/conf/core",
}


def get_conformance_response(response_json: dict[str, Any]) -> set[str]:
    """Extract conformance classes from response as a set."""
    return set(response_json.get("conformsTo", []))


class TestConformanceFiltering:
    """Tests for conformance endpoint filtering based on configuration.

    The default pygeoapi-config.yml has:
    - Feature providers (obs, lakes)
    - Process (hello-world)

    It does NOT have: coverages, tiles, maps, records, EDR.
    """

    @pytest.mark.asyncio
    async def test_conformance_includes_base_classes(
        self, unprotected_app
    ) -> None:
        """Test that base OGC API Common conformance classes are always included."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response = await client.get(f"{context}/conformance")
            assert response.status_code == 200

            conformance = get_conformance_response(response.json())
            assert BASE_CONFORMANCE.issubset(conformance), (
                f"Missing base conformance classes: {BASE_CONFORMANCE - conformance}"
            )

    @pytest.mark.asyncio
    async def test_conformance_includes_features_when_configured(
        self, unprotected_app
    ) -> None:
        """Test that Features conformance classes are included when feature providers exist."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response = await client.get(f"{context}/conformance")
            assert response.status_code == 200

            conformance = get_conformance_response(response.json())
            assert FEATURES_CONFORMANCE.issubset(conformance), (
                f"Missing features conformance classes: {FEATURES_CONFORMANCE - conformance}"
            )

    @pytest.mark.asyncio
    async def test_conformance_includes_processes_when_configured(
        self, unprotected_app
    ) -> None:
        """Test that Processes conformance classes are included when processes exist."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response = await client.get(f"{context}/conformance")
            assert response.status_code == 200

            conformance = get_conformance_response(response.json())
            assert PROCESSES_CONFORMANCE.issubset(conformance), (
                f"Missing processes conformance classes: {PROCESSES_CONFORMANCE - conformance}"
            )

    @pytest.mark.asyncio
    async def test_conformance_excludes_coverages_when_not_configured(
        self, unprotected_app
    ) -> None:
        """Test that Coverages conformance classes are NOT included when no coverage providers exist."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response = await client.get(f"{context}/conformance")
            assert response.status_code == 200

            conformance = get_conformance_response(response.json())
            coverage_intersection = COVERAGES_CONFORMANCE & conformance
            assert not coverage_intersection, (
                f"Unexpected coverages conformance classes present: {coverage_intersection}"
            )

    @pytest.mark.asyncio
    async def test_conformance_excludes_tiles_when_not_configured(
        self, unprotected_app
    ) -> None:
        """Test that Tiles conformance classes are NOT included when no tile providers exist."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response = await client.get(f"{context}/conformance")
            assert response.status_code == 200

            conformance = get_conformance_response(response.json())
            tiles_intersection = TILES_CONFORMANCE & conformance
            assert not tiles_intersection, (
                f"Unexpected tiles conformance classes present: {tiles_intersection}"
            )

    @pytest.mark.asyncio
    async def test_conformance_excludes_maps_when_not_configured(
        self, unprotected_app
    ) -> None:
        """Test that Maps conformance classes are NOT included when no map providers exist."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response = await client.get(f"{context}/conformance")
            assert response.status_code == 200

            conformance = get_conformance_response(response.json())
            maps_intersection = MAPS_CONFORMANCE & conformance
            assert not maps_intersection, (
                f"Unexpected maps conformance classes present: {maps_intersection}"
            )

    @pytest.mark.asyncio
    async def test_conformance_excludes_records_when_not_configured(
        self, unprotected_app
    ) -> None:
        """Test that Records conformance classes are NOT included when no record providers exist."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response = await client.get(f"{context}/conformance")
            assert response.status_code == 200

            conformance = get_conformance_response(response.json())
            records_intersection = RECORDS_CONFORMANCE & conformance
            assert not records_intersection, (
                f"Unexpected records conformance classes present: {records_intersection}"
            )

    @pytest.mark.asyncio
    async def test_conformance_excludes_edr_when_not_configured(
        self, unprotected_app
    ) -> None:
        """Test that EDR conformance classes are NOT included when no EDR providers exist."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response = await client.get(f"{context}/conformance")
            assert response.status_code == 200

            conformance = get_conformance_response(response.json())
            edr_intersection = EDR_CONFORMANCE & conformance
            assert not edr_intersection, (
                f"Unexpected EDR conformance classes present: {edr_intersection}"
            )


class TestConformanceIdempotency:
    """Tests to verify conformance endpoint doesn't accumulate classes across requests."""

    @pytest.mark.asyncio
    async def test_conformance_is_idempotent(self, unprotected_app) -> None:
        """Test that multiple requests to conformance return the same result.

        This test verifies the fix for the bug where conformance classes
        accumulate in the global list across multiple requests.
        """
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            response1 = await client.get(f"{context}/conformance")
            assert response1.status_code == 200
            conformance1 = get_conformance_response(response1.json())

            response2 = await client.get(f"{context}/conformance")
            assert response2.status_code == 200
            conformance2 = get_conformance_response(response2.json())

            response3 = await client.get(f"{context}/conformance")
            assert response3.status_code == 200
            conformance3 = get_conformance_response(response3.json())

            assert conformance1 == conformance2, (
                f"Conformance changed between request 1 and 2. "
                f"Added: {conformance2 - conformance1}, "
                f"Removed: {conformance1 - conformance2}"
            )
            assert conformance2 == conformance3, (
                f"Conformance changed between request 2 and 3. "
                f"Added: {conformance3 - conformance2}, "
                f"Removed: {conformance2 - conformance3}"
            )

    @pytest.mark.asyncio
    async def test_conformance_count_is_stable(self, unprotected_app) -> None:
        """Test that the number of conformance classes doesn't grow across requests."""
        transport = ASGITransport(app=unprotected_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")

        async with AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30
        ) as client:
            counts = []
            for _ in range(5):
                response = await client.get(f"{context}/conformance")
                assert response.status_code == 200
                conformance = get_conformance_response(response.json())
                counts.append(len(conformance))

            assert all(c == counts[0] for c in counts), (
                f"Conformance count changed across requests: {counts}"
            )


class TestBuildConformanceList:
    """Tests for the build_conformance_list service function."""

    def test_build_conformance_list_empty_resources(self) -> None:
        """Test build_conformance_list with no resources returns base classes."""
        response = build_conformance_list(resources={}, has_pubsub=False)

        assert isinstance(response, ConformanceResponse)
        assert BASE_CONFORMANCE.issubset(set(response.conforms_to))

    def test_build_conformance_list_with_feature_provider(self) -> None:
        """Test build_conformance_list includes feature classes."""
        resources = {
            "test_feature": {
                "type": "collection",
                "providers": [{"type": "feature", "name": "GeoJSON"}],
            },
        }

        response = build_conformance_list(resources=resources, has_pubsub=False)

        assert FEATURES_CONFORMANCE.issubset(set(response.conforms_to))

    def test_build_conformance_list_with_process(self) -> None:
        """Test build_conformance_list includes process classes."""
        resources = {
            "test_process": {
                "type": "process",
                "processor": {"name": "HelloWorld"},
            },
        }

        response = build_conformance_list(resources=resources, has_pubsub=False)

        assert PROCESSES_CONFORMANCE.issubset(set(response.conforms_to))

    def test_build_conformance_list_returns_sorted_unique(self) -> None:
        """Test build_conformance_list returns sorted, deduplicated classes."""
        resources = {
            "feature1": {
                "type": "collection",
                "providers": [{"type": "feature", "name": "GeoJSON"}],
            },
            "feature2": {
                "type": "collection",
                "providers": [{"type": "feature", "name": "GeoJSON"}],
            },
        }

        response = build_conformance_list(resources=resources, has_pubsub=False)

        assert list(response.conforms_to) == sorted(response.conforms_to)
        assert len(response.conforms_to) == len(set(response.conforms_to))
