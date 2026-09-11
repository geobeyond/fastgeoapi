"""The awaitable side of the API (ADR-0010).

Handlers here serve natively asynchronous providers on the event loop;
every other provider keeps pygeoapi's synchronous handlers in the
threadpool, byte for byte.
"""
