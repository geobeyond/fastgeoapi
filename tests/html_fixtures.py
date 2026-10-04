"""What the tests of the HTML pages share.

``app.*`` is imported inside ``native_client``, and nowhere else here. The
sub-app is then built from the modules loaded at that moment, the same ones
pygeoapi finds when it loads a provider by name. Imported at the top, the
pages would keep the classes of the first load, and a test module that purges
``app.*`` earlier in the run would leave them unlike the provider's.
"""

import json
import re
from pathlib import Path

from pygeoapi.process.base import BaseProcessor
from pygeoapi.process.manager.tinydb_ import TinyDBManager
from pygeoapi.util import yaml_load
from starlette.testclient import TestClient

from tests.maps_fixtures import map_provider
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
    "_maplibre-3d2e.js": {"file": "assets/maplibre-3d2e.js"},
    "pages/map.ts": {
        "file": "assets/map-8b0c.js",
        "src": "pages/map.ts",
        "isEntry": True,
        "imports": ["_maplibre-3d2e.js", "_config-9c1d.js"],
        "css": ["assets/map-8b0c.css"],
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
    from app.html.activation import native_pages
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

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


ECHO_METADATA = {
    "version": "1.0.0",
    "id": "echo",
    "title": "Echo",
    "description": "Echoes its inputs back </script><script>alert(1)</script>",
    "jobControlOptions": ["sync-execute"],
    "keywords": ["echo"],
    "links": [],
    "inputs": {
        "anything": {
            "title": "Anything",
            "description": "Any JSON value </script><b>bold</b>",
            "minOccurs": 0,
            "maxOccurs": 1,
        }
    },
    "outputs": {"echo": {"title": "Echo", "schema": {"type": "object"}}},
}


class EchoProcessor(BaseProcessor):
    """A process with markup in its texts and an input without a schema."""

    def __init__(self, processor_def: dict) -> None:
        super().__init__(processor_def, ECHO_METADATA)

    def execute(self, data: dict, outputs: dict | None = None) -> tuple[str, dict]:
        return "application/json", {"echo": data}


def with_echo(api_config: dict) -> dict:
    """``api_config`` with the echo process."""
    api_config["resources"]["echo"] = {
        "type": "process",
        "processor": {"name": "tests.html_fixtures.EchoProcessor"},
    }
    return api_config


RUNNING_JOB = "job-running"


def _manager(directory: Path) -> dict:
    return {
        "name": "TinyDB",
        "connection": str(directory / "jobs.db"),
        "output_dir": str(directory),
    }


def with_jobs(api_config: dict, directory: Path) -> dict:
    """``api_config`` with a job manager that keeps its jobs in ``directory``."""
    api_config["server"]["manager"] = _manager(directory)
    return api_config


def add_running_job(directory: Path) -> None:
    """A job of hello-world halfway through, in the manager of ``directory``."""
    TinyDBManager(_manager(directory)).add_job(
        {
            "type": "process",
            "identifier": RUNNING_JOB,
            "process_id": "hello-world",
            "created": "2026-10-03T10:00:00Z",
            "started": "2026-10-03T10:00:01Z",
            "updated": "2026-10-03T10:00:30Z",
            "finished": None,
            "status": "running",
            "location": None,
            "mimetype": "application/json",
            "message": "Halfway there",
            "progress": 50,
        }
    )


CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


def with_map(api_config: dict, directory: Path) -> dict:
    """``api_config`` with ``roads``, a collection drawn as map images in two styles."""
    archive = write_archive(
        directory / "roads.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "roads", "vector_layers": [{"id": "roads"}]},
    )
    night = directory / "night.json"
    night.write_text(
        '{"version": 8, "sources": {}, "layers": [{"id": "night", "type": "background"}]}'
    )
    api_config["resources"]["roads"] = {
        "type": "collection",
        "title": "Roads",
        "description": "Roads drawn as maps",
        "keywords": ["roads"],
        "extents": {"spatial": {"bbox": [12.2, 41.7, 12.7, 42.1], "crs": CRS84}},
        "links": [],
        "providers": [map_provider(archive, styles={"night": str(night)}, max_size=1024)],
    }
    return api_config


def with_lost_tiles(api_config: dict, directory: Path) -> dict:
    """``api_config`` with ``lost``, a collection of tiles whose archive does not read."""
    archive = directory / "lost.pmtiles"
    archive.write_bytes(b"not an archive")
    api_config["resources"]["lost"] = {
        "type": "collection",
        "title": "Lost",
        "description": "Tiles that cannot be read",
        "keywords": [],
        "extents": {"spatial": {"bbox": [6.6, 36.6, 18.5, 47.1], "crs": CRS84}},
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
