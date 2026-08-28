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
    """

    ok: bool
    problems: list[str] = field(default_factory=list)
    variables: dict[str, str] = field(default_factory=dict)
    collections: list[str] = field(default_factory=list)


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


def dry_run(text: str) -> Outcome:
    """Build the configuration for real, and report what stood up.

    This is what validation cannot do: a document can satisfy the schema
    and still name a file that is not there, a provider that will not
    import, or a bucket nothing can reach.

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
        subapp = build_pygeoapi_subapp(config, build_openapi(config))
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
    return Outcome(
        ok=not problems,
        problems=problems,
        variables=effective.variables,
        collections=sorted(served),
    )


def _unreachable_sources(config: dict):
    """Yield (resource, source, why) for every data source that is absent.

    One code path for local files and buckets: the storage layer treats
    a directory and a prefix the same way, which is the whole point of
    ADR-0003's Protocol. A source naming an object is checked with
    `stat`; one naming a prefix has to list at least something.
    """
    from app.provider.storage import StorageBridge, load_store, split_source

    for name, resource in (config.get("resources") or {}).items():
        for provider in resource.get("providers") or []:
            data = provider.get("data")
            if not isinstance(data, str) or not data or "*" in data:
                continue  # a glob, or a connection string: not ours to judge
            try:
                base, key = split_source(data)
                bridge = StorageBridge(load_store(base))
                try:
                    bridge.stat(key)
                except FileNotFoundError:
                    if not any(k.startswith(key) for k in bridge.keys(key)):
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
