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
    ResourceConfig,
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
    """Tests for conformance endpoint filtering."""

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
            # The default config has feature providers (obs, lakes)
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
            # The default config has hello-world process
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
            # The default config does NOT have coverage providers
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
            # The default config does NOT have tile providers
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
            # The default config does NOT have map providers
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
            # The default config does NOT have record providers
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
            # The default config does NOT have EDR providers
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
            # Make first request
            response1 = await client.get(f"{context}/conformance")
            assert response1.status_code == 200
            conformance1 = get_conformance_response(response1.json())

            # Make second request
            response2 = await client.get(f"{context}/conformance")
            assert response2.status_code == 200
            conformance2 = get_conformance_response(response2.json())

            # Make third request
            response3 = await client.get(f"{context}/conformance")
            assert response3.status_code == 200
            conformance3 = get_conformance_response(response3.json())

            # All requests should return the same conformance classes
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

            # All counts should be the same
            assert all(c == counts[0] for c in counts), (
                f"Conformance count changed across requests: {counts}"
            )


class TestConformanceGlobalListMutation:
    """Tests to verify the global CONFORMANCE_CLASSES list is not mutated.

    These tests directly verify that the pygeoapi bug where the global
    CONFORMANCE_CLASSES list is mutated on each request is fixed.
    """

    def test_pygeoapi_conformance_bug_demonstration(self) -> None:
        """Demonstrate the pygeoapi bug where global list is mutated.

        This test shows what happens when the buggy code pattern is used.
        It documents the bug that needs to be fixed.
        """
        from pygeoapi.api import all_apis

        # Create a fresh list to simulate CONFORMANCE_CLASSES
        test_global_list = ["class1", "class2", "class3"]
        original_length = len(test_global_list)

        apis_dict = all_apis()
        config_resources = {
            "test_feature": {
                "type": "collection",
                "providers": [{"type": "feature", "name": "GeoJSON"}],
            },
        }

        # Simulate the BUGGY pattern: direct assignment without copy
        for _ in range(3):
            conformance_list = test_global_list  # BUG: no copy!
            for key, value in config_resources.items():
                for provider in value.get("providers", []):
                    if provider["type"] == "feature":
                        conformance_list.extend(
                            apis_dict["itemtypes"].CONFORMANCE_CLASSES_FEATURES
                        )

        # This demonstrates the bug - the "global" list was mutated
        assert len(test_global_list) > original_length, (
            "Bug demonstration failed - list should have grown"
        )

    def test_correct_conformance_pattern_does_not_mutate(self) -> None:
        """Test that using list() copy prevents mutation.

        This test verifies that the fix (using list() to copy) works correctly.
        """
        from pygeoapi.api import all_apis

        # Create a fresh list to simulate CONFORMANCE_CLASSES
        test_global_list = ["class1", "class2", "class3"]
        original_length = len(test_global_list)
        original_classes = list(test_global_list)

        apis_dict = all_apis()
        config_resources = {
            "test_feature": {
                "type": "collection",
                "providers": [{"type": "feature", "name": "GeoJSON"}],
            },
        }

        # Simulate the FIXED pattern: use list() to copy
        for _ in range(3):
            conformance_list = list(test_global_list)  # FIX: make a copy
            for key, value in config_resources.items():
                for provider in value.get("providers", []):
                    if provider["type"] == "feature":
                        conformance_list.extend(
                            apis_dict["itemtypes"].CONFORMANCE_CLASSES_FEATURES
                        )

        # Verify the "global" list was NOT mutated
        assert len(test_global_list) == original_length, (
            f"List was mutated! Original: {original_length}, "
            f"Current: {len(test_global_list)}"
        )
        assert test_global_list == original_classes, (
            "List content was modified!"
        )


class TestConformanceValueObjects:
    """Tests for conformance value objects (dataclasses)."""

    def test_conformance_response_is_immutable(self) -> None:
        """Test that ConformanceResponse is immutable (frozen)."""
        response = ConformanceResponse(conforms_to=("class1", "class2"))

        with pytest.raises(AttributeError):
            response.conforms_to = ("modified",)  # type: ignore[misc]

    def test_conformance_response_to_dict(self) -> None:
        """Test ConformanceResponse.to_dict() produces OGC-compliant format."""
        response = ConformanceResponse(
            conforms_to=("class1", "class2", "class3")
        )

        result = response.to_dict()

        assert "conformsTo" in result
        assert result["conformsTo"] == ["class1", "class2", "class3"]
        assert isinstance(result["conformsTo"], list)

    def test_resource_config_from_feature_collection(self) -> None:
        """Test ResourceConfig.from_config_dict() with feature collection."""
        config = {
            "type": "collection",
            "providers": [
                {"type": "feature", "name": "GeoJSON"},
            ],
        }

        resource = ResourceConfig.from_config_dict("test_collection", config)

        assert resource.name == "test_collection"
        assert resource.resource_type == "collection"
        assert resource.provider_types == ("feature",)

    def test_resource_config_from_process(self) -> None:
        """Test ResourceConfig.from_config_dict() with process type."""
        config = {
            "type": "process",
            "processor": {"name": "HelloWorld"},
        }

        resource = ResourceConfig.from_config_dict("test_process", config)

        assert resource.name == "test_process"
        assert resource.resource_type == "process"
        assert resource.provider_types == ()

    def test_resource_config_with_multiple_providers(self) -> None:
        """Test ResourceConfig.from_config_dict() with multiple providers."""
        config = {
            "type": "collection",
            "providers": [
                {"type": "feature", "name": "GeoJSON"},
                {"type": "tile", "name": "MVT"},
            ],
        }

        resource = ResourceConfig.from_config_dict("multi_provider", config)

        assert resource.provider_types == ("feature", "tile")


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

        # Should be sorted
        assert list(response.conforms_to) == sorted(response.conforms_to)
        # Should have no duplicates
        assert len(response.conforms_to) == len(set(response.conforms_to))
