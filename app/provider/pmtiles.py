"""Tiles from a PMTiles archive, read by ranges wherever it lives (ADR-0011).

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

from pmtiles.tile import (
    Compression,
    Entry,
    deserialize_directory,
    deserialize_header,
    find_tile,
    zxy_to_tileid,
)
from pygeoapi.provider.base import ProviderQueryError

from app.provider.pmtiles_types import MEDIA_TYPES
from app.provider.sansio import Core, drive, drive_sync
from app.provider.storage import ByteRanges, ObjectChangedError
from app.provider.tiles import TilesProvider
from app.tiles.contract import (
    TileContent,
    TileOutsideError,
    VectorLayer,
    data_type_for,
    format_parameter,
)
from app.tiles.sources import TileSourceContext

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


@dataclass(frozen=True)
class _Opened:
    """An archive read at one version of its object, with the reads pinned to that version."""

    archive: Archive
    ranges: ByteRanges
    etag: str | None


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


class PMTilesTiles:
    """The tiles of one PMTiles archive, read by ranges wherever it lives.

    Each tile costs one ranged read once the directory it sits in is
    cached. The header, root, metadata and leaf caches live as long as the
    source; through the range cache they follow the archive's version, and
    a changed archive is opened again.
    """

    format = "pmtiles"

    def __init__(self, context: TileSourceContext) -> None:
        """No I/O: the archive is opened at the first read."""
        self._context = context
        self.inline_inflate_limit = int(
            context.options.get("inline_inflate_limit", INLINE_INFLATE_LIMIT)
        )
        self._leaves = LeafCache(maxsize=int(context.options.get("leaf_cache", 256)))
        self._ranges: ByteRanges | None = None
        self._archive: Archive | None = None
        self._opened: _Opened | None = None
        self._lock = threading.Lock()

    # -- the archive, known once ---------------------------------------------

    def _shared_ranges(self) -> ByteRanges:
        # Concurrent identical reads (a cold burst wanting the same
        # directories) share one fetch through these.
        if self._ranges is None:
            with self._lock:
                if self._ranges is None:
                    self._ranges = self._context.ranges()
        return self._ranges

    def _archive_sync(self) -> Archive:
        if self._archive is None:
            # Taken before the lock: _shared_ranges takes the same lock.
            ranges = self._shared_ranges()
            with self._lock:
                if self._archive is None:
                    self._archive = drive_sync(open_archive(self._leaves), ranges)
        return self._archive

    async def _archive_async(self) -> Archive:
        if self._archive is None:
            archive = await drive(open_archive(self._leaves), self._shared_ranges())
            with self._lock:
                if self._archive is None:
                    self._archive = archive
        return self._archive

    def _open_sync(self) -> tuple[Archive, ByteRanges]:
        """The archive and the reads that match it, opened again when the object changes."""
        cached = self._context.cached()
        if cached is None:
            return self._archive_sync(), self._shared_ranges()
        meta = cached.meta()
        opened = self._opened
        if opened is None or opened.etag != meta.etag:
            ranges = cached.at(meta)
            archive = drive_sync(open_archive(self._fresh_leaves()), ranges)
            opened = _Opened(archive, ranges, meta.etag)
            with self._lock:
                self._opened = opened
        return opened.archive, opened.ranges

    async def _open_async(self) -> tuple[Archive, ByteRanges]:
        """Async twin of :meth:`_open_sync`."""
        cached = self._context.cached()
        if cached is None:
            return await self._archive_async(), self._shared_ranges()
        meta = await cached.ameta()
        opened = self._opened
        if opened is None or opened.etag != meta.etag:
            ranges = cached.at(meta)
            archive = await drive(open_archive(self._fresh_leaves()), ranges)
            opened = _Opened(archive, ranges, meta.etag)
            with self._lock:
                self._opened = opened
        return opened.archive, opened.ranges

    def _fresh_leaves(self) -> LeafCache:
        # Leaf offsets belong to one version of the archive.
        return LeafCache(maxsize=self._leaves.maxsize)

    # -- the tile source --------------------------------------------------------

    def content(self) -> TileContent:
        """What the archive holds, from its header and metadata."""
        archive, _ = self._open_sync()
        return self._describe(archive)

    async def acontent(self) -> TileContent:
        """Async twin of :meth:`content`."""
        archive, _ = await self._open_async()
        return self._describe(archive)

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        """The tile bytes, decompressed."""
        try:
            return self._tile_sync(z, x, y)
        except ObjectChangedError:
            # The archive changed under the version being read: read the tile from the new one.
            return self._tile_sync(z, x, y)

    async def atile(self, z: int, x: int, y: int) -> bytes | None:
        """The same tile, awaited; big tiles are inflated in a worker to keep the loop free."""
        try:
            return await self._tile_async(z, x, y)
        except ObjectChangedError:
            return await self._tile_async(z, x, y)

    def _tile_sync(self, z: int, x: int, y: int) -> bytes | None:
        archive, ranges = self._open_sync()
        entry = drive_sync(locate(archive, _tile_id(archive, z, x, y)), ranges)
        if entry is None:
            return None
        raw = drive_sync(read_tile(archive, entry), ranges)
        return inflate(raw, archive.header["tile_compression"])

    async def _tile_async(self, z: int, x: int, y: int) -> bytes | None:
        archive, ranges = await self._open_async()
        entry = await drive(locate(archive, _tile_id(archive, z, x, y)), ranges)
        if entry is None:
            return None
        raw = await drive(read_tile(archive, entry), ranges)
        compression = archive.header["tile_compression"]
        if len(raw) > self.inline_inflate_limit:
            return await self._context.offload(inflate, raw, compression)
        return inflate(raw, compression)

    def _describe(self, archive: Archive) -> TileContent:
        header, metadata = archive.header, archive.metadata
        media_type = MEDIA_TYPES[header["tile_type"]][0]
        low, high = zoom_limits(archive)
        return TileContent(
            data_type=data_type_for(media_type, self._context.dem),
            media_type=media_type,
            format_parameter=format_parameter(media_type),
            min_zoom=low,
            max_zoom=high,
            bounds=(
                _degrees(header["min_lon_e7"]),
                _degrees(header["min_lat_e7"]),
                _degrees(header["max_lon_e7"]),
                _degrees(header["max_lat_e7"]),
            ),
            center=(
                _degrees(header["center_lon_e7"]),
                _degrees(header["center_lat_e7"]),
                header["center_zoom"],
            ),
            name=metadata.get("name"),
            description=metadata.get("description"),
            attribution=metadata.get("attribution"),
            layers=tuple(
                VectorLayer(
                    id=layer["id"],
                    description=layer.get("description"),
                    minzoom=layer.get("minzoom"),
                    maxzoom=layer.get("maxzoom"),
                    fields=layer.get("fields", {}),
                )
                for layer in metadata.get("vector_layers", [])
                if "id" in layer
            ),
            dem=self._context.dem,
        )


def _tile_id(archive: Archive, z: int, x: int, y: int) -> int:
    """The tile id of z/x/y; outside the archive's zooms is :class:`TileOutsideError`."""
    low, high = zoom_limits(archive)
    if not low <= z <= high:
        raise TileOutsideError(f"tile {z}/{x}/{y} is outside the archive's zooms {low}-{high}")
    return zxy_to_tileid(z, x, y)


class PMTilesProvider(TilesProvider):
    """Tiles from a PMTiles archive on local disk or object storage.

    Configuration::

        - type: tile
          name: app.provider.pmtiles.PMTilesProvider
          data: s3://overturemaps-extras-us-west-2/tiles/2026-08-19.0/places.pmtiles
          store_options: {region: us-west-2, skip_signature: true}
          options: {zoom: {min: 14, max: 14}, schemes: [WebMercatorQuad]}
          format: {name: pbf, mimetype: application/vnd.mapbox-vector-tile}
    """

    source_builder = PMTilesTiles
