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

import numpy as np
import rasterio
from pygeoapi.process.base import BaseProcessor
from pygeoapi.process.manager.tinydb_ import TinyDBManager
from pygeoapi.provider.base import BaseProvider
from pygeoapi.provider.base_edr import BaseEDRProvider
from pygeoapi.util import yaml_load
from rasterio.transform import from_bounds
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


def section(html: str, heading: str) -> str:
    """What the page shows under its ``<h2>`` named ``heading``, up to the next one."""
    _, found, rest = html.partition(f"<h2>{heading}</h2>")
    assert found, f"no section {heading!r}"
    return rest.split("<h2>", 1)[0]


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


def with_parquet_lakes(api_config: dict) -> dict:
    """``api_config`` with ``lakes-parquet``: four lakes in GeoParquet, whose provider applies CQL2."""
    api_config["resources"]["lakes-parquet"] = {
        "type": "collection",
        "title": "Lakes in GeoParquet",
        "description": "Four lakes",
        "keywords": [],
        "extents": {
            "spatial": {"bbox": [-180, -90, 180, 90], "crs": CRS84},
            "temporal": {"begin": "2000-01-01T00:00:00Z", "end": None},
        },
        "links": [],
        "providers": [
            {
                "type": "feature",
                "name": "app.provider.geoparquet.GeoParquetProvider",
                "data": "tests/data/lakes.parquet",
                "id_field": "id",
                "geometry_column": "geometry",
            }
        ],
    }
    return api_config


ROME = (12.2, 41.7, 12.7, 42.1)


def with_coverage(api_config: dict, directory: Path) -> dict:
    """``api_config`` with ``dem``, a coverage of one band in 4 by 4 cells over Rome."""
    path = directory / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(*ROME, 4, 4),
    ) as raster:
        raster.write(np.arange(16, dtype="float32").reshape(1, 4, 4))
    api_config["resources"]["dem"] = {
        "type": "collection",
        "title": "DEM",
        "description": "Heights over Rome",
        "keywords": [],
        "extents": {"spatial": {"bbox": list(ROME), "crs": CRS84}},
        "links": [],
        "providers": [
            {
                "type": "coverage",
                "name": "rasterio",
                "data": str(path),
                "options": {"DATA": {"BAND": 1}},
                "format": {"name": "GTiff", "mimetype": "application/tiff"},
            }
        ],
    }
    return api_config


EDR_COVERAGE = {
    "type": "Coverage",
    "domain": {
        "type": "Domain",
        "domainType": "Point",
        "axes": {
            "x": {"values": [12.5]},
            "y": {"values": [41.9]},
            "t": {"values": ["2026-10-03T00:00:00Z"]},
        },
        "referencing": [],
    },
    "parameters": {
        "temperature": {
            "type": "Parameter",
            "unit": {"symbol": "K"},
            "observedProperty": {"label": {"en": "Temperature"}},
        }
    },
    "ranges": {
        "temperature": {
            "type": "NdArray",
            "dataType": "float",
            "axisNames": ["t"],
            "shape": [1],
            "values": [288.4],
        }
    },
}
"""The answer of the fake EDR source: one temperature at one point."""


class FakeEDRProvider(BaseEDRProvider):
    """An EDR source with one instance and one point, without xarray."""

    def __init__(self, provider_def: dict):
        super().__init__(provider_def)
        # pygeoapi's EDR sources read their fields when they open, and the
        # parameters of the collection come from them.
        self._fields = self.get_fields()

    def get_fields(self) -> dict:
        return {"temperature": {"title": "Temperature", "type": "number", "x-ogc-unit": "K"}}

    def instances(self) -> list[str]:
        return ["2026"]

    def instance(self, instance: str) -> bool:
        return instance in self.instances()

    def position(self, **kwargs) -> dict:
        return EDR_COVERAGE


PHOTO = {
    "type": "Feature",
    "id": "colosseum",
    "geometry": {"type": "Point", "coordinates": [12.4922, 41.8902]},
    "properties": {
        "name": "Colosseum",
        "image": "https://example.org/colosseum.jpg",
        "note": "Opening hours on https://example.org/hours",
        "tags": ["arena", "rome"],
        "source": {"agency": "MiC", "year": 2026},
    },
}
"""An item whose values are an image, a text with a URL, a list and an object."""


def with_photos(api_config: dict, directory: Path) -> dict:
    """``api_config`` with ``photos``, a GeoJSON collection of one item with rich values."""
    data = directory / "photos.geojson"
    data.write_text(json.dumps({"type": "FeatureCollection", "features": [PHOTO]}))
    api_config["resources"]["photos"] = {
        "type": "collection",
        "title": "Photos",
        "description": "Photos of Rome",
        "keywords": [],
        "extents": {"spatial": {"bbox": [12.4, 41.8, 12.6, 42.0], "crs": CRS84}},
        "links": [],
        "providers": [
            {
                "type": "feature",
                "name": "GeoJSON",
                "data": str(data),
                "id_field": "id",
                "title_field": "name",
            }
        ],
    }
    return api_config


def with_edr(api_config: dict) -> dict:
    """``api_config`` with ``weather``, environmental data from the fake EDR source."""
    api_config["resources"]["weather"] = {
        "type": "collection",
        "title": "Weather",
        "description": "Temperatures",
        "keywords": [],
        "extents": {"spatial": {"bbox": [6.6, 36.6, 18.5, 47.1], "crs": CRS84}},
        "links": [],
        "providers": [
            {"type": "edr", "name": "tests.html_fixtures.FakeEDRProvider", "data": "unused"}
        ],
    }
    return api_config


class FakeStacProvider(BaseProvider):
    """A STAC catalog of two images: ``rome`` has a bbox, ``nowhere`` has none."""

    def get_data_path(self, baseurl: str, urlpath: str, dirpath: str) -> dict:
        name = dirpath.strip("/")
        if not name:
            return {
                "links": [
                    {"rel": "item", "href": f"{baseurl}/{urlpath}/rome", "title": "rome.tif"},
                    {
                        "rel": "item",
                        "href": f"{baseurl}/{urlpath}/nowhere",
                        "title": "nowhere.tif",
                    },
                ]
            }
        return {
            "id": name,
            "type": "Feature",
            "properties": {"datetime": "2026-10-03T00:00:00Z"},
            "assets": {
                "default": {
                    "href": f"{baseurl}/{urlpath}.tif",
                    "type": "image/tiff",
                    "file:size": 430,
                }
            },
            "bbox": list(ROME) if name == "rome" else None,
            "geometry": None,
        }


def with_stac(api_config: dict) -> dict:
    """``api_config`` with ``catalog``, the STAC catalog of the fake source."""
    api_config["resources"]["catalog"] = {
        "type": "stac-collection",
        "title": "Catalog",
        "description": "Two images",
        "keywords": [],
        "links": [],
        "extents": {"spatial": {"bbox": [-180, -90, 180, 90], "crs": CRS84}},
        "providers": [
            {"type": "stac", "name": "tests.html_fixtures.FakeStacProvider", "data": "unused"}
        ],
    }
    return api_config
