"""Invalidating the plugin cache closes the shared instances that hold something open."""


class _Holder:
    THREAD_SAFE = True

    def __init__(self, provider_def):
        self.closed = False

    def close(self):
        self.closed = True


def test_invalidation_closes_a_shared_instance():
    import app.pygeoapi.plugin as plugin

    holder = _Holder({})
    with plugin._shared_lock:
        plugin._shared["test|holder"] = holder

    plugin.invalidate_plugin_cache()

    assert holder.closed
    assert "test|holder" not in plugin._shared


def test_a_failing_close_does_not_stop_the_invalidation():
    import app.pygeoapi.plugin as plugin

    class _Broken(_Holder):
        def close(self):
            raise RuntimeError("cannot close")

    with plugin._shared_lock:
        plugin._shared["test|broken"] = _Broken({})

    plugin.invalidate_plugin_cache()

    assert "test|broken" not in plugin._shared
