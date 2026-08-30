"""Answer three questions about a configuration document.

Is the document being edited well formed? Is what will actually run
well formed? Does it build?

These are deliberately plain functions over text, not endpoints: the
CLI wants them, a CI check wants them, and the editor's routes are only
one caller. Text rather than a parsed mapping because the distinction
between *source* and *effective* lives in how the text is loaded —
pygeoapi resolves `${VAR}` at load time, so a mapping has already lost
the difference.
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import yaml

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class Outcome:
    """What was asked, and what can be said about it.

    Attributes
    ----------
    ok
        Whether the question came back clean.
    problems
        One line per problem, phrased for whoever wrote the document —
        the key at fault and why, never a stack trace.
    variables
        The `${VAR}` values used while resolving. Present so a reader
        can tell *this* answer from the one the deployment would give:
        the values come from whoever is running the editor.
    collections
        For a dry run, the collections that actually stood up.
    specs
        With `augmented`, the OGC API specifications this configuration
        would mount. fastgeoapi builds its route table from the
        resources rather than serving everything (ADR-0005), so this is
        a fact about the document that no pygeoapi tool can report.
    tools
        With `augmented`, the MCP tools an agent would see.
    not_reported
        Parts of an augmented answer that could not be produced, and
        why. Asking for more than is installed is not an error — saying
        nothing about it would be.
    """

    ok: bool
    problems: list[str] = field(default_factory=list)
    variables: dict[str, str] = field(default_factory=dict)
    collections: list[str] = field(default_factory=list)
    specs: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    not_reported: list[str] = field(default_factory=list)


def _placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def _parse(text: str) -> tuple[dict | None, str | None]:
    """Parse YAML, returning the problem instead of raising it.

    Someone is editing: a half-written document is the normal case, not
    an exceptional one.
    """
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return None, f"the document is not valid YAML: {str(e).splitlines()[0]}"
    if not isinstance(parsed, dict):
        return None, "the document must be a mapping at the top level"
    return parsed, None


def _schema_problems(config: dict, forgive_placeholders: bool) -> list[str]:
    """Validate against pygeoapi's schema, one line per problem.

    With `forgive_placeholders`, a complaint about a value that is still
    a `${VAR}` is dropped: in the source document `port: ${PORT}` is a
    string where the schema wants an integer, and that is correct, not
    broken. Everything else is still reported — forgiving placeholders
    must not mean forgiving the document.
    """
    import json

    from jsonschema import Draft202012Validator
    from pygeoapi.config import load_schema
    from pygeoapi.util import to_json

    # Through JSON first, exactly as pygeoapi's own `validate_config`
    # does. YAML turns `2000-10-30T18:24:39Z` into a `datetime`, which
    # the schema has no type for — validating the raw mapping reports a
    # correct document as broken.
    instance = json.loads(to_json(config))

    problems = []
    for error in Draft202012Validator(load_schema()).iter_errors(instance):
        instance = error.instance
        if forgive_placeholders and isinstance(instance, str) and _PLACEHOLDER.search(instance):
            continue
        where = ".".join(str(part) for part in error.absolute_path) or "the document root"
        problems.append(f"{where}: {error.message}")
    return problems


def validate_source(text: str) -> Outcome:
    """Check the document as written, placeholders and all."""
    config, problem = _parse(text)
    if config is None:
        return Outcome(ok=False, problems=[problem or "unparseable"])
    problems = _schema_problems(config, forgive_placeholders=True)
    return Outcome(ok=not problems, problems=problems)


def _resolve(text: str) -> tuple[dict[str, str], list[str]]:
    """The values behind the placeholders, and the ones that are missing."""
    used, missing = {}, []
    for name in sorted(_placeholders(text)):
        value = os.environ.get(name)
        if value is None:
            missing.append(f"${{{name}}} has no value in this environment")
        else:
            used[name] = value
    return used, missing


def validate_effective(text: str) -> Outcome:
    """Check what would actually run, once the placeholders are resolved."""
    variables, missing = _resolve(text)
    if missing:
        return Outcome(ok=False, problems=missing, variables=variables)

    from pygeoapi.util import yaml_load

    try:
        config = yaml_load(text)
    except Exception as e:  # a resolved document can still fail to load
        return Outcome(ok=False, problems=[str(e)], variables=variables)

    problems = _schema_problems(config, forgive_placeholders=False)
    return Outcome(ok=not problems, problems=problems, variables=variables)


def dry_run(text: str, augmented: bool = False) -> Outcome:
    """Build the configuration for real, and report what stood up.

    This is what validation cannot do: a document can satisfy the schema
    and still name a file that is not there, a provider that will not
    import, or a bucket nothing can reach.

    With `augmented`, it also reports what fastgeoapi would make of the
    document beyond serving it: which specifications get mounted, and
    which MCP tools an agent would see. Both are answers pygeoapi has no
    way to give — and both are optional, because this command has to
    keep working for someone who only has pygeoapi.

    It answers **"does this build here"**, never "will this work in
    production": the build uses the environment and the credentials of
    whoever is running the editor. `variables` carries what was
    substituted so a reader can tell the difference — an outcome that
    hid it would invite reading a green as a guarantee it cannot give.
    """
    effective = validate_effective(text)
    if not effective.ok:
        return effective

    from pygeoapi.util import yaml_load

    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    config: dict[str, Any] = yaml_load(text)
    try:
        openapi = build_openapi(config)
        subapp = build_pygeoapi_subapp(config, openapi)
    except Exception as e:
        return Outcome(ok=False, problems=[_blame(config, e)], variables=effective.variables)

    # Building is not enough, and neither is asking: pygeoapi's GeoJSON
    # provider answers 200 with an empty FeatureCollection when its file
    # is not there, so "no features" and "no file" look identical over
    # HTTP. The data source is therefore checked directly — which is the
    # case ADR-0008 uses to justify a dry run in the first place: a
    # configuration that validates while the provider cannot read what
    # it names.
    unreachable = [
        f"resource '{name}': cannot reach the data source '{data}' — {why}"
        for name, data, why in _unreachable_sources(config)
    ]

    # Building is not enough. A provider is constructed without touching
    # its data — a GeoJSON pointing at a file that is not there builds
    # perfectly and fails on the first read — so each collection is asked
    # for a single item. That is the difference between "it imported"
    # and "it can serve", and the second is what an operator wants to
    # know before saving.
    from starlette.testclient import TestClient

    client = TestClient(subapp, raise_server_exceptions=False)
    served, problems = [], []
    for name, resource in (config.get("resources") or {}).items():
        if resource.get("type") != "collection":
            continue
        response = client.get(
            f"/collections/{name}/items?limit=1", headers={"Accept": "application/json"}
        )
        if response.status_code == 200:
            served.append(name)
        else:
            problems.append(
                f"resource '{name}': asking for one item answered "
                f"{response.status_code} — {response.text[:160]}"
            )

    problems = unreachable + problems
    specs: list[str] = []
    tools: list[str] = []
    not_reported: list[str] = []
    if augmented:
        specs, tools, not_reported = _augmented(config, openapi)

    return Outcome(
        ok=not problems,
        problems=problems,
        variables=effective.variables,
        collections=sorted(served),
        specs=specs,
        tools=tools,
        not_reported=not_reported,
    )


def _augmented(config: dict, openapi: dict) -> tuple[list[str], list[str], list[str]]:
    """The two answers only fastgeoapi can give, each failing on its own.

    Separately, deliberately: an installation without fastmcp still gets
    its specifications, and neither missing half is allowed to take the
    dry run down with it. Someone may pass the flag against a pygeoapi
    they do not serve with fastgeoapi, and failing would hand them back
    the barrier this command just removed.
    """
    specs: list[str] = []
    tools: list[str] = []
    missing: list[str] = []

    try:
        from app.pygeoapi.registry import active_specs

        specs = sorted(active_specs(config))
    except Exception as e:
        missing.append(f"specifications: {type(e).__name__}: {e}")

    try:
        tools = sorted(_mcp_tools(openapi))
    except Exception as e:
        missing.append(f"tools: {type(e).__name__}: {e}")

    return specs, tools, missing


def _mcp_tools(openapi: dict) -> list[str]:
    """The tool names FastMCP would generate from this document.

    Asked of FastMCP rather than derived here: the naming is its own,
    and a copy of its rules would drift the first time upstream changed
    them. The client is a stand-in — it is only reached when a tool is
    *called*, and nothing here calls one.

    Run on a thread of its own because the caller is synchronous and is
    itself called from a running event loop, where `asyncio.run` refuses.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    import httpx2
    from fastmcp import FastMCP

    from app.utils.openapi_resolver import resolve_external_refs

    async def listed() -> list[str]:
        # The generated document carries external `$ref`s to the OGC
        # schemas and FastMCP resolves only local ones.
        resolved = resolve_external_refs(openapi)
        async with httpx2.AsyncClient(base_url="http://the-tools-are-not-called") as client:
            server = FastMCP.from_openapi(openapi_spec=resolved, client=client, name="preview")
            return [tool.name for tool in await server.list_tools()]

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(listed())).result()


