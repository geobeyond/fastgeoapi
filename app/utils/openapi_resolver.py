"""OpenAPI external reference resolver.

This module provides utilities to resolve external $ref references in OpenAPI
specifications. It fetches remote schemas and inlines them, preserving local
references (those starting with #) in *our* document.

Local references found *inside* inlined remote content are a different
matter: they are relative to the remote document, and left untouched they
would point at our root, where their targets do not exist. Those targets
are hoisted into our ``components`` under document-prefixed names and the
pointers rewritten (see ``_Hoist``); a whole document inlined this way
leaves its now-dead ``$defs`` behind. The result is a document in which
every ``$ref`` resolves — which FastMCP needs to generate whole tool
schemas.

This is particularly useful for OGC API specifications which heavily use
external references to shared schema definitions.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from loguru import logger

# Default cache TTL: 24 hours
DEFAULT_CACHE_TTL_SECONDS = 86400

# The keywords under which a JSON Schema document keeps its reusable
# definitions (draft 2019-09+ and the older name).
_DEFINITION_KEYWORDS = ("$defs", "definitions")


def _get_cache_path(url: str, cache_dir: Path) -> Path:
    """Generate a cache file path for a URL.

    Args:
        url: The URL to cache.
        cache_dir: The cache directory.

    Returns
    -------
        The path to the cache file.
    """
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return cache_dir / f"{url_hash}.json"


def _read_from_cache(
    url: str,
    cache_dir: Path,
    cache_ttl_seconds: int,
) -> dict[str, Any] | None:
    """Read a document from the cache if it exists and is not expired.

    Args:
        url: The URL of the document.
        cache_dir: The cache directory.
        cache_ttl_seconds: The cache TTL in seconds.

    Returns
    -------
        The cached document, or None if not cached or expired.
    """
    cache_path = _get_cache_path(url, cache_dir)
    if not cache_path.exists():
        return None

    try:
        with cache_path.open() as f:
            cached_data = json.load(f)

        timestamp = cached_data.get("timestamp", 0)
        if time.time() - timestamp > cache_ttl_seconds:
            logger.debug(f"Cache expired for: {url}")
            return None

        logger.debug(f"Cache hit for: {url}")
        return cached_data.get("document")
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning(f"Error reading cache for {url}: {e}")
        return None


def _write_to_cache(
    url: str,
    document: dict[str, Any],
    cache_dir: Path,
) -> None:
    """Write a document to the cache.

    Args:
        url: The URL of the document.
        document: The document content.
        cache_dir: The cache directory.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = _get_cache_path(url, cache_dir)

    try:
        cached_data = {
            "timestamp": time.time(),
            "url": url,
            "document": document,
        }
        with cache_path.open("w") as f:
            json.dump(cached_data, f)
        logger.debug(f"Cached: {url}")
    except OSError as e:
        logger.warning(f"Error writing cache for {url}: {e}")


def _fetch_remote_document(url: str) -> dict[str, Any]:
    """Fetch a remote document and parse it as YAML or JSON.

    Args:
        url: The URL to fetch (must be the base URL without fragment).

    Returns
    -------
        The parsed document as a dictionary.

    Raises
    ------
        httpx.RequestError: If the request fails.
    """
    logger.debug(f"Fetching remote OpenAPI reference: {url}")
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    content = response.text

    if url.endswith(".yaml") or url.endswith(".yml"):
        return yaml.safe_load(content)
    return json.loads(content)


def _navigate_to_fragment(doc: dict[str, Any], fragment: str) -> Any:
    """Navigate to a JSON pointer fragment within a document.

    Args:
        doc: The document to navigate.
        fragment: The JSON pointer fragment (e.g., '/components/schemas/Link').

    Returns
    -------
        The value at the fragment location.
    """
    if not fragment or fragment == "/":
        return doc

    parts = fragment.strip("/").split("/")
    result = doc
    for part in parts:
        if part:
            result = result[part]
    return result


def _resolve_relative_url(ref: str, base_url: str | None) -> str:
    """Resolve a relative URL against a base URL.

    Args:
        ref: The reference URL (may be relative or absolute).
        base_url: The base URL to resolve against.

    Returns
    -------
        The absolute URL.
    """
    # If ref is already absolute, return it
    parsed = urlparse(ref)
    if parsed.scheme:
        return ref

    # If no base URL, we can't resolve relative refs
    if not base_url:
        raise ValueError(f"Cannot resolve relative reference '{ref}' without base URL")

    # Use urljoin to resolve relative URL
    return urljoin(base_url, ref)


