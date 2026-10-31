"""A provider dropped by a configuration reload is closed."""

import time
from unittest.mock import patch

from tests.maps_fixtures import FakeRenderer

MAP = "/collections/under_test/map"


def test_a_reload_closes_the_provider(contract):
    from app.pygeoapi.plugin import invalidate_plugin_cache

    response = contract.client.get(MAP, params={"width": 16, "height": 16})
    assert response.status_code == 200, response.text[:200]
    provider = contract.provider

    with patch.object(provider, "close", wraps=provider.close) as close:
        invalidate_plugin_cache()

    close.assert_called_once_with()
    if contract.records_requests:
        # The renderer closes on the loop that owns it, once no map waits for it.
        deadline = time.monotonic() + 2
        while not FakeRenderer.instances[-1].closed and time.monotonic() < deadline:
            time.sleep(0.01)
        assert FakeRenderer.instances[-1].closed
