"""Load the pygeoapi config from any storage-layer source.

The config never touches disk nor env vars (ADR-0003): bytes → dict
here, the ``API`` instance is born in ``app/pygeoapi/factory.py``.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml

from app.provider.storage import load_store, split_source
from app.provider.storage.base import ObjectMeta
from app.provider.storage.bridge import StorageBridge


class ConfigSourceError(Exception):
    """The source exists but does not hold a valid pygeoapi config."""


@dataclass(frozen=True)
class ConfigDocument:
    """Parsed config plus the metadata the reload needs."""

    config: dict
    etag: str | None
    source: str


def _bridge_and_key(source: str) -> tuple[StorageBridge, str]:
    base, key = split_source(source)
    return StorageBridge(load_store(base)), key


def _parse(raw: bytes, source: str) -> dict:
    """Parse with pygeoapi semantics: ``${VAR}`` interpolated from env.

    ``pygeoapi.util.yaml_load`` is the same loader upstream uses in
    ``get_config()``: a config that works with vanilla pygeoapi works
    identically here, placeholders included. A missing variable raises
    ``EnvironmentError`` exactly as upstream does.
    """
    import io

    from pygeoapi.util import yaml_load

    try:
        parsed = yaml_load(io.StringIO(raw.decode("utf-8")))
    except yaml.YAMLError as e:
        raise ConfigSourceError(f"invalid YAML in {source}: {e}") from e
    if not isinstance(parsed, dict):
        raise ConfigSourceError(f"{source} must be a YAML mapping, got {type(parsed).__name__}")
    return parsed


def resolve_file_indexes(config: dict, source: str) -> dict:
    """Resolve every relative index location of ``config`` against ``source``.

    The locations are ``file_index`` and ``id_index.location``. An index
    written beside the configuration is named relative to it, so the two
    move together. A provider does not know where its configuration came
    from, so the path is resolved here, after parsing; the text of the
    configuration keeps the relative path.

    Parameters
    ----------
    config
        The parsed configuration; changed in place.
    source
        Where the configuration was read: a local path or a bucket URL.

    Returns
    -------
    dict
        ``config``, with each relative index location made absolute.
    """
    resources = config.get("resources")
    # The schema validation reports a malformed configuration; leave it as it is.
    if not isinstance(resources, dict):
        return config
    for resource in resources.values():
        providers = resource.get("providers") if isinstance(resource, dict) else None
        for provider in providers if isinstance(providers, list) else []:
            if not isinstance(provider, dict):
                continue
            if isinstance(provider.get("file_index"), str):
                provider["file_index"] = _resolve_beside(provider["file_index"], source)
            id_index = provider.get("id_index")
            if isinstance(id_index, dict) and isinstance(id_index.get("location"), str):
                id_index["location"] = _resolve_beside(id_index["location"], source)
    return config


def _resolve_beside(location: str, source: str) -> str:
    """``location`` joined to the folder of ``source`` when it is relative, as written otherwise."""
    if not location or urlsplit(location).scheme or Path(location).is_absolute():
        return location
    remote = urlsplit(source)
    if remote.scheme:
        # urljoin does not know s3:// and keeps the key relative, so it is joined here;
        # normpath folds a `..` that PurePosixPath keeps and S3 would read literally.
        key = posixpath.normpath(str(PurePosixPath(remote.path).parent / location))
        return f"{remote.scheme}://{remote.netloc}{key}"
    return str(Path(source).resolve().parent / location)


def load_config_source(source: str) -> ConfigDocument:
    """Sync face: used at startup, before the loop exists."""
    bridge, key = _bridge_and_key(source)
    raw = bridge.read(key)
    config = resolve_file_indexes(_parse(raw, source), source)
    return ConfigDocument(config=config, etag=bridge.stat(key).etag, source=source)


async def aload_config_source(source: str) -> ConfigDocument:
    """Async face: used by the reload webhook."""
    bridge, key = _bridge_and_key(source)
    raw = await bridge.aread(key)
    meta = await bridge.astat(key)
    config = resolve_file_indexes(_parse(raw, source), source)
    return ConfigDocument(config=config, etag=meta.etag, source=source)


async def astat_config_source(source: str) -> ObjectMeta:
    """Metadata only: the reload ETag check never downloads the body."""
    bridge, key = _bridge_and_key(source)
    return await bridge.astat(key)