#: Where a dataset lives. obstore reads these in every constructor and
#: an explicit ``endpoint`` does not override them — which is why the
#: provider reads buckets through DuckDB's own reader instead, whose
#: secret is scoped to the dataset.
_AMBIENT_ADDRESS = (
    "AWS_ENDPOINT_URL_S3",
    "AWS_ENDPOINT_URL",
    "AWS_ENDPOINT",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
)

#: How to sign for it.
_AMBIENT_CREDENTIALS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "GOOGLE_SERVICE_ACCOUNT",
    "GOOGLE_SERVICE_ACCOUNT_PATH",
    "AZURE_STORAGE_ACCOUNT_KEY",
)

#: Options by which a dataset declares it signs for itself.
_OWN_CREDENTIALS = ("key_id", "secret", "access_key_id", "secret_access_key")

#: `_only` edits the process environment, so two dry runs must not
#: overlap. One operator on one machine will not notice; Starlette still
#: runs handlers in a threadpool, and a race here would read a dataset
#: with another dataset's credentials.
_ENVIRONMENT_LOCK = threading.Lock()


@contextmanager
def _only(store_options: dict | None):
    """Read a dataset the way its own options describe it.

    obstore takes the ambient variables first and offers no opt-out, so a
    machine holding `AWS_ENDPOINT_URL_S3` for one bucket sends every
    other dataset's request there too. DuckDB avoids this with a
    dataset-scoped secret; obstore has no equivalent, so the environment
    is removed for the length of the call instead.

    What gets removed follows the rule DuckDB's secrets follow, and the
    two halves are not symmetric:

    - **where it lives** is scoped. A dataset carrying `store_options`
      has said where it is, and *not* naming an endpoint means the
      provider's default — not "inherit the one this machine happens to
      hold for something else".
    - **how to sign** is inherited unless the dataset says otherwise.
      An endpoint with no keys is the ordinary way to name a bucket you
      already have credentials for. Only a dataset carrying its own
      keys, or asking to be read anonymously, displaces them.

    Both halves were found the hard way, one per collection, on the
    deployment's own configuration: taking too little sent a public
    Overture bucket to a Tigris endpoint; taking too much left a private
    Tigris bucket with no credentials and 38 seconds of EC2-metadata
    retries.

    Editing the process environment is acceptable only because of the
    role separation: this runs in the authoring process, which serves no
    traffic (ADR-0008). It would not be acceptable in the deployment.
    """
    if not store_options:
        yield
        return

    displaced = list(_AMBIENT_ADDRESS)
    if store_options.get("skip_signature") or any(
        name in store_options for name in _OWN_CREDENTIALS
    ):
        displaced += _AMBIENT_CREDENTIALS

    with _ENVIRONMENT_LOCK:
        saved = {name: os.environ.pop(name) for name in displaced if name in os.environ}
        try:
            yield
        finally:
            os.environ.update(saved)


