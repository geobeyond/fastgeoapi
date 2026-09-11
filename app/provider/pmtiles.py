"""OGC API Tiles from a PMTiles archive, read by ranges wherever it lives (ADR-0011).

An archive is a header (127 bytes), a root directory, a metadata JSON,
leaf directories and the tiles, all addressable by offset: it is served
straight from the object store, one ranged read per piece. The parsing
comes from the `pmtiles` library's pure functions; the lookup is ours,
because the library's reader re-reads the root at every depth, four
times on a miss, and keeps no cache.
"""

from __future__ import annotations

import gzip
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, ClassVar

from pmtiles.tile import (
    Compression,
    Entry,
    deserialize_directory,
    deserialize_header,
    find_tile,
    zxy_to_tileid,
)
from pygeoapi.models.provider.base import LinkType, TileMatrixSetEnum, TileSetMetadata
from pygeoapi.models.provider.mvt import MVTTilesJson
from pygeoapi.provider.base import ProviderQueryError
from pygeoapi.provider.base_mvt import BaseMVTProvider
from pygeoapi.provider.tile import ProviderTileNotFoundError
from pygeoapi.util import url_join

from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from app.provider.sansio import Core, drive, drive_sync
from app.provider.storage import SingleFlightRanges

HEADER_LENGTH = 127
"""The fixed size of a PMTiles v3 header, at offset 0."""

MAX_DIRECTORY_DEPTH = 4
"""The format's maximum nesting of leaf directories."""


class LeafCache:
    """Decoded leaf directories by offset, least recently used first out.

    Entries are immutable lists, so one instance is shared between the
    threadpool and the event loop; only the map itself is locked.
    """

    def __init__(self, maxsize: int = 256) -> None:
        self.maxsize = maxsize
        self._items: OrderedDict[int, list[Entry]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, offset: int) -> list[Entry] | None:
        """The leaf at ``offset``, marked as recently used."""
        with self._lock:
            entries = self._items.get(offset)
            if entries is not None:
                self._items.move_to_end(offset)
            return entries

    def put(self, offset: int, entries: list[Entry]) -> list[Entry]:
        """Remember the leaf at ``offset``, evicting the oldest beyond ``maxsize``."""
        with self._lock:
            self._items[offset] = entries
            self._items.move_to_end(offset)
            while len(self._items) > self.maxsize:
                self._items.popitem(last=False)
        return entries


@dataclass
class Archive:
    """What one archive costs to know once: header, root and metadata, plus its leaf cache."""

    header: dict
    root: list[Entry]
    metadata: dict
    leaves: LeafCache


def inflate(data: bytes, compression: Compression) -> bytes:
    """Decompress tile or metadata bytes; gzip is what every writer produces."""
    if compression in (Compression.NONE, Compression.UNKNOWN):
        return data
    if compression == Compression.GZIP:
        return gzip.decompress(data)
    raise ProviderQueryError(f"PMTiles compression {compression.name} is not supported")


def zoom_limits(archive: Archive) -> tuple[int, int]:
    """Zoom range from the metadata's vector layers, the header as a fallback.

    Overture's ``places`` header says 0-14 while the archive holds zoom
    14 only; its ``vector_layers`` say 14-14. The layers tell the truth.
    """
    layers = [
        layer
        for layer in archive.metadata.get("vector_layers", [])
        if "minzoom" in layer and "maxzoom" in layer
    ]
    if layers:
        return (
            min(layer["minzoom"] for layer in layers),
            max(layer["maxzoom"] for layer in layers),
        )
    return archive.header["min_zoom"], archive.header["max_zoom"]


def open_archive(leaves: LeafCache) -> Core[Archive]:
    """Header, root directory and metadata: three reads, once per instance."""
    header = deserialize_header((yield (0, HEADER_LENGTH)))
    if header["internal_compression"] != Compression.GZIP:
        raise ProviderQueryError(
            "PMTiles directories must be gzip-compressed; "
            f"this archive declares {header['internal_compression'].name}"
        )
    # The library inflates gzip directories itself: hand it the raw bytes.
    root = deserialize_directory((yield (header["root_offset"], header["root_length"])))
    metadata: dict = {}
    if header["metadata_length"]:
        raw = yield (header["metadata_offset"], header["metadata_length"])
        metadata = json.loads(inflate(raw, header["internal_compression"]))
    return Archive(header, root, metadata, leaves)  # ruff: ignore[return-in-generator]


def locate(archive: Archive, tile_id: int) -> Core[Entry | None]:
    """The entry for ``tile_id``, descending leaf directories; no read is ever repeated."""
    entries = archive.root
    for _ in range(MAX_DIRECTORY_DEPTH):
        entry = find_tile(entries, tile_id)
        if entry is None or entry.run_length > 0:
            return entry
        leaf = archive.leaves.get(entry.offset)
        if leaf is None:
            raw = yield (archive.header["leaf_directory_offset"] + entry.offset, entry.length)
            leaf = archive.leaves.put(entry.offset, deserialize_directory(raw))
        entries = leaf
    return None  # ruff: ignore[return-in-generator]


