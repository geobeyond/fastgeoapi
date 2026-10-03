"""What the tests of the HTML pages share.

``app.*`` is imported at the top of this module; a test module that uses it
imports ``app.*`` at its top as well.
"""

import json
import re
from pathlib import Path

from pygeoapi.util import yaml_load
from starlette.testclient import TestClient

from app.html.activation import native_pages
from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
from tests.pmtiles_fixtures import TILE_BYTES, write_archive

MANIFEST = {
    "pages/style.css": {"file": "assets/style-4f2a.css", "src": "pages/style.css", "isEntry": True},
    "_config-9c1d.js": {"file": "assets/config-9c1d.js"},
    "pages/api-docs.ts": {
        "file": "assets/api-docs-77aa.js",
        "src": "pages/api-docs.ts",
        "isEntry": True,
        "imports": ["_config-9c1d.js"],
        "css": ["assets/api-docs-77aa.css"],
    },
    "pages/process-run.ts": {
        "file": "assets/process-run-1b3e.js",
        "src": "pages/process-run.ts",
        "isEntry": True,
        "imports": ["_config-9c1d.js"],
    },
    "pages/job-status.ts": {
        "file": "assets/job-status-5e60.js",
        "src": "pages/job-status.ts",
        "isEntry": True,
        "imports": ["_config-9c1d.js"],
    },
}
"""A manifest shaped as Vite writes it, for pages tested without a build."""

SERVER_URL = "http://example.org/geoapi"
"""The server URL of the tests' configuration, not the host the test client calls."""


def config() -> dict:
    """The tests' configuration, served at ``SERVER_URL`` in English, Italian and French."""
    with Path("tests/data/pygeoapi-config.yml").open() as handle:
        loaded = yaml_load(handle)
    loaded["server"]["url"] = SERVER_URL
    loaded["server"]["languages"] = ["en-US", "it-IT", "fr-CA"]
    return loaded


def fake_build(directory: Path) -> Path:
    """A compiled-assets directory: the manifest, and the stylesheet it names."""
    (directory / ".vite").mkdir(parents=True)
    (directory / ".vite" / "manifest.json").write_text(json.dumps(MANIFEST))
    (directory / "assets").mkdir()
    (directory / "assets" / "style-4f2a.css").write_text("body { margin: 0; }\n")
    return directory


def native_client(api_config: dict, static: Path) -> TestClient:
    """A client of the sub-app of ``api_config``, with fastgeoapi's pages and ``static`` assets."""
    pages = native_pages(static=static)
    subapp = build_pygeoapi_subapp(api_config, build_openapi(api_config), pages=pages)
    return TestClient(subapp, raise_server_exceptions=False)


def jsonld(html: str) -> dict:
    """The JSON-LD the page carries in its head."""
    found = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    assert found is not None
    return json.loads(found.group(1))


def with_tiles(api_config: dict, directory: Path) -> dict:
    """``api_config`` with ``places``, a collection of vector tiles from a PMTiles archive."""
    archive = write_archive(
        directory / "places.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "Places", "vector_layers": [{"id": "place", "minzoom": 0, "maxzoom": 2}]},
    )
    api_config["resources"]["places"] = {
        "type": "collection",
        "title": "Places",
        "description": "Places as vector tiles",
        "keywords": ["places"],
        "extents": {
            "spatial": {
                "bbox": [-180, -90, 180, 90],
                "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            }
        },
        "links": [],
        "providers": [
            {
                "type": "tile",
                "name": "app.provider.pmtiles.PMTilesProvider",
                "data": str(archive),
                "options": {"zoom": {"min": 0, "max": 2}, "schemes": ["WebMercatorQuad"]},
                "format": {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"},
            }
        ],
    }
    return api_config


def island_config(html: str, element: str) -> dict:
    """The configuration the server wrote inside an island element."""
    found = re.search(
        rf'<{element}>\s*<script type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert found is not None
    return json.loads(found.group(1))
