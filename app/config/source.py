"""Load the pygeoapi config from any storage-layer source.

The config never touches disk nor env vars (ADR-0003): bytes → dict
here, the ``API`` instance is born in ``app/pygeoapi/factory.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def load_config_source(source: str) -> ConfigDocument:
    """Sync face: used at startup, before the loop exists."""
    bridge, key = _bridge_and_key(source)
    raw = bridge.read(key)
    return ConfigDocument(config=_parse(raw, source), etag=bridge.stat(key).etag, source=source)


async def aload_config_source(source: str) -> ConfigDocument:
    """Async face: used by the reload webhook."""
    bridge, key = _bridge_and_key(source)
    raw = await bridge.aread(key)
    meta = await bridge.astat(key)
    return ConfigDocument(config=_parse(raw, source), etag=meta.etag, source=source)


async def astat_config_source(source: str) -> ObjectMeta:
    """Metadata only: the reload ETag check never downloads the body."""
    bridge, key = _bridge_and_key(source)
    return await bridge.astat(key)
