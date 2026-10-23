"""From a collection with a PMTiles archive to a tile provider."""

from __future__ import annotations

import io
import json
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

from fastgeoapi_portolan.catalog.testing import PORTOLAN
from fastgeoapi_portolan.handlers import Overrides, Refused
from fastgeoapi_portolan.reader import Collection
from fastgeoapi_portolan.tiles import PROVIDER, pmtiles, style_name

ARCHIVE = "boston-open-space.pmtiles"
PMTILES = "application/vnd.pmtiles"


def _write_archive(path, *, tile_type=TileType.MVT, zooms=(0, 14), metadata=None):
    if metadata is None:
        metadata = {"vector_layers": [{"id": "parks", "minzoom": zooms[0], "maxzoom": zooms[-1]}]}
    header = {
        "tile_type": tile_type,
        "tile_compression": Compression.NONE,
        "min_lon_e7": -710000000,
        "min_lat_e7": 422000000,
        "max_lon_e7": -709000000,
        "max_lat_e7": 424000000,
        "center_zoom": zooms[0],
        "center_lon_e7": -710500000,
        "center_lat_e7": 423000000,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer = Writer(handle)
        for zoom in zooms:
            writer.write_tile(zxy_to_tileid(zoom, 0, 0), b"tile")
        writer.finalize(header, metadata)


def _style(source="boston", archive=f"https://cdn.example.org/{ARCHIVE}"):
    return {
        "version": 8,
        "sources": {
            "basemap": {"type": "raster", "tiles": ["https://tiles.example.org/{z}/{x}/{y}.png"]},
            source: {"type": "vector", "url": f"pmtiles://{archive}"},
        },
        "layers": [],
    }


def _style_asset(href, *roles, **fields):
    return {"href": href, "type": "application/json", "roles": ["style", *roles], **fields}


@pytest.fixture
def folder(tmp_path):
    """The folder of a collection ``roads``, with its archive."""
    folder = tmp_path.resolve() / "roads"
    _write_archive(folder / ARCHIVE)
    return folder


def _collection(folder, *, assets=None, links=(), href=None):
    if assets is None:
        assets = {"tiles": {"href": f"./{ARCHIVE}", "type": PMTILES, "roles": ["visual"]}}
    document = {"type": "Collection", "id": "roads", "assets": assets, "links": list(links)}
    return Collection("roads", href or str(folder / "collection.json"), document, (), PORTOLAN)


def _write_styles(folder, styles):
    for name, style in styles.items():
        path = folder / "styles" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(style))


@pytest.mark.asyncio
async def test_the_visual_asset_or_the_pmtiles_link_is_the_data(folder):
    from_asset = await pmtiles(_collection(folder), Overrides())
    link = {"rel": "pmtiles", "href": f"./{ARCHIVE}", "type": PMTILES}
    from_link = await pmtiles(_collection(folder, assets={}, links=[link]), Overrides())

    assert from_asset.provider["type"] == "tile"
    assert from_asset.provider["name"] == PROVIDER
    assert from_asset.provider["data"] == str(folder / ARCHIVE)
    assert "data: visual asset" in from_asset.choices
    assert from_link.provider["data"] == str(folder / ARCHIVE)
    assert "data: pmtiles link" in from_link.choices


@pytest.mark.asyncio
async def test_a_collection_without_an_archive_is_not_this_handlers(folder):
    parquet = {
        "data": {
            "href": "./roads.parquet",
            "type": "application/vnd.apache.parquet",
            "roles": ["data"],
        }
    }

    assert await pmtiles(_collection(folder, assets=parquet), Overrides()) is None


@pytest.mark.asyncio
async def test_zoom_comes_from_the_vector_layers_before_the_header(folder):
    _write_archive(
        folder / ARCHIVE,
        zooms=(0, 14),
        metadata={"vector_layers": [{"id": "parks", "minzoom": 14, "maxzoom": 14}]},
    )

    provided = await pmtiles(_collection(folder), Overrides())

    assert provided.provider["options"]["zoom"] == {"min": 14, "max": 14}
    assert "zoom: 14-14 (vector_layers)" in provided.choices


