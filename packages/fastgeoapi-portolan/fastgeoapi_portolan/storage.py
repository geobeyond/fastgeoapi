"""Where the documents and files of a catalog live, and how they are read.

A catalog can sit on a local disk, behind http(s) or in a bucket. The
reader names every place with a single string and leaves the backend to
this module. ``store_options`` use the vocabulary of a fastgeoapi
configuration, which is DuckDB's, and are translated here for obstore,
the same way fastgeoapi translates them when it serves the data.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import obstore
from obstore.exceptions import BaseError
from obstore.store import LocalStore, from_url

from fastgeoapi_portolan.catalog.locations import is_url
from fastgeoapi_portolan.catalog.protocols import MAX_DOCUMENT_BYTES

_HTTP = ("http://", "https://")
# The variables obstore reads an endpoint from, in every constructor.
_ENDPOINT_VARIABLES = ("AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL", "AWS_ENDPOINT")
_environment_lock = threading.Lock()


def _virtual_hosted(endpoint: str, base: str) -> str:
    """Put the bucket in the host of a virtual-hosted endpoint.

    DuckDB takes the service's host and adds the bucket itself; obstore
    uses the endpoint exactly as given. An endpoint that already names the
    bucket is left alone rather than doubled.
    """
    bucket = base.split("://", 1)[-1].split("/", 1)[0]
    scheme, _, host = endpoint.rpartition("://")
    if not bucket or host.startswith(f"{bucket}."):
        return endpoint
    return f"{scheme}://{bucket}.{host}" if scheme else f"{bucket}.{host}"


def to_obstore_config(store_options: Mapping[str, Any] | None, base: str = "") -> dict[str, Any]:
    """``store_options`` spelled the way obstore expects them.

    obstore refuses a key it does not know, so an untranslated
    ``key_id`` makes a readable bucket look unreachable. ``allow_http``
    goes in the client options: obstore panics when it finds it in the
    store configuration.
    """
    options = dict(store_options or {})
    translated: dict[str, Any] = {}
    for name, obstore_name in (("key_id", "access_key_id"), ("secret", "secret_access_key")):
        if name in options:
            translated[obstore_name] = options.pop(name)

    url_style = options.pop("url_style", None)
    if url_style is not None:
        translated["virtual_hosted_style_request"] = url_style != "path"

    use_ssl = options.pop("use_ssl", True)
    endpoint = options.pop("endpoint", None)
    if endpoint is not None:
        scheme = "https" if use_ssl else "http"
        endpoint = endpoint if "://" in str(endpoint) else f"{scheme}://{endpoint}"
        if translated.get("virtual_hosted_style_request"):
            endpoint = _virtual_hosted(endpoint, base)
        translated["endpoint"] = endpoint

    return {**options, **translated}


@contextmanager
def _explicit_endpoint_wins(config: Mapping[str, Any]) -> Generator[None, None, None]:
    """Hide the environment's endpoint while a store with its own is built.

    obstore reads the standard variables in every constructor and lets the
    endpoint found there win over the one in the configuration. A
    process whose ``AWS_ENDPOINT_URL_S3`` names its own service would then
    ask that service for a public catalog on AWS. The variables are hidden
    only while the constructor runs; credentials stay visible.
    """
    if "endpoint" not in config:
        yield
        return
    with _environment_lock:
        hidden = {name: os.environ.pop(name) for name in _ENDPOINT_VARIABLES if name in os.environ}
        try:
            yield
        finally:
            os.environ.update(hidden)


def store_and_key(location: str, store_options: Mapping[str, Any] | None) -> tuple[Any, str]:
    """The store that holds ``location``, and the key of the object in it.

    Bucket options never reach an http(s) store, which refuses any; a
    catalog in a bucket may well link a style at an https URL. A plain
    ``http://`` location was written that way on purpose, so the store
    accepts it.
    """
    if not is_url(location):
        return LocalStore(), str(Path(location).absolute())
    base, _, key = location.rpartition("/")
    if location.startswith(_HTTP):
        return from_url(base, client_options={"allow_http": location.startswith("http://")}), key
    if not store_options:
        return from_url(base), key
    config = to_obstore_config(store_options, base)
    # An endpoint written with `use_ssl: false` is plain http on purpose.
    plain_http = str(config.get("endpoint", "")).startswith("http://")
    client_options = {"allow_http": True} if plain_http else None
    with _explicit_endpoint_wins(config):
        # ty: `from_url` is overloaded per provider config type; this one is
        # a plain mapping, known only at runtime.
        return (
            from_url(base, config=config, client_options=client_options),  # ty: ignore[no-matching-overload]
            key,
        )


async def read_bytes(
    location: str, store_options: Mapping[str, Any] | None = None, *, max_bytes: int | None = None
) -> bytes:
    """The whole object at ``location``; ``FileNotFoundError`` when there is none.

    With ``max_bytes``, a larger object raises ``OSError``: the size the
    store reports is checked before the body is read, and the body as it
    arrives.
    """
    store, key = store_and_key(location, store_options)
    result = await obstore.get_async(store, key)
    if max_bytes is None:
        return bytes(await result.bytes_async())
    too_large = OSError(f"{location} is larger than {max_bytes} bytes")
    if result.meta["size"] > max_bytes:
        raise too_large
    body = bytearray()
    async for chunk in result.stream():
        body += chunk
        if len(body) > max_bytes:
            raise too_large
    return bytes(body)


async def read_range(
    location: str, start: int, length: int, store_options: Mapping[str, Any] | None = None
) -> bytes:
    """``length`` bytes of the object at ``location``, from ``start``."""
    store, key = store_and_key(location, store_options)
    return bytes(await obstore.get_range_async(store, key, start=start, length=length))


class ObstoreTransport:
    """Reads catalog documents through obstore, wherever they are: disk, http(s) or a bucket.

    ``store_options`` reach the buckets only, as with :func:`read_bytes`. A
    document larger than ``max_bytes`` raises ``OSError``.
    """

    def __init__(
        self, store_options: Mapping[str, Any] | None = None, *, max_bytes: int = MAX_DOCUMENT_BYTES
    ) -> None:
        self.store_options = store_options
        self.max_bytes = max_bytes

    async def read(self, location: str) -> bytes:
        """The bytes of the document at ``location``.

        An obstore error becomes an ``OSError``, so the walk skips the
        document with the reason instead of stopping.
        """
        try:
            return await read_bytes(location, self.store_options, max_bytes=self.max_bytes)
        except BaseError as error:
            raise OSError(str(error)) from error