def _get_document(
    url: str,
    document_cache: dict[str, dict[str, Any]],
    disk_cache_dir: Path | None,
    cache_ttl_seconds: int,
) -> dict[str, Any]:
    """Get a document from memory cache, disk cache, or fetch it.

    Args:
        url: The URL of the document.
        document_cache: In-memory cache of documents.
        disk_cache_dir: Optional disk cache directory.
        cache_ttl_seconds: Cache TTL in seconds.

    Returns
    -------
        The document content.
    """
    # Check memory cache first
    if url in document_cache:
        return document_cache[url]

    # Check disk cache
    if disk_cache_dir is not None:
        cached_doc = _read_from_cache(url, disk_cache_dir, cache_ttl_seconds)
        if cached_doc is not None:
            document_cache[url] = cached_doc
            return cached_doc

    # Fetch from remote
    doc = _fetch_remote_document(url)
    document_cache[url] = doc

    # Write to disk cache
    if disk_cache_dir is not None:
        _write_to_cache(url, doc, disk_cache_dir)

    return doc


def _resolve_ref(
    ref: str,
    document_cache: dict[str, dict[str, Any]],
    base_url: str | None = None,
    disk_cache_dir: Path | None = None,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> tuple[Any, str]:
    """Resolve a single external $ref.

    Args:
        ref: The $ref value (e.g., 'https://example.com/schema.yaml#/components/schemas/Link').
        document_cache: Cache of already fetched documents.
        base_url: Base URL for resolving relative references.
        disk_cache_dir: Optional disk cache directory.
        cache_ttl_seconds: Cache TTL in seconds.

    Returns
    -------
        A tuple of (resolved schema/object, document URL for further relative resolution).
    """
    if "#" in ref:
        url_part, fragment = ref.split("#", 1)
    else:
        url_part, fragment = ref, ""

    # Resolve relative URL if needed
    if url_part:
        absolute_url = _resolve_relative_url(url_part, base_url)
    else:
        # Fragment-only ref in an external document
        absolute_url = base_url or ""

    # Get document (from cache or fetch)
    if absolute_url:
        doc = _get_document(
            absolute_url,
            document_cache,
            disk_cache_dir,
            cache_ttl_seconds,
        )
    else:
        doc = {}

    result = _navigate_to_fragment(doc, fragment)
    return result, absolute_url


class _Hoist:
    """Definitions lifted out of remote documents into our ``components``.

    A ``#/...`` pointer found inside inlined remote content is relative to
    the *remote* document, not to ours. Left as it is, it aims at our root
    where its target does not exist: on the demo document that was 489
    dangling references, most of them ``#/$defs/*`` from ``cql2.json``.

    Rather than inlining the target — CQL2 is recursive, and inlining a
    recursive schema never ends — the target is copied once into our
    ``components``, under a name prefixed by the document it came from,
    and every pointer to it is rewritten to that name. Registering the
    name *before* processing the target is what terminates the recursion:
    a self-reference finds the name already taken and just points at it.
    ``#/components/schemas/…`` is also the one shape FastMCP turns into
    tool ``$defs``, so the MCP tools come out whole.
    """

    def __init__(self) -> None:
        self.components: dict[str, dict[str, Any]] = {}
        self._names: dict[tuple[str, str], tuple[str, str]] = {}

    @staticmethod
    def _prefix(url: str) -> str:
        stem = Path(urlparse(url).path).stem or "remote"
        # Component keys are restricted to [A-Za-z0-9._-].
        return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)

    @staticmethod
    def _section_and_name(fragment: str) -> tuple[str, str]:
        parts = [p for p in fragment.strip("/").split("/") if p]
        if len(parts) >= 3 and parts[0] == "components":
            return parts[1], "_".join(parts[2:])
        if len(parts) >= 2 and parts[0] in _DEFINITION_KEYWORDS:
            return "schemas", "_".join(parts[1:])
        return "schemas", "_".join(parts) or "root"

    def reference(self, url: str, fragment: str, resolve: Any) -> str:
        """The local pointer, rewritten to our components; hoists on first sight."""
        key = (url, fragment)
        if key not in self._names:
            section, name = self._section_and_name(fragment)
            hoisted = f"{self._prefix(url)}__{name}"
            taken = self.components.setdefault(section, {})
            suffix = 1
            while hoisted in taken:
                suffix += 1
                hoisted = f"{self._prefix(url)}__{name}_{suffix}"
            self._names[key] = (section, hoisted)
            taken[hoisted] = None  # reserve the name: recursion stops here
            taken[hoisted] = resolve(url, fragment)
        section, hoisted = self._names[key]
        return f"#/components/{section}/{hoisted}"