@pytest.mark.asyncio
async def test_without_vector_layers_the_zoom_comes_from_the_header(folder):
    _write_archive(folder / ARCHIVE, zooms=(2, 9), metadata={"name": "parks"})

    provided = await pmtiles(_collection(folder), Overrides())

    assert provided.provider["options"]["zoom"] == {"min": 2, "max": 9}
    assert "zoom: 2-9 (header)" in provided.choices


@pytest.mark.parametrize(
    ("tile_type", "expected"),
    [
        (TileType.MVT, {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"}),
        (TileType.PNG, {"name": "png", "mimetype": "image/png"}),
    ],
)
@pytest.mark.asyncio
async def test_the_format_follows_the_tile_type(folder, tile_type, expected):
    _write_archive(folder / ARCHIVE, tile_type=tile_type)

    provided = await pmtiles(_collection(folder), Overrides())

    assert provided.provider["format"] == expected


@pytest.mark.asyncio
async def test_a_tile_type_the_provider_does_not_serve_is_refused(folder):
    _write_archive(folder / ARCHIVE, tile_type=TileType.MLT)

    refused = await pmtiles(_collection(folder), Overrides())

    assert isinstance(refused, Refused)
    assert "MLT" in refused.reason


@pytest.mark.asyncio
async def test_schemes_are_web_mercator(folder):
    provided = await pmtiles(_collection(folder), Overrides())

    assert provided.provider["options"]["schemes"] == ["WebMercatorQuad"]


def test_a_style_is_named_by_its_title_or_its_key():
    assert style_name("default-style", {}) == "default"
    assert style_name("style-by-subtype", {}) == "by-subtype"
    assert style_name("style-by-subtype", {"title": "By subtype"}) == "By subtype"


@pytest.mark.asyncio
async def test_every_style_asset_is_named_and_the_default_leads(folder):
    _write_styles(
        folder, {"by-subtype.json": _style(), "default.json": _style(), "night.json": _style()}
    )
    assets = {
        "tiles": {"href": f"./{ARCHIVE}", "type": PMTILES, "roles": ["visual"]},
        "style-by-subtype": _style_asset("./styles/by-subtype.json"),
        "default-style": _style_asset("./styles/default.json", "default"),
        "night": _style_asset("./styles/night.json", title="Night"),
    }

    provided = await pmtiles(_collection(folder, assets=assets), Overrides())

    options = provided.provider["options"]
    assert list(options["styles"]) == ["default", "by-subtype", "Night"]
    assert options["default_style"] == "default"


class RangeHandler(SimpleHTTPRequestHandler):
    """Answers a ``Range`` request with 206, as the hosts of real archives do."""

    def send_head(self):
        asked = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        path = Path(self.translate_path(self.path))
        if asked is None or not path.is_file():
            return super().send_head()
        data = path.read_bytes()
        start = int(asked[1])
        end = int(asked[2]) if asked[2] else len(data) - 1
        body = data[start : end + 1]
        self.send_response(206)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Range", f"bytes {start}-{start + len(body) - 1}/{len(data)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)


@pytest.fixture
def served(tmp_path):
    """``tmp_path`` over HTTP on loopback, with byte ranges."""
    handler = partial(RangeHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.mark.asyncio
async def test_style_hrefs_are_made_absolute(folder, served):
    _write_styles(folder, {"default.json": _style()})
    assets = {
        "tiles": {"href": f"./{ARCHIVE}", "type": PMTILES, "roles": ["visual"]},
        "default-style": _style_asset("./styles/default.json", "default"),
    }
    collection = _collection(folder, assets=assets, href=f"{served}/roads/collection.json")

    provided = await pmtiles(collection, Overrides())

    assert provided.provider["data"] == f"{served}/roads/{ARCHIVE}"
    assert provided.provider["options"]["styles"] == {
        "default": f"{served}/roads/styles/default.json"
    }


@pytest.mark.asyncio
async def test_the_style_source_is_the_source_that_points_at_the_archive(folder):
    _write_styles(folder, {"default.json": _style("boston")})
    assets = {
        "tiles": {"href": f"./{ARCHIVE}", "type": PMTILES, "roles": ["visual"]},
        "default-style": _style_asset("./styles/default.json", "default"),
    }

    provided = await pmtiles(_collection(folder, assets=assets), Overrides())

    assert provided.provider["options"]["style_source"] == "boston"


@pytest.mark.asyncio
async def test_a_style_naming_the_archive_differently_is_left_out_with_the_reason(folder):
    _write_styles(folder, {"default.json": _style("boston"), "other.json": _style("openspace")})
    assets = {
        "tiles": {"href": f"./{ARCHIVE}", "type": PMTILES, "roles": ["visual"]},
        "default-style": _style_asset("./styles/default.json", "default"),
        "style-other": _style_asset("./styles/other.json"),
    }

    provided = await pmtiles(_collection(folder, assets=assets), Overrides())

    assert list(provided.provider["options"]["styles"]) == ["default"]
    (left_out,) = [choice for choice in provided.choices if "left out" in choice]
    assert "other" in left_out
    assert "openspace" in left_out
    assert "boston" in left_out


@pytest.mark.asyncio
async def test_an_unreadable_archive_header_is_refused_with_the_reason(folder):
    (folder / ARCHIVE).write_bytes(b"not an archive" * 20)

    refused = await pmtiles(_collection(folder), Overrides())
    (folder / ARCHIVE).unlink()
    missing = await pmtiles(_collection(folder), Overrides())

    assert isinstance(refused, Refused)
    assert "header" in refused.reason
    assert isinstance(missing, Refused)
    assert "does not exist" in missing.reason


@pytest.mark.asyncio
async def test_styles_that_cannot_draw_the_archive_are_left_out_with_the_reason(folder):
    _write_styles(folder, {"default.json": _style(), "basemap.json": {"version": 8, "sources": {}}})
    (folder / "styles" / "broken.json").write_text("not JSON")
    assets = {
        "tiles": {"href": f"./{ARCHIVE}", "type": PMTILES, "roles": ["visual"]},
        "default-style": _style_asset("./styles/default.json", "default"),
        "missing-style": _style_asset("./styles/missing.json"),
        "broken-style": _style_asset("./styles/broken.json"),
        "basemap-style": _style_asset("./styles/basemap.json"),
    }

    provided = await pmtiles(_collection(folder, assets=assets), Overrides())

    assert list(provided.provider["options"]["styles"]) == ["default"]
    assert "styles: missing left out: it could not be read: it does not exist" in provided.choices
    assert "styles: broken left out: it is not JSON" in provided.choices
    assert "styles: basemap left out: none of its sources reads the archive" in provided.choices


@pytest.mark.asyncio
async def test_two_styles_with_one_name_keep_the_first(folder):
    _write_styles(folder, {"a.json": _style(), "b.json": _style()})
    assets = {
        "tiles": {"href": f"./{ARCHIVE}", "type": PMTILES, "roles": ["visual"]},
        "a": _style_asset("./styles/a.json", title="Day"),
        "b": _style_asset("./styles/b.json", title="Day"),
    }

    provided = await pmtiles(_collection(folder, assets=assets), Overrides())

    assert provided.provider["options"]["styles"] == {"Day": str(folder / "styles" / "a.json")}
    assert "styles: Day left out: another style has the name" in provided.choices


@pytest.mark.asyncio
async def test_store_options_reach_the_provider(folder):
    provided = await pmtiles(_collection(folder), Overrides(store_options={"region": "eu-west-1"}))

    assert provided.provider["store_options"] == {"region": "eu-west-1"}
