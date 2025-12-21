"""Tests for OpenAPI external reference resolver."""

from unittest import mock

import httpx
import pytest


class TestOpenAPIResolver:
    """Test suite for OpenAPI external $ref resolution."""

    def test_resolve_simple_external_ref(self):
        """Test resolving a simple external $ref."""
        from app.utils.openapi_resolver import resolve_external_refs

        # Mock the external schema
        external_schema = {"type": "string", "description": "A link"}

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schemas/link.yaml#/components/schemas/link"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"link": external_schema}}}
            resolved = resolve_external_refs(spec)

        # The external ref should be replaced with the actual schema
        result_schema = resolved["paths"]["/"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert result_schema == external_schema
        assert "$ref" not in result_schema

    def test_preserve_local_refs(self):
        """Test that local $refs (starting with #) are preserved."""
        from app.utils.openapi_resolver import resolve_external_refs

        spec = {
            "openapi": "3.0.0",
            "components": {
                "schemas": {
                    "Error": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    }
                }
            },
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "400": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Error"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        resolved = resolve_external_refs(spec)

        # Local ref should be preserved
        result_schema = resolved["paths"]["/"]["get"]["responses"]["400"]["content"][
            "application/json"
        ]["schema"]
        assert result_schema == {"$ref": "#/components/schemas/Error"}

    def test_resolve_nested_external_refs(self):
        """Test resolving nested external $refs (refs within resolved refs)."""
        from app.utils.openapi_resolver import resolve_external_refs

        # First level external schema references another external schema
        level1_schema = {
            "type": "object",
            "properties": {
                "link": {"$ref": "https://example.com/schemas/common.yaml#/components/schemas/href"}
            },
        }
        level2_schema = {"type": "string", "format": "uri"}

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schemas/link.yaml#/components/schemas/link"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        def mock_fetch(url):
            if "link.yaml" in url:
                return {"components": {"schemas": {"link": level1_schema}}}
            elif "common.yaml" in url:
                return {"components": {"schemas": {"href": level2_schema}}}
            raise ValueError(f"Unexpected URL: {url}")

        with mock.patch(
            "app.utils.openapi_resolver._fetch_remote_document",
            side_effect=mock_fetch,
        ):
            resolved = resolve_external_refs(spec)

        # Both levels should be resolved
        result_schema = resolved["paths"]["/"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert result_schema["type"] == "object"
        assert result_schema["properties"]["link"] == level2_schema

    def test_cache_remote_documents(self):
        """Test that remote documents are cached and not fetched multiple times."""
        from app.utils.openapi_resolver import resolve_external_refs

        external_schema = {"type": "string"}

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/a": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schemas/link.yaml#/components/schemas/link"
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "/b": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schemas/link.yaml#/components/schemas/link"
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"link": external_schema}}}
            resolve_external_refs(spec)

        # Should only fetch once despite two references to the same URL
        assert mock_fetch.call_count == 1

    def test_resolve_refs_in_arrays(self):
        """Test resolving $refs inside arrays."""
        from app.utils.openapi_resolver import resolve_external_refs

        external_schema = {"type": "string"}

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "oneOf": [
                                                {
                                                    "$ref": "https://example.com/schemas/a.yaml#/components/schemas/a"
                                                },
                                                {"type": "integer"},
                                            ]
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"a": external_schema}}}
            resolved = resolve_external_refs(spec)

        result_schema = resolved["paths"]["/"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert result_schema["oneOf"][0] == external_schema
        assert result_schema["oneOf"][1] == {"type": "integer"}

    def test_handle_yaml_and_json_remote_files(self):
        """Test that both YAML and JSON remote files are handled correctly."""
        from app.utils.openapi_resolver import resolve_external_refs

        yaml_schema = {"type": "string", "description": "from yaml"}
        json_schema = {"type": "number", "description": "from json"}

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/yaml": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schemas/a.yaml#/components/schemas/a"
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "/json": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schemas/b.json#/components/schemas/b"
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            },
        }

        def mock_fetch(url):
            if url.endswith(".yaml"):
                return {"components": {"schemas": {"a": yaml_schema}}}
            elif url.endswith(".json"):
                return {"components": {"schemas": {"b": json_schema}}}
            raise ValueError(f"Unexpected URL: {url}")

        with mock.patch(
            "app.utils.openapi_resolver._fetch_remote_document",
            side_effect=mock_fetch,
        ):
            resolved = resolve_external_refs(spec)

        yaml_result = resolved["paths"]["/yaml"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        json_result = resolved["paths"]["/json"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        assert yaml_result == yaml_schema
        assert json_result == json_schema

    def test_count_external_refs(self):
        """Test counting external references in a spec."""
        from app.utils.openapi_resolver import count_external_refs

        spec = {
            "paths": {
                "/a": {"$ref": "https://example.com/a.yaml#/path"},
                "/b": {"$ref": "#/components/paths/b"},  # local ref - should not count
            },
            "components": {
                "schemas": {
                    "A": {"$ref": "https://example.com/schemas.yaml#/A"},
                    "B": {"type": "string"},
                }
            },
        }

        count = count_external_refs(spec)
        assert count == 2  # Only external refs

    def test_has_external_refs(self):
        """Test checking if spec has external references."""
        from app.utils.openapi_resolver import has_external_refs

        spec_with_external = {"paths": {"/": {"$ref": "https://example.com/path.yaml#/path"}}}
        spec_with_local_only = {"paths": {"/": {"$ref": "#/components/paths/root"}}}
        spec_without_refs = {"paths": {"/": {"get": {"responses": {"200": {}}}}}}

        assert has_external_refs(spec_with_external) is True
        assert has_external_refs(spec_with_local_only) is False
        assert has_external_refs(spec_without_refs) is False

    def test_resolve_real_ogc_style_refs(self):
        """Test resolving OGC API style external references."""
        from app.utils.openapi_resolver import resolve_external_refs

        # Simulate OGC API style refs
        landing_page_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "links": {
                    "type": "array",
                    "items": {
                        "$ref": "https://schemas.opengis.net/ogcapi/common.yaml#/components/schemas/link"
                    },
                },
            },
        }
        link_schema = {
            "type": "object",
            "properties": {
                "href": {"type": "string", "format": "uri"},
                "rel": {"type": "string"},
            },
        }

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "$ref": "https://schemas.opengis.net/ogcapi/features.yaml#/components/responses/LandingPage"
                            }
                        }
                    }
                }
            },
        }

        def mock_fetch(url):
            if "features.yaml" in url:
                return {
                    "components": {
                        "responses": {
                            "LandingPage": {
                                "content": {"application/json": {"schema": landing_page_schema}}
                            }
                        }
                    }
                }
            elif "common.yaml" in url:
                return {"components": {"schemas": {"link": link_schema}}}
            raise ValueError(f"Unexpected URL: {url}")

        with mock.patch(
            "app.utils.openapi_resolver._fetch_remote_document",
            side_effect=mock_fetch,
        ):
            resolved = resolve_external_refs(spec)

        # Verify the response was resolved
        response = resolved["paths"]["/"]["get"]["responses"]["200"]
        assert "content" in response

        # Verify nested link schema was also resolved
        schema = response["content"]["application/json"]["schema"]
        assert schema["properties"]["links"]["items"] == link_schema

    def test_handle_fetch_error_gracefully(self):
        """Test that fetch errors are handled gracefully."""
        from app.utils.openapi_resolver import resolve_external_refs

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://nonexistent.example.com/schema.yaml#/a"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch(
            "app.utils.openapi_resolver._fetch_remote_document",
            side_effect=httpx.RequestError("Connection failed"),
        ):
            with pytest.raises(httpx.RequestError):
                resolve_external_refs(spec)

    def test_iterative_resolution_until_complete(self):
        """Test that resolution continues until no external refs remain."""
        from app.utils.openapi_resolver import (
            has_external_refs,
            resolve_external_refs,
        )

        # Create a chain of refs: spec -> level1 -> level2 -> level3
        level3_schema = {"type": "string", "description": "final"}
        level2_schema = {
            "type": "object",
            "properties": {"value": {"$ref": "https://example.com/level3.yaml#/schemas/value"}},
        }
        level1_schema = {
            "type": "object",
            "properties": {"nested": {"$ref": "https://example.com/level2.yaml#/schemas/nested"}},
        }

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/level1.yaml#/schemas/root"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        def mock_fetch(url):
            if "level1.yaml" in url:
                return {"schemas": {"root": level1_schema}}
            elif "level2.yaml" in url:
                return {"schemas": {"nested": level2_schema}}
            elif "level3.yaml" in url:
                return {"schemas": {"value": level3_schema}}
            raise ValueError(f"Unexpected URL: {url}")

        with mock.patch(
            "app.utils.openapi_resolver._fetch_remote_document",
            side_effect=mock_fetch,
        ):
            resolved = resolve_external_refs(spec)

        # Should have no external refs remaining
        assert has_external_refs(resolved) is False

        # Verify full resolution chain
        schema = resolved["paths"]["/"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert schema["properties"]["nested"]["properties"]["value"] == level3_schema


class TestOpenAPIResolverCache:
    """Test suite for OpenAPI resolver disk caching."""

    def test_cache_stores_fetched_documents(self, tmp_path):
        """Test that fetched documents are stored in cache directory."""
        from app.utils.openapi_resolver import resolve_external_refs

        external_schema = {"type": "string"}
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schema.yaml#/components/schemas/a"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"a": external_schema}}}
            resolve_external_refs(spec, cache_dir=tmp_path)

        # Verify cache file was created
        cache_files = list(tmp_path.glob("*.json"))
        assert len(cache_files) == 1

    def test_cache_is_used_on_subsequent_calls(self, tmp_path):
        """Test that cached documents are used instead of fetching again."""
        from app.utils.openapi_resolver import resolve_external_refs

        external_schema = {"type": "string"}
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schema.yaml#/components/schemas/a"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"a": external_schema}}}

            # First call - should fetch
            resolve_external_refs(spec, cache_dir=tmp_path)
            assert mock_fetch.call_count == 1

            # Second call - should use cache
            resolve_external_refs(spec, cache_dir=tmp_path)
            assert mock_fetch.call_count == 1  # Still 1, not fetched again

    def test_cache_respects_ttl(self, tmp_path):
        """Test that cache entries expire after TTL."""
        from app.utils.openapi_resolver import resolve_external_refs

        external_schema = {"type": "string"}
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schema.yaml#/components/schemas/a"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"a": external_schema}}}

            # First call with very short TTL
            resolve_external_refs(spec, cache_dir=tmp_path, cache_ttl_seconds=0)
            assert mock_fetch.call_count == 1

            # Second call - cache expired, should fetch again
            resolve_external_refs(spec, cache_dir=tmp_path, cache_ttl_seconds=0)
            assert mock_fetch.call_count == 2

    def test_cache_disabled_when_no_cache_dir(self):
        """Test that caching is disabled when cache_dir is None."""
        from app.utils.openapi_resolver import resolve_external_refs

        external_schema = {"type": "string"}
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schema.yaml#/components/schemas/a"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"a": external_schema}}}

            # Both calls without cache_dir should fetch
            resolve_external_refs(spec, cache_dir=None)
            resolve_external_refs(spec, cache_dir=None)
            assert mock_fetch.call_count == 2

    def test_cache_creates_directory_if_not_exists(self, tmp_path):
        """Test that cache directory is created if it doesn't exist."""
        from app.utils.openapi_resolver import resolve_external_refs

        cache_dir = tmp_path / "new_cache_dir"
        assert not cache_dir.exists()

        external_schema = {"type": "string"}
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schema.yaml#/components/schemas/a"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"a": external_schema}}}
            resolve_external_refs(spec, cache_dir=cache_dir)

        assert cache_dir.exists()

    def test_cache_handles_different_urls_separately(self, tmp_path):
        """Test that different URLs are cached separately."""
        from app.utils.openapi_resolver import resolve_external_refs

        schema_a = {"type": "string"}
        schema_b = {"type": "number"}

        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/a": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "https://example.com/a.yaml#/schemas/a"}
                                    }
                                }
                            }
                        }
                    }
                },
                "/b": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "https://example.com/b.yaml#/schemas/b"}
                                    }
                                }
                            }
                        }
                    }
                },
            },
        }

        def mock_fetch(url):
            if "a.yaml" in url:
                return {"schemas": {"a": schema_a}}
            elif "b.yaml" in url:
                return {"schemas": {"b": schema_b}}
            raise ValueError(f"Unexpected URL: {url}")

        with mock.patch(
            "app.utils.openapi_resolver._fetch_remote_document",
            side_effect=mock_fetch,
        ):
            resolve_external_refs(spec, cache_dir=tmp_path)

        # Two different URLs should create two cache files
        cache_files = list(tmp_path.glob("*.json"))
        assert len(cache_files) == 2

    def test_cache_file_contains_valid_json(self, tmp_path):
        """Test that cache files contain valid JSON with document content."""
        import json

        from app.utils.openapi_resolver import resolve_external_refs

        external_schema = {"type": "string", "description": "test"}
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "https://example.com/schema.yaml#/components/schemas/a"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        with mock.patch("app.utils.openapi_resolver._fetch_remote_document") as mock_fetch:
            mock_fetch.return_value = {"components": {"schemas": {"a": external_schema}}}
            resolve_external_refs(spec, cache_dir=tmp_path)

        # Read and verify cache file content
        cache_files = list(tmp_path.glob("*.json"))
        assert len(cache_files) == 1

        with open(cache_files[0]) as f:
            cached_data = json.load(f)

        assert "document" in cached_data
        assert "timestamp" in cached_data
        assert cached_data["document"]["components"]["schemas"]["a"] == external_schema
