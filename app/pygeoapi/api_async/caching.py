"""HTTP caching for the map and tile routes: ETags from the provider's version, and 304s.

The provider tells which version of its answer a request would get,
before any map is drawn or tile read. The ETag is a digest of that
version, of the request's parameters and of fastgeoapi's own sources,
so the same input has the same ETag in every process. A request whose
``If-None-Match`` names it gets a 304, and nothing is drawn or read.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from typing import Any

from pygeoapi.provider.base import ProviderGenericError

from app.config.logging import create_logger
from app.interfaces.providers import VersionedProvider

PACKAGE = Path(__file__).resolve().parents[2]
"""The ``app`` package: its sources take part in every ETag."""

VARY = "Accept, Accept-Encoding"
"""Without ``f``, ``Accept`` picks the format; ``Accept-Encoding`` decides the gzip."""

logger = create_logger("app.pygeoapi.api_async.caching")


def sources_digest(root: Path) -> str:
    """A digest of the Python sources under ``root``, their paths included."""
    sha = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        sha.update(path.relative_to(root).as_posix().encode())
        sha.update(b"\0")
        sha.update(path.read_bytes())
        sha.update(b"\0")
    return sha.hexdigest()[:16]


@lru_cache(maxsize=1)
def code_version() -> str:
    """The digest of fastgeoapi's own sources, read once per process.

    The Docker image does not install the project, so it has no package
    version, and the version in ``pyproject.toml`` changes only at releases.
    """
    return sources_digest(PACKAGE)


@dataclass(frozen=True)
class HttpCache:
    """How long browsers and caches may keep the answers of the map and tile routes.

    ``protected`` is true when fastgeoapi authenticates the requests: then
    only the user's own browser keeps an answer. ``code`` takes part in
    every ETag, so an answer of another version of fastgeoapi never
    matches. A ``max_age`` of 0 turns the headers off.
    """

    max_age: int
    protected: bool
    code: str

    @classmethod
    def from_settings(cls, settings: Any) -> HttpCache:
        """The policy of fastgeoapi's settings: protected when OPA, JWKS or an API key is on."""
        protected = bool(settings.OPA_ENABLED or settings.JWKS_ENABLED or settings.API_KEY_ENABLED)
        return cls(
            max_age=int(settings.FASTGEOAPI_HTTP_MAX_AGE_SECONDS),
            protected=protected,
            code=code_version(),
        )

    @property
    def enabled(self) -> bool:
        """Whether the answers get cache headers at all."""
        return self.max_age > 0

    def cache_control(self) -> str:
        """``public`` or ``private``, with the max age."""
        scope = "private" if self.protected else "public"
        return f"{scope}, max-age={self.max_age}"

    def etag(self, dataset: str, kind: str, version: str, arguments: dict[str, Any]) -> str:
        """A strong ETag for the ``kind`` (``tile`` or ``map``) of ``dataset`` at ``version``."""
        payload = json.dumps(
            [self.code, dataset, kind, version, arguments], sort_keys=True, default=str
        )
        return f'"{hashlib.sha256(payload.encode()).hexdigest()[:32]}"'

    def headers(self, etag: str) -> dict[str, str]:
        """The headers of an answer with ``etag``, a 304 included."""
        return {"ETag": etag, "Cache-Control": self.cache_control(), "Vary": VARY}


def default_http_cache() -> HttpCache:
    """The policy of fastgeoapi's settings; off without them, since protection is then unknown."""
    # Imported here: building the settings needs a configured fastgeoapi, and
    # the sub-app is also built by tools that only have pygeoapi.
    try:
        from app.config.app import configuration
    except (ImportError, ValueError):
        return HttpCache(max_age=0, protected=False, code="")
    return HttpCache.from_settings(configuration)


def not_modified(if_none_match: str | None, etag: str) -> bool:
    """Whether ``If-None-Match`` names ``etag``, compared weakly (RFC 9110, section 13.1.2)."""
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    wanted = etag.removeprefix("W/")
    return any(tag.strip().removeprefix("W/") == wanted for tag in if_none_match.split(","))


async def cache_headers(
    http_cache: HttpCache | None,
    provider: Any,
    dataset: str,
    kind: str,
    arguments: dict[str, Any],
    response_headers: dict,
) -> dict[str, str]:
    """The cache headers of the answer to ``arguments``; empty when it gets none.

    A provider without ``aversion``, or one that does not know its version,
    gives none. A provider error means the request fails, and the data
    call that follows reports it. Any other failure is logged, and the
    request goes on without cache headers. The content coding already in
    ``response_headers`` takes part in the ETag, since gzip gives other
    bytes.
    """
    if http_cache is None or not http_cache.enabled:
        return {}
    if not isinstance(provider, VersionedProvider):
        return {}
    try:
        version = await provider.aversion(**arguments)
    except ProviderGenericError:
        return {}
    except Exception as error:
        logger.warning(f"the {kind} of {dataset} goes without cache headers: {error}")
        return {}
    if version is None:
        return {}
    coded = {**arguments, "encoding": response_headers.get("Content-Encoding")}
    return http_cache.headers(http_cache.etag(dataset, kind, version, coded))


def not_modified_answer(headers: dict, cached: dict[str, str]) -> tuple[dict, int, bytes]:
    """The 304 for a request whose ``If-None-Match`` names the current ETag.

    It has no body, so no content coding either.
    """
    headers.pop("Content-Encoding", None)
    headers.update(cached)
    return headers, HTTPStatus.NOT_MODIFIED, b""
