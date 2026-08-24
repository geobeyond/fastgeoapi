"""The provider through the whole fastgeoapi stack.

Builds a pygeoapi config that points a collection at a DuckDB-generated
GeoParquet dataset and drives it over HTTP, so the OGC API contract —
not just the provider API — is what gets checked.
"""

import pytest
from starlette.testclient import TestClient

from app.provider.duckdb_ import connect
from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp


def _dataset(root) -> str:
    con = connect(str(root))
    con.execute(
        f"""
        COPY (
            SELECT 1 AS id, 'alpha' AS name, 'it' AS country, ST_Point(12.5, 41.9) AS geom
            UNION ALL SELECT 2, 'beta', 'fr', ST_Point(2.3, 48.9)
        ) TO '{root}/ds' (FORMAT parquet, PARTITION_BY (country), OVERWRITE_OR_IGNORE)
        """
    )
    return f"{root}/ds"


def _config(dataset: str) -> dict:
    return {
        "server": {
            "bind": {"host": "0.0.0.0", "port": 5000},
            "url": "http://localhost:5000",
            "mimetype": "application/json; charset=UTF-8",
            "encoding": "utf-8",
            "language": "en-US",
            "map": {
                "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                "attribution": "OpenStreetMap",
            },
        },
        "logging": {"level": "ERROR"},
        "metadata": {
            "identification": {
                "title": {"en": "GeoParquet test"},
                "description": {"en": "GeoParquet test"},
                "keywords": {"en": ["geoparquet"]},
                "keywords_type": "theme",
                "terms_of_service": "https://creativecommons.org/licenses/by/4.0/",
                "url": "https://example.org",
            },
            "license": {
                "name": "CC-BY 4.0",
                "url": "https://creativecommons.org/licenses/by/4.0/",
            },
            "provider": {"name": "geobeyond", "url": "https://geobeyond.it"},
            "contact": {"name": "test", "email": "test@example.org"},
        },
        "resources": {
            "places": {
                "type": "collection",
                "title": {"en": "Places"},
                "description": {"en": "Places"},
                "keywords": {"en": ["places"]},
                "extents": {
                    "spatial": {
                        "bbox": [-180, -90, 180, 90],
                        "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                    }
                },
                "links": [],
                "providers": [
                    {
                        "type": "feature",
                        "name": "app.provider.geoparquet.GeoParquetProvider",
                        "data": dataset,
                        "id_field": "id",
                        "geometry_column": "geom",
                    }
                ],
            }
        },
    }


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    config = _config(_dataset(tmp_path_factory.mktemp("e2e")))
    subapp = build_pygeoapi_subapp(config, build_openapi(config))
    return TestClient(subapp, raise_server_exceptions=False)


def test_collection_is_advertised(client):
    r = client.get("/collections?f=json")
    assert r.status_code == 200
    assert "places" in {c["id"] for c in r.json()["collections"]}


def test_items_over_http(client):
    r = client.get("/collections/places/items?f=json&limit=10")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert sorted(f["id"] for f in body["features"]) == [1, 2]


def test_cql2_over_http(client):
    r = client.get(
        "/collections/places/items",
        params={"f": "json", "filter": "name = 'beta'", "filter-lang": "cql2-text"},
    )
    assert r.status_code == 200, r.text[:300]
    assert [f["id"] for f in r.json()["features"]] == [2]


def test_spatial_cql2_over_http(client):
    r = client.get(
        "/collections/places/items",
        params={
            "f": "json",
            "filter": "S_INTERSECTS(geom, POLYGON((11 41, 14 41, 14 43, 11 43, 11 41)))",
            "filter-lang": "cql2-text",
        },
    )
    assert r.status_code == 200, r.text[:300]
    assert [f["id"] for f in r.json()["features"]] == [1]


def test_bbox_over_http(client):
    r = client.get("/collections/places/items?f=json&bbox=11,41,14,43")
    assert r.status_code == 200, r.text[:300]
    assert [f["id"] for f in r.json()["features"]] == [1]


def test_single_item_over_http(client):
    r = client.get("/collections/places/items/1?f=json")
    assert r.status_code == 200, r.text[:300]
    assert r.json()["properties"]["name"] == "alpha"


def test_queryables_expose_the_columns(client):
    r = client.get("/collections/places/queryables?f=json")
    assert r.status_code == 200
    assert "name" in r.json()["properties"]


def test_items_html_renders(client):
    """The HTML rendering must work on a config the schema accepts.

    Every other test here asks for JSON, which is how a 500 on the HTML
    branch went unnoticed: pygeoapi's items template dereferences
    ``config['server']['limits']['default_items']`` unconditionally,
    while its own JSON Schema does not require ``limits`` and its Python
    code reads it with ``.get('limits', {})``. A tenant config without
    that key therefore validates, serves JSON, and 500s in a browser.
    """
    r = client.get("/collections/places/items?f=html&limit=1")
    assert r.status_code == 200, r.text[:300]
    assert "html" in r.headers.get("content-type", "")


def test_collection_and_landing_html_render(client):
    for path in ("/?f=html", "/collections?f=html", "/collections/places?f=html"):
        assert client.get(path).status_code == 200, path


def test_the_provider_is_not_rebuilt_per_request(client, monkeypatch):
    """Requests must not each rebuild the provider.

    pygeoapi calls load_plugin per request (ten call sites in itemtypes
    alone), so without the plugin cache a DuckDB session — 76 ms, mostly
    loading the spatial extension — is opened again and again while the
    query itself takes 3 ms.

    The assertion is "at most one build", not "exactly one": other test
    modules purge ``app.*`` from ``sys.modules``, so the invalidation
    call below may reach a second copy of the cache module while the
    running app keeps the instance it already had. Zero builds is the
    same evidence of reuse; five would mean the cache is gone.
    """
    from app.provider import geoparquet
    from app.pygeoapi.plugin import invalidate_plugin_cache

    invalidate_plugin_cache()
    built = []
    original = geoparquet.GeoParquetProvider.__init__

    def counting_init(self, provider_def):
        built.append(provider_def.get("data"))
        original(self, provider_def)

    monkeypatch.setattr(geoparquet.GeoParquetProvider, "__init__", counting_init)

    for _ in range(5):
        assert client.get("/collections/places/items?f=json&limit=1").status_code == 200

    assert len(built) <= 1, f"provider rebuilt {len(built)} times for 5 requests"
