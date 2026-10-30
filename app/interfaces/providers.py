"""Provider capability Protocols (ADR-0010).

pygeoapi's provider contract is synchronous and per family. These
Protocols describe the *asynchronous* capability a provider may add,
again per family, and are what the router checks::

    isinstance(p, AsyncTileProvider) and p.native_async

Conformance is structural: any object with these members qualifies,
whether or not it inherits from fastgeoapi's mixin.

pygeoapi builds every provider with ``cls(provider_def)``, from one
untyped dict. None of these Protocols says how a provider is built; they
describe the built instance.
"""

from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, runtime_checkable


@runtime_checkable
class AsyncTileProvider(Protocol):
    """A tile provider that can be awaited for tile data.

    Attributes
    ----------
    native_async
        ``True`` only when ``aget_tiles`` awaits its I/O for real.
    format_type
        The configured tile format name (``format.name`` in the
        provider definition), passed back as ``format_``.
    """

    native_async: ClassVar[bool]
    format_type: str

    def get_layer(self) -> Any:
        """The layer name pygeoapi passes to ``get_tiles``."""
        ...

    async def aget_tiles(
        self,
        layer: Any,
        tileset: str,
        z: int | str,
        y: int | str,
        x: int | str,
        format_: str,
    ) -> bytes | None:
        """The tile bytes, ``None`` when the tile is absent within limits."""
        ...


@runtime_checkable
class AsyncFeatureProvider(Protocol):
    """A feature provider that can be awaited for queries and single items."""

    native_async: ClassVar[bool]

    async def aquery(self, **kwargs: Any) -> dict:
        """The async twin of ``query``: same keyword arguments, same GeoJSON result."""
        ...

    async def aget(self, identifier: Any, **kwargs: Any) -> dict:
        """The async twin of ``get``."""
        ...


@dataclass(frozen=True)
class MapLimits:
    """What a map provider accepts and how many maps it draws at once.

    Attributes
    ----------
    max_width
        The largest ``width`` of a map, in pixels.
    max_height
        The largest ``height`` of a map, in pixels.
    max_pixels
        The largest ``width * height`` a map may have. None sets no limit on
        the product, so a map within ``max_width`` and ``max_height`` is
        accepted whatever its area.
    concurrent
        How many maps the provider draws at the same time.
    waiting
        How many more maps may wait while those are drawn.
    timeout
        How many seconds a map may take, waiting included.
    """

    max_width: int
    max_height: int
    max_pixels: int | None
    concurrent: int
    waiting: int
    timeout: float