def _resolve_object(
    obj: Any,
    document_cache: dict[str, dict[str, Any]],
    base_url: str | None = None,
    disk_cache_dir: Path | None = None,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    hoist: _Hoist | None = None,
) -> Any:
    """Recursively resolve external $refs in an object.

    Args:
        obj: The object to process (can be dict, list, or scalar).
        document_cache: Cache of already fetched documents.
        base_url: Base URL for resolving relative references. ``None`` while
            walking our own document; the remote document's URL once inside
            inlined content — which is what makes a ``#/...`` pointer there
            relative to *that* document.
        disk_cache_dir: Optional disk cache directory.
        cache_ttl_seconds: Cache TTL in seconds.
        hoist: Where remote-local targets are lifted to (see ``_Hoist``).

    Returns
    -------
        The object with external $refs resolved.
    """
    if hoist is None:
        hoist = _Hoist()

    def recurse(value: Any, url: str | None) -> Any:
        return _resolve_object(value, document_cache, url, disk_cache_dir, cache_ttl_seconds, hoist)

    if isinstance(obj, dict):
        ref = obj.get("$ref")
        # An external $ref: fetch, inline, and keep walking inside the
        # fetched content with its own URL as the base.
        if isinstance(ref, str) and not ref.startswith("#") and len(obj) == 1:
            resolved, new_base_url = _resolve_ref(
                ref,
                document_cache,
                base_url,
                disk_cache_dir,
                cache_ttl_seconds,
            )
            fragment = ref.split("#", 1)[1] if "#" in ref else ""
            if isinstance(resolved, dict) and not fragment.strip("/"):
                # A whole document is being inlined. Every pointer into its
                # `$defs`/`definitions` gets rewritten to a hoisted copy
                # (`lift` below reads the cached original), so the block
                # itself is dead weight — and, carried along, a trap:
                # FastMCP does not descend into `$defs`, so the stale
                # pointers inside it surfaced in the CQL2 tool schema as
                # 97 broken references.
                resolved = {k: v for k, v in resolved.items() if k not in _DEFINITION_KEYWORDS}
            return recurse(resolved, new_base_url)

        # A local $ref inside remote content is local to the remote
        # document: hoist its target and point at the hoisted copy.
        if isinstance(ref, str) and ref.startswith("#") and base_url:
            fragment = ref[1:]

            def lift(url: str, frag: str) -> Any:
                doc = _get_document(url, document_cache, disk_cache_dir, cache_ttl_seconds)
                return recurse(_navigate_to_fragment(doc, frag), url)

            rewritten = dict(obj)
            rewritten["$ref"] = hoist.reference(base_url, fragment, lift)
            return {k: (v if k == "$ref" else recurse(v, base_url)) for k, v in rewritten.items()}

        # A local $ref in our own document, or a regular dict: recurse.
        return {k: recurse(v, base_url) for k, v in obj.items()}

    if isinstance(obj, list):
        return [recurse(item, base_url) for item in obj]

    return obj


def resolve_external_refs(
    spec: dict[str, Any],
    cache_dir: Path | None = None,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    """Resolve all external $ref references in an OpenAPI specification.

    This function recursively resolves external references (URLs) while
    preserving local references (those starting with #/). It fetches
    remote documents and inlines their content.

    Relative references are resolved against the URL of the document
    that contains them.

    Args:
        spec: The OpenAPI specification dictionary.
        cache_dir: Optional directory for caching fetched documents.
            If provided, documents are cached to disk to speed up subsequent runs.
        cache_ttl_seconds: Time-to-live for cached documents in seconds.
            Defaults to 24 hours (86400 seconds).

    Returns
    -------
        A new specification with all external $refs resolved.

    Example:
        >>> spec = {"paths": {}, "components": {"schemas": {}}}
        >>> resolved = resolve_external_refs(spec)
        >>> resolved == spec  # No external refs, returns unchanged
        True
    """
    document_cache: dict[str, dict[str, Any]] = {}
    hoist = _Hoist()
    resolved = _resolve_object(
        spec,
        document_cache,
        disk_cache_dir=cache_dir,
        cache_ttl_seconds=cache_ttl_seconds,
        hoist=hoist,
    )
    if hoist.components:
        # Remote-local definitions, lifted into our components under
        # document-prefixed names. Existing components are never touched:
        # a prefixed name colliding with a user's own is next to
        # impossible, and if it happens the user's definition wins.
        if not isinstance(resolved, dict):
            return resolved
        components = resolved.setdefault("components", {})
        for section, definitions in hoist.components.items():
            target = components.setdefault(section, {})
            for name, definition in definitions.items():
                target.setdefault(name, definition)
    return resolved


def count_external_refs(obj: Any) -> int:
    """Count the number of external $ref references in an object.

    Args:
        obj: The object to count refs in.

    Returns
    -------
        The number of external references.
    """
    count = 0
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref = obj["$ref"]
            if isinstance(ref, str) and not ref.startswith("#"):
                count += 1
        for v in obj.values():
            count += count_external_refs(v)
    elif isinstance(obj, list):
        for item in obj:
            count += count_external_refs(item)
    return count


def has_external_refs(obj: Any) -> bool:
    """Check if an object contains any external $ref references.

    Args:
        obj: The object to check.

    Returns
    -------
        True if any external references exist, False otherwise.
    """
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref = obj["$ref"]
            if isinstance(ref, str) and not ref.startswith("#"):
                return True
        for v in obj.values():
            if has_external_refs(v):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if has_external_refs(item):
                return True
    return False
