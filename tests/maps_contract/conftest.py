"""One map collection, ``under_test``, served by each native map provider.

Every test of this folder runs once per entry of :data:`PROVIDERS`. An
entry builds the definition of a provider over a PMTiles archive, and the
tests ask the served collection what any client may ask. A new native map
provider joins the suite with one entry.

``app.*`` is imported inside the functions, nowhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from tests.maps_fixtures import map_provider
from tests.mvt_fixtures import land_archive
from tests.test_tiles_async_route import _collection, _config

REAL_RENDERER = "app.maps.mlnative.create_renderer"
NIGHT = '{"version": 8, "sources": {}, "layers": [{"id": "night", "type": "background"}]}'


def _maplibre(archive: Path, **options: Any) -> dict:
    return map_provider(archive, **options)


def _maplibre_native(archive: Path, **options: Any) -> dict:
    return map_provider(archive, **{"renderer": REAL_RENDERER, **options})


PROVIDERS: dict[str, Callable[..., dict]] = {
    # MapLibre styles drawn by a renderer that records the requests.
    "maplibre": _maplibre,
    # The same provider drawing with MapLibre Native, where mlnative installs.
    "maplibre-native": _maplibre_native,
}
NEEDS_RENDERER = {"maplibre-native"}


def _skip_without_mlnative() -> None:
    mlnative = pytest.importorskip("mlnative")
    try:
        mlnative.get_binary_path()
    except Exception:
        pytest.skip("the mlnative binary is missing")


@dataclass
class Contract:
    """The collection ``under_test`` and the provider that serves it.

    Attributes
    ----------
    name
        The entry of :data:`PROVIDERS` under test.
    folder
        The test's own folder, for the archive and the styles.
    archive
        The PMTiles archive the collection draws.
    definition
        The provider definition of the client opened last.
    client
        A client over the sub-app of that definition, with the HTTP cache on.
    """

    name: str
    folder: Path
    archive: Path
    definition: dict = field(default_factory=dict)
    client: TestClient | None = None
    _stack: ExitStack = field(default_factory=ExitStack)

    @property
    def records_requests(self) -> bool:
        """Whether the renderer is the fake one, which keeps every request it draws."""
        return self.name not in NEEDS_RENDERER

    @property
    def provider(self) -> Any:
        """The provider instance the route awaits, from the plugin cache."""
        from pygeoapi import plugin

        return plugin.load_plugin("provider", self.definition)

    def build_definition(self, **options: Any) -> dict:
        """The entry's definition over the archive, with the style ``night`` and ``options``."""
        night = self.folder / "night.json"
        night.write_text(NIGHT)
        return PROVIDERS[self.name](
            self.archive, **{"styles": {"night": str(night)}, "max_size": 1024, **options}
        )

    def open_client(self, definition: dict) -> TestClient:
        """A client over one collection served by ``definition``; it becomes the current one."""
        from app.pygeoapi.api_async.caching import HttpCache
        from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

        config = _config({"under_test": _collection("Under test", [definition])})
        app = build_pygeoapi_subapp(
            config,
            build_openapi(config),
            http_cache=HttpCache(max_age=300, protected=False, code="contract"),
        )
        # One loop for the client's life: the provider closes its renderer on it.
        client = self._stack.enter_context(TestClient(app, raise_server_exceptions=False))
        self.client, self.definition = client, definition
        provider = self.provider
        # Before the loop closes: a renderer process outliving it would leak.
        self._stack.callback(client.portal.call, provider.aclose)
        return client

    def close(self) -> None:
        """Close the clients this contract opened."""
        self._stack.close()


@pytest.fixture(
    params=[
        pytest.param(name, marks=pytest.mark.renderer) if name in NEEDS_RENDERER else name
        for name in PROVIDERS
    ]
)
def contract(request, tmp_path):
    """The collection ``under_test``, served by one entry of :data:`PROVIDERS`."""
    if request.param in NEEDS_RENDERER:
        _skip_without_mlnative()
    contract = Contract(request.param, tmp_path, land_archive(tmp_path / "land.pmtiles"))
    contract.open_client(contract.build_definition())
    try:
        yield contract
    finally:
        contract.close()