@runtime_checkable
class AsyncMapProvider(Protocol):
    """A map provider that can be awaited for a rendered map.

    The contract cannot type the definition the provider is built from, so
    it types what the provider makes of it: ``limits`` says which sizes it
    accepts and how many maps it draws at once.

    Attributes
    ----------
    native_async
        ``True`` only when ``aquery`` awaits its work for real. The route
        then awaits it on the event loop instead of calling ``query`` in the
        threadpool. A configuration is refused when its provider class sets
        it and misses a member of this Protocol.
    """

    native_async: ClassVar[bool]

    @property
    def limits(self) -> MapLimits:
        """The sizes it accepts and the maps it draws at once."""
        ...

    async def aquery(
        self,
        *,
        style: str | None,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
        crs: str,
        transparent: bool,
        format_: str,
        **kwargs: Any,
    ) -> bytes:
        """Draw the map and return the image, encoded as ``format_``.

        Parameters
        ----------
        style
            The name of a configured style, from the ``{styleId}`` of
            ``/collections/{collectionId}/styles/{styleId}/map``, or None for
            the default one (/req/styled-map/map-operation).
        bbox
            ``(xmin, ymin, xmax, ymax)`` in ``crs``; ``xmin > xmax`` means
            that the box crosses the antimeridian
            (/req/spatial-subsetting/bbox-definition).
        width
            The width of the image in pixels, a positive integer
            (/req/scaling/width-definition).
        height
            The height of the image in pixels, a positive integer
            (/req/scaling/height-definition).
        crs
            The URI of the CRS the map is drawn in; ``bbox`` arrives in it
            (/req/crs/crs-definition).
        transparent
            Whether the background is transparent
            (/req/background/transparent-definition).
        format_
            The format the client asked for with ``f``; maps are drawn as
            PNG (/req/png/content).
        **kwargs
            The other arguments pygeoapi passes: ``datetime_``
            (/req/datetime/datetime-definition) and ``subsets`` on the
            additional dimensions (/req/general-subsetting/subset-definition).

        Raises
        ------
        ProviderItemNotFoundError
            For a ``style`` the provider does not know; the route answers 404.
        ProviderGenericError
            When the engine fails; the route answers 500.
        """
        ...

    async def aversion(
        self,
        *,
        style: str | None,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
        crs: str,
        transparent: bool,
        format_: str,
        **kwargs: Any,
    ) -> str | None:
        """The version of the map ``aquery`` would draw, without drawing it.

        The route builds the response's ``ETag`` from it (RFC 9110, section
        8.8.3) and answers 304 to an ``If-None-Match`` that names that
        ``ETag`` (RFC 9110, section 13.1.2). So the version changes whenever the image for these
        arguments can change: the data, the definition, the style or the
        engine. It reads metadata only. A map served under a version is drawn
        from the data that version names, so a provider whose reads are not
        pinned to one version returns None, and the map gets no ``ETag``.

        Parameters
        ----------
        style
            The name of a configured style, from the ``{styleId}`` of
            ``/collections/{collectionId}/styles/{styleId}/map``, or None for
            the default one (/req/styled-map/map-operation).
        bbox
            ``(xmin, ymin, xmax, ymax)`` in ``crs``; ``xmin > xmax`` means
            that the box crosses the antimeridian
            (/req/spatial-subsetting/bbox-definition).
        width
            The width of the image in pixels, a positive integer
            (/req/scaling/width-definition).
        height
            The height of the image in pixels, a positive integer
            (/req/scaling/height-definition).
        crs
            The URI of the CRS the map is drawn in; ``bbox`` arrives in it
            (/req/crs/crs-definition).
        transparent
            Whether the background is transparent
            (/req/background/transparent-definition).
        format_
            The format the client asked for with ``f``; maps are drawn as
            PNG (/req/png/content).
        **kwargs
            The other arguments pygeoapi passes: ``datetime_``
            (/req/datetime/datetime-definition) and ``subsets`` on the
            additional dimensions (/req/general-subsetting/subset-definition).

        Returns
        -------
        str or None
            The version, or None when the version of the data is unknown.
        """
        ...

    def close(self) -> None:
        """Release the engine once the maps it is drawing are done.

        On a reload the plugin cache calls it from the thread that handles
        the reload, while the old configuration may still be serving maps
        with this instance. So it must be safe to call from any thread,
        return without waiting for those maps, and do nothing on a second
        call. An error it raises is logged and does not stop the reload.
        """
        ...


NATIVE_MAP_MEMBERS: tuple[str, ...] = ("aquery", "aversion", "limits", "close")
"""The members a map provider class with ``native_async`` must define."""


@runtime_checkable
class VersionedProvider(Protocol):
    """A provider that tells which version of its answer a request would get.

    The tile and map routes ask for it before doing any work for the
    request. The HTTP cache builds the response's ``ETag`` from it (RFC
    9110, section 8.8.3) and answers 304 to an ``If-None-Match`` that names
    that ``ETag`` (RFC 9110, section 13.1.2). A provider without
    ``aversion`` gets no cache headers.
    """

    async def aversion(self, **kwargs: Any) -> str | None:
        """The version of the answer to these arguments, without computing the answer.

        It changes whenever the answer can change, and it reads metadata
        only: neither the tiles nor the data a map is drawn from.

        Parameters
        ----------
        **kwargs
            The arguments of the provider's data method: those of
            ``aget_tiles`` for a tile provider, those of ``aquery`` for a map
            provider.

        Returns
        -------
        str or None
            The version, or None when it is unknown; the answer then gets no
            cache headers.
        """
        ...
