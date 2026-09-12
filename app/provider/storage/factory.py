"""Store factory: from a source reference to the right backend.

``load_store`` is the factory (in the spirit of pygeoapi's
``load_plugin``): it maps a base — an ``s3://``/``gs://``/``az://``/
``file://`` URL or a local directory — to the right backend.
Credentials come ONLY from each cloud's standard environment variables
(for Tigris: ``AWS_ENDPOINT_URL_S3`` from the Fly secrets).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.provider.storage.base import ObjectStore
from app.provider.storage.obstore_ import ObstoreStore

# The variables obstore reads an endpoint from, in every constructor.
_ENDPOINT_VARIABLES = ("AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL", "AWS_ENDPOINT")
_environment_lock = threading.Lock()

_URL_SCHEMES = (
    "s3://",
    "gs://",
    "az://",
    "azure://",
    "abfs://",
    "file://",
    "http://",
    "https://",
)


def split_source(source: str) -> tuple[str, str]:
    """Split an object reference into (base, relative key)."""
    if source.startswith(_URL_SCHEMES):
        base, _, key = source.rpartition("/")
        return f"{base}/", key
    path = Path(source)
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.parent), path.name


def _for_obstore(store_options: dict) -> dict:
    """Spell a dataset's store options the way obstore expects them.

    ``store_options`` are written in DuckDB's secret vocabulary, because
    that is the reader the GeoParquet provider uses by default. obstore
    speaks a different one, and it does not ignore what it does not
    recognise: an unknown key is refused outright. So an untranslated
    dict does not degrade — it makes a perfectly readable bucket look
    unreachable, which is how the editor came to report a source as
    missing in the same run that served features from it.
    """
    options = dict(store_options)
    translated: dict = {}
    for name, obstore_name in (("key_id", "access_key_id"), ("secret", "secret_access_key")):
        if name in options:
            translated[obstore_name] = options.pop(name)

    url_style = options.pop("url_style", None)
    if url_style is not None:
        translated["virtual_hosted_style_request"] = url_style != "path"

    # obstore reads the scheme off the endpoint; DuckDB takes a bare host
    # and a separate flag. Plain HTTP additionally needs `AWS_ALLOW_HTTP`
    # in the environment — obstore 0.11.1 *panics* (a Rust panic, not an
    # exception) when `allow_http` arrives through the configuration, so
    # there is no way to express it here.
    use_ssl = options.pop("use_ssl", True)
    endpoint = options.pop("endpoint", None)
    if endpoint is not None:
        scheme = "https" if use_ssl else "http"
        translated["endpoint"] = endpoint if "://" in str(endpoint) else f"{scheme}://{endpoint}"

    return {**options, **translated}


@contextmanager
def _explicit_endpoint_wins(config: dict) -> Iterator[None]:
    """Hide the environment's endpoint while a store with its own is built.

    A dataset is read where it lives, not where the process banks. But
    obstore 0.11 reads the standard variables in every constructor and,
    for the endpoint, lets them win over an explicit ``endpoint`` in the
    configuration: the store *reports* the explicit one while sending
    its requests to the environment's. On a deployment whose
    ``AWS_ENDPOINT_URL_S3`` names its own S3-compatible service, a public
    dataset on AWS was therefore asked of the wrong host.

    The variables are hidden only while the constructor runs and only
    when the configuration names an endpoint of its own; credentials
    stay visible, since a store on the deployment's own service still
    needs them. The lock keeps two concurrent constructions from seeing
    each other's half-restored environment.
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


def load_store(base: str, store_options: dict | None = None) -> ObjectStore:
    """Build the backend for a base URL/directory.

    ``store_options`` are the cloud store settings — ``region``,
    ``skip_signature`` for public data, ``endpoint`` for an
    S3-compatible service (and an explicit one wins over the process
    environment). They are meaningless for a local path and ignored
    there.
    """
    if base.startswith(_URL_SCHEMES):
        from obstore.store import from_url

        if store_options:
            config = _for_obstore(store_options)
            with _explicit_endpoint_wins(config):
                # ty: `from_url` is overloaded per provider-specific config
                # type, and ours is a plain mapping read from the tenant's
                # configuration — the value is only known at runtime.
                return ObstoreStore(
                    from_url(base, config=config)  # ty: ignore[no-matching-overload]
                )
        return ObstoreStore(from_url(base))
    from obstore.store import LocalStore

    return ObstoreStore(LocalStore(base))
