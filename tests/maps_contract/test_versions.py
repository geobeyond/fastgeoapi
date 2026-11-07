"""The ETag of a map changes with what the map draws, and only with that."""

import asyncio
import gzip
import io
from unittest.mock import patch

from tests.maps_fixtures import FakeRenderer
from tests.pmtiles_fixtures import write_archive

MAP = "/collections/under_test/map"
SIZE = {"width": 64, "height": 64}
# Around Rome, in EPSG:3857 metres, where land covers the whole map. Opaque,
# so the land is drawn over the white background the pixels are measured on.
ROME = {
    **SIZE,
    "transparent": "false",
    "bbox": "1379000,5140000,1403000,5160000",
    "bbox-crs": "http://www.opengis.net/def/crs/EPSG/0/3857",
}
KEY = "land.pmtiles"
DATA = f"s3://bucket/tiles/{KEY}"
# The default style fills the land layer with #e15759 at 0.3 over white.
OPAQUE = (246, 205, 205)


def _etag(client, path=MAP, **headers) -> str:
    response = client.get(path, params=SIZE, headers=headers)
    assert response.status_code == 200, response.text[:200]
    return response.headers["etag"]


def _share(png: bytes, colour: tuple[int, ...], tolerance: int = 8) -> float:
    from PIL import Image

    data = Image.open(io.BytesIO(png)).convert("RGB").tobytes()
    pixels = [tuple(data[i : i + 3]) for i in range(0, len(data), 3)]
    close = [
        p for p in pixels if all(abs(a - b) <= tolerance for a, b in zip(p, colour, strict=True))
    ]
    return len(close) / len(pixels)


def test_the_same_map_keeps_its_etag(contract):
    assert _etag(contract.client) == _etag(contract.client)


def test_a_map_the_client_has_answers_304(contract):
    etag = _etag(contract.client)

    response = contract.client.get(MAP, params=SIZE, headers={"If-None-Match": etag})

    assert (response.status_code, response.content) == (304, b"")
    assert response.headers["etag"] == etag


def test_another_style_gives_another_etag(contract):
    assert _etag(contract.client) != _etag(
        contract.client, "/collections/under_test/styles/night/map"
    )


def test_another_definition_gives_another_etag(contract):
    first = _etag(contract.client)

    client = contract.open_client(contract.build_definition(max_size=512))

    assert _etag(client) != first


def _drawn_version() -> str:
    """The archive version in the style of the last map the fake renderer drew."""
    url = FakeRenderer.instances[-1].requests[-1].style["sources"]["archive"]["url"]
    return url.rsplit("/", 1)[1]


def test_a_replaced_archive_gives_a_new_etag_with_its_map(contract):
    """A map carries the ETag of the version it was drawn from, even when the data changes.

    Past the TTL the known version answers while the HEAD runs behind. The
    HEAD is held until the route has the version and is about to draw: the
    map is then drawn from the new version, and must not carry the old ETag.
    """
    from app.provider.storage import CachedRanges
    from app.provider.storage.cache import version_of
    from app.provider.storage.loopback import close_range_server
    from tests.range_cache_fixtures import Clock, memory_store, range_cache
    from tests.test_cached_ranges_revalidation import GatedStore

    definition = contract.build_definition()
    definition["data"] = DATA
    client = contract.open_client(definition)
    clock, origin = Clock(), GatedStore(memory_store())
    origin.gate.set()
    origin.put(KEY, contract.archive.read_bytes())
    provider = contract.provider
    cached = CachedRanges(origin, KEY, range_cache(memory_store(), clock=clock), source=DATA)
    provider.cached_ranges = cached
    draw = provider.arender_map

    async def draw_once_the_head_returned(**arguments):
        origin.gate.set()
        while version_of(cached.known_meta()) == old_version:
            await asyncio.sleep(0.01)
        return await draw(**arguments)

    drawn = []
    try:
        old = client.get(MAP, params=ROME)
        old_version = version_of(cached.meta())
        drawn.append(_drawn_version() if contract.records_requests else None)
        empty = write_archive(
            contract.folder / "empty.pmtiles",
            {(0, 0, 0): gzip.compress(b"")},
            metadata={"name": "land", "vector_layers": [{"id": "land"}]},
        )
        origin.gate.clear()
        origin.put(KEY, empty.read_bytes())
        clock.now += 301
        with patch.object(provider, "arender_map", side_effect=draw_once_the_head_returned):
            changed = client.get(MAP, params=ROME)
        drawn.append(_drawn_version() if contract.records_requests else None)
        new = client.get(MAP, params=ROME)
        new_version = version_of(cached.meta())
        drawn.append(_drawn_version() if contract.records_requests else None)
    finally:
        client.portal.call(provider.aclose)
        client.portal.call(close_range_server)

    assert [r.status_code for r in (old, changed, new)] == [200, 200, 200], changed.text[:200]
    assert old_version != new_version
    assert new.headers["etag"] != old.headers["etag"]
    assert changed.headers.get("etag") != old.headers["etag"]
    if contract.records_requests:
        assert drawn == [old_version, new_version, new_version]
    else:
        assert _share(old.content, OPAQUE) > 0.9
        assert _share(changed.content, OPAQUE) < 0.1
        assert _share(new.content, OPAQUE) < 0.1