def read_tile(archive: Archive, entry: Entry) -> Core[bytes]:
    """The compressed tile bytes for ``entry``: one read."""
    return (yield (archive.header["tile_data_offset"] + entry.offset, entry.length))  # ruff: ignore[return-in-generator]


INLINE_INFLATE_LIMIT = 256 * 1024
"""Compressed bytes above which the async face inflates in a worker thread."""


def _degrees(e7: int) -> float:
    return e7 / 1e7


def _service_url(server_url: str, dataset: str, tileset: str) -> str:
    return url_join(
        server_url,
        f"collections/{dataset}/tiles/{tileset}/{{tileMatrix}}/{{tileRow}}/{{tileCol}}?f=mvt",
    )


class PMTilesProvider(AsyncProviderMixin, StorageBackedMixin, BaseMVTProvider):
    """Vector tiles from a PMTiles archive on local disk or object storage.

    Natively asynchronous: the tile route awaits it, and each tile costs
    one ranged read once the directory it sits in is cached. The
    synchronous face is the same core driven by blocking reads, for
    pygeoapi's own chain. ``THREAD_SAFE`` keeps one instance alive,
    which is what makes the header, root and leaf caches worth having.

    Configuration::

        - type: tile
          name: app.provider.pmtiles.PMTilesProvider
          data: s3://overturemaps-extras-us-west-2/tiles/2026-08-19.0/places.pmtiles
          store_options: {region: us-west-2, skip_signature: true}
          options: {zoom: {min: 14, max: 14}, schemes: [WebMercatorQuad]}
          format: {name: pbf, mimetype: application/vnd.mapbox-vector-tile}
    """

    THREAD_SAFE: ClassVar[bool] = True
    native_async: ClassVar[bool] = True

    def __init__(self, provider_def: dict) -> None:
        super().__init__(provider_def)
        # Building the store contacts no network; the archive is read on
        # the first request, never here (pygeoapi instantiates every tile
        # provider while it generates the OpenAPI document). Concurrent
        # identical reads (a cold burst wanting the same directories)
        # share one fetch.
        self.ranges = SingleFlightRanges(self.byte_ranges())
        self.inline_inflate_limit = int(
            self.options.get("inline_inflate_limit", INLINE_INFLATE_LIMIT)
        )
        self._leaves = LeafCache(maxsize=int(self.options.get("leaf_cache", 256)))
        self._archive: Archive | None = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        """The archive this provider serves."""
        return f"<PMTilesProvider> {self.data}"

    # -- the archive, known once -----------------------------------------------

    def _archive_sync(self) -> Archive:
        if self._archive is None:
            with self._lock:
                if self._archive is None:
                    self._archive = drive_sync(open_archive(self._leaves), self.ranges)
        return self._archive

    async def _archive_async(self) -> Archive:
        if self._archive is None:
            archive = await drive(open_archive(self._leaves), self.ranges)
            with self._lock:
                if self._archive is None:
                    self._archive = archive
        return self._archive

    def _tile_id_within_limits(self, archive: Archive, z: Any, x: Any, y: Any) -> int:
        """Pygeoapi's semantics: outside the limits is 404, inside but absent is 204.

        Non-numeric coordinates (a URL template pasted literally) count as
        outside the limits, as pygeoapi's own ``is_in_limits`` treats them,
        rather than crashing the request.
        """
        try:
            z, x, y = int(z), int(x), int(y)
        except (TypeError, ValueError):
            raise ProviderTileNotFoundError(  # ruff: ignore[raise-without-from-inside-except]
                f"tile coordinates {z}/{x}/{y} are not numbers"
            )
        low, high = zoom_limits(archive)
        scheme = TileMatrixSetEnum.WEBMERCATORQUAD.value
        if not (low <= z <= high) or not self.is_in_limits(scheme, z, x, y):
            raise ProviderTileNotFoundError(f"tile {z}/{x}/{y} is outside the archive limits")
        return zxy_to_tileid(z, x, y)

    # -- the two faces -----------------------------------------------------------

    def get_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        """The tile bytes, decompressed; pygeoapi's synchronous contract."""
        archive = self._archive_sync()
        tile_id = self._tile_id_within_limits(archive, z, x, y)
        entry = drive_sync(locate(archive, tile_id), self.ranges)
        if entry is None:
            return None
        raw = drive_sync(read_tile(archive, entry), self.ranges)
        return inflate(raw, archive.header["tile_compression"])

    async def aget_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        """The same tile, awaited; big tiles are inflated in a worker to keep the loop free.

        Same signature as ``get_tiles``, defaults included, so
        ``async_view`` can call either face with the same keywords.
        """
        archive = await self._archive_async()
        tile_id = self._tile_id_within_limits(archive, z, x, y)
        entry = await drive(locate(archive, tile_id), self.ranges)
        if entry is None:
            return None
        raw = await drive(read_tile(archive, entry), self.ranges)
        compression = archive.header["tile_compression"]
        if len(raw) > self.inline_inflate_limit:
            return await self.run_sync(inflate, raw, compression)
        return inflate(raw, compression)

    # -- what pygeoapi asks besides tiles ---------------------------------------

    def get_layer(self):
        """The layer name: the archive's file stem, like the tippecanoe provider's directory."""
        return PurePosixPath(self.object_key).stem

    def get_fields(self):
        """Tiles carry no queryable fields."""
        return {}

    def get_tiling_schemes(self):
        """PMTiles is z/x/y in Web Mercator by construction."""
        return [TileMatrixSetEnum.WEBMERCATORQUAD.value]

    def get_tiles_service(self, baseurl=None, servicepath=None, dirpath=None, tile_type=None):
        """The links pygeoapi lists under ``/tiles``; the base method returns None."""
        self._service_url = servicepath
        return self.get_tms_links()

    def _tilejson(self, dataset: str, server_url: str, tileset: str) -> dict:
        archive = self._archive_sync()
        header, metadata = archive.header, archive.metadata
        low, high = zoom_limits(archive)
        bounds = (
            header["min_lon_e7"],
            header["min_lat_e7"],
            header["max_lon_e7"],
            header["max_lat_e7"],
        )
        center = (header["center_lon_e7"], header["center_lat_e7"])
        # pygeoapi's layer model wants every key present; archives written
        # by planetiler or tippecanoe may omit `description` or `fields`.
        layers = [
            {
                "id": layer["id"],
                "description": layer.get("description"),
                "minzoom": layer.get("minzoom"),
                "maxzoom": layer.get("maxzoom"),
                "fields": layer.get("fields", {}),
            }
            for layer in metadata.get("vector_layers", [])
            if "id" in layer
        ]
        # pygeoapi's TileJSON model carries bounds, center and tiles as strings.
        content = MVTTilesJson(
            tilejson="3.0.0",
            name=metadata.get("name", dataset),
            description=metadata.get("description"),
            attribution=metadata.get("attribution"),
            tiles=_service_url(server_url, dataset, tileset),
            minzoom=low,
            maxzoom=high,
            bounds=",".join(str(_degrees(value)) for value in bounds),
            center=",".join(
                [*(str(_degrees(value)) for value in center), str(header["center_zoom"])]
            ),
            vector_layers=layers,
        )
        return content.model_dump(exclude_none=True)

    def get_vendor_metadata(
        self, dataset, server_url, layer, tileset, title, description, keywords, **kwargs
    ):
        """TileJSON, from the archive's own metadata and header."""
        return self._tilejson(dataset, server_url, tileset)

    def get_default_metadata(
        self, dataset, server_url, layer, tileset, title, description, keywords, **kwargs
    ):
        """OGC tileset metadata, in the shape of the tippecanoe provider's."""
        scheme = next((s for s in self.get_tiling_schemes() if s.tileMatrixSet == tileset), None)
        if scheme is None:
            raise ProviderTileNotFoundError(f"tile matrix set {tileset} is not served")
        content = TileSetMetadata(
            title=title,
            description=description,
            keywords=keywords,
            crs=scheme.crs,
            tileMatrixSetURI=scheme.tileMatrixSetURI,
        )
        content.links = [
            LinkType(
                **{
                    "href": url_join(server_url, f"/TileMatrixSets/{scheme.tileMatrixSet}"),
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/tiling-scheme",
                    "type": "application/json",
                    "title": f"{scheme.tileMatrixSet} tile matrix set definition",
                }
            ),
            LinkType(
                **{
                    "href": _service_url(server_url, dataset, tileset),
                    "rel": "item",
                    "type": self.mimetype,
                    "title": f"{tileset} vector tiles for {layer}",
                }
            ),
        ]
        return content.model_dump(exclude_none=True, by_alias=True)

    def get_html_metadata(
        self, dataset, server_url, layer, tileset, title, description, keywords, **kwargs
    ):
        """What the HTML template renders: the TileJSON plus the URLs around it."""
        metadata_url = url_join(server_url, f"collections/{dataset}/tiles/{tileset}/metadata")
        return {
            "id": dataset,
            "title": title,
            "tileset": tileset,
            "collections_path": _service_url(server_url, dataset, tileset),
            "json_url": f"{metadata_url}?f=json",
            "tilejson_url": f"{metadata_url}?f=tilejson",
            "metadata": self._tilejson(dataset, server_url, tileset),
        }