def _unreachable_sources(config: dict):
    """Yield (resource, source, why) for every data source that is absent.

    One code path for local files and buckets: the storage layer treats
    a directory and a prefix the same way, which is the whole point of
    ADR-0003's Protocol. A source naming an object is checked with
    `stat`; one naming a prefix has to list at least something.

    The provider's own `store_options` are what make the check agree with
    the provider. They carry the region, `skip_signature` for public
    data, and — the one that bites — the `endpoint` of an S3-compatible
    service. Without them a public bucket gets signed with whatever
    credentials the process happens to hold, and the request goes
    wherever `AWS_ENDPOINT_URL_S3` happens to point, which is rarely
    where the dataset lives. That is how this check came to report a
    source as unreachable in the same run that served it.
    """
    from app.provider.storage import StorageBridge, load_store, split_source

    for name, resource in (config.get("resources") or {}).items():
        for provider in resource.get("providers") or []:
            data = provider.get("data")
            if not isinstance(data, str) or not data or "*" in data:
                continue  # a glob, or a connection string: not ours to judge
            options = provider.get("store_options")
            try:
                base, key = split_source(data)
                with _only(options):
                    store = load_store(base, options)
                try:
                    StorageBridge(store).stat(key)
                except FileNotFoundError:
                    # Listing is the store's, not the bridge's: the bridge
                    # reads and writes one object, and asking it to list
                    # would turn "nothing is there" into an AttributeError
                    # the operator would read as a fact about their config.
                    if not any(k.startswith(key) for k in store.keys(key)):
                        yield name, data, "nothing is there"
            except Exception as e:  # unreadable store, bad credentials, bad URL
                yield name, data, f"{type(e).__name__}: {str(e).splitlines()[0][:100]}"


def _blame(config: dict, error: Exception) -> str:
    """Name the resource a failure belongs to, when it can be told.

    A build failure arrives as whatever the provider raised, far from
    the configuration that caused it. Matching the message against the
    configured data sources turns "no such file" into "the lakes
    provider cannot read …", which is the difference between a report an
    operator can act on and one they have to decode.
    """
    message = str(error)
    for name, resource in (config.get("resources") or {}).items():
        for provider in resource.get("providers") or []:
            data = provider.get("data")
            if isinstance(data, str) and data and data in message:
                return f"resource '{name}': {type(error).__name__}: {message}"
    return f"{type(error).__name__}: {message}"
