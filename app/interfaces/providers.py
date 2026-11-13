"""Provider capability Protocols (ADR-0010).

pygeoapi's provider contract is synchronous and per family. These
Protocols describe the *asynchronous* capability a provider may add,
again per family, and are what the router checks::

    isinstance(p, AsyncTileProvider) and p.native_async

Conformance is structural: any object with these members qualifies,
whether or not it inherits from fastgeoapi's mixin.
"""

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


@runtime_checkable
class AsyncMapProvider(Protocol):
    """A map provider that can be awaited for a rendered map."""

    native_async: ClassVar[bool]

    async def aquery(self, **kwargs: Any) -> bytes:
        """The async twin of ``query``: same keyword arguments, the image bytes."""
        ...


@runtime_checkable
class VersionedProvider(Protocol):
    """A provider that tells which version of its answer a request would get.

    The HTTP cache builds its ETag from that version before any work is
    done for the request.
    """

    async def aversion(self, **kwargs: Any) -> str | None:
        """A string that changes whenever the answer to ``kwargs`` changes; None when unknown.

        Takes the arguments of the provider's data method, and neither draws
        nor reads data to answer.
        """
        ...
