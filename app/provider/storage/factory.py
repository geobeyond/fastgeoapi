"""Store factory: from a source reference to the right backend.

``load_store`` is the factory (in the spirit of pygeoapi's
``load_plugin``): it maps a base — an ``s3://``/``gs://``/``az://``/
``file://`` URL or a local directory — to the right backend.
Credentials come ONLY from each cloud's standard environment variables
(for Tigris: ``AWS_ENDPOINT_URL_S3`` from the Fly secrets).
"""

from __future__ import annotations

from pathlib import Path

from app.provider.storage.base import ObjectStore
from app.provider.storage.obstore_ import ObstoreStore

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


def load_store(base: str, store_options: dict | None = None) -> ObjectStore:
    """Build the backend for a base URL/directory.

    ``store_options`` are the cloud store settings — ``region``,
    ``skip_signature`` for public data, ``endpoint`` for an
    S3-compatible service. They are meaningless for a local path and
    ignored there.
    """
    if base.startswith(_URL_SCHEMES):
        from obstore.store import from_url

        if store_options:
            # ty: `from_url` is overloaded per provider-specific config
            # type, and ours is a plain mapping read from the tenant's
            # configuration — the value is only known at runtime.
            return ObstoreStore(
                from_url(base, config=store_options)  # ty: ignore[no-matching-overload]
            )
        return ObstoreStore(from_url(base))
    from obstore.store import LocalStore

    return ObstoreStore(LocalStore(base))
