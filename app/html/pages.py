"""HTML pages rendered by fastgeoapi from the JSON its routes answer.

A route with a page asks itself for JSON, as any client would, and the
page renders that document with a Jinja template. A route without a page
keeps pygeoapi's HTML. An error keeps its JSON answer and its status, and a
request for another format never reaches the page.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from babel.dates import format_datetime
from babel.numbers import format_decimal
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pygeoapi import l10n
from pygeoapi.api import API, APIRequest
from pygeoapi.formats import F_HTML, F_JSON
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from app.html.assets import STYLE, Assets
from app.html.i18n import translations

FORMAT_LABELS = {
    "application/json": "JSON",
    "application/ld+json": "JSON-LD",
    "application/geo+json": "GeoJSON",
    "application/schema+json": "JSON Schema",
}
"""How the bar names the other formats of a page."""


@dataclass(frozen=True)
class PageContext:
    """What a page's view reads to fill its template."""

    document: Any
    """The JSON the route answered, or None for a page that does not ask for it."""
    api: API
    request: APIRequest
    """pygeoapi's view of the request: its parameters and the negotiated locale."""
    path_params: dict[str, str]
    url: str
    """The page's own URL, on the configured server URL."""
    gettext: Callable[[str], str]
    """Translates an interface string into the page's language."""


@dataclass(frozen=True)
class Page:
    """The HTML page of one route."""

    template: str
    view: Callable[[PageContext], dict[str, Any]]
    """Builds the template's variables, ``title`` at least."""
    islands: tuple[str, ...] = ()
    """The manifest entries of the scripts the page loads."""
    needs_document: bool = True
    """False for a page that renders without asking its route for JSON."""


class NativePages:
    """fastgeoapi's pages: each wraps its route and renders the route's JSON."""

    def __init__(
        self, pages: dict[str, Page], templates: list[Path], locale: Path, static: Path
    ) -> None:
        """Pages by route path; templates are searched in order, the first directory first."""
        self._pages = pages
        self._templates = [str(path) for path in templates]
        self._locale = locale
        self.static = static
        self._environments: dict[str, Environment] = {}

    def wrap(self, api: API, routes: list[Route]) -> list[Route]:
        """``routes``, with the ones that have a page answering HTML from their own JSON."""
        assets = Assets(self.static, api.config["server"]["url"])
        return [
            self._wrapped(api, assets, route) if route.path in self._pages else route
            for route in routes
        ]

    def _wrapped(self, api: API, assets: Assets, route: Route) -> Route:
        page = self._pages[route.path]
        inner = route.endpoint

        async def endpoint(request: Request) -> Response:
            # The constructor, not ``from_starlette``: that one reads the body,
            # and the route must still find it when it is called below.
            api_request = APIRequest(request, api.locales)
            if request.method not in ("GET", "HEAD") or api_request.format != F_HTML:
                return await inner(request)
            document = None
            if page.needs_document:
                answer = await inner(_asking_json(request))
                body = getattr(answer, "body", None)
                if answer.status_code >= 400 or body is None:
                    return answer
                try:
                    document = json.loads(body)
                except ValueError:
                    return answer
            return self._render(api, assets, page, request, api_request, document)

        methods = sorted(route.methods - {"HEAD"}) if route.methods else None
        return Route(route.path, endpoint, methods=methods)

    def _render(
        self,
        api: API,
        assets: Assets,
        page: Page,
        request: Request,
        api_request: APIRequest,
        document: Any,
    ) -> Response:
        locale = api_request.locale
        catalog = translations(self._locale, locale.language)
        url = page_url(api, request)
        context = PageContext(
            document, api, api_request, dict(request.path_params), url, catalog.gettext
        )
        links = _links(document)
        variables = {
            **_frame(api, api_request, url, links, catalog.gettext),
            "styles": assets.styles((STYLE, *page.islands)),
            "scripts": assets.scripts(page.islands),
            **page.view(context),
        }
        variables["jsonld"].setdefault("name", variables.get("title", ""))
        template = self._environment(locale.language).get_template(page.template)
        return HTMLResponse(template.render(variables), headers=_headers(url, links, locale))

    def _environment(self, language: str) -> Environment:
        environment = self._environments.get(language)
        if environment is None:
            environment = Environment(
                loader=FileSystemLoader(self._templates),
                autoescape=select_autoescape(("html",)),
                extensions=["jinja2.ext.i18n"],
            )
            environment.install_gettext_translations(
                translations(self._locale, language), newstyle=True
            )
            environment.filters["instant"] = lambda value: format_instant(value, language)
            environment.filters["number"] = lambda value: format_number(value, language)
            self._environments[language] = environment
        return environment


def with_query(url: str, **params: str) -> str:
    """``url`` with ``params`` set in its query, the other parameters kept in order."""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in params
    ]
    query.extend(params.items())
    return urlunsplit(parts._replace(query=urlencode(query)))


def page_url(api: API, request: Request) -> str:
    """The page's URL on the configured server URL, with the request's parameters and ``f=html``.

    The request may come through a proxy, under another host name: the
    links of a page follow the configuration, as pygeoapi's own links do.
    """
    path = request.scope["path"]
    root = request.scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root) :]
    query = [(key, value) for key, value in request.query_params.multi_items() if key != "f"]
    query.append(("f", F_HTML))
    return f"{api.base_url.rstrip('/')}{path.rstrip('/')}?{urlencode(query)}"


def format_instant(value: str | None, language: str) -> str:
    """An ISO 8601 instant, as the page's language writes it; anything else as it is."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    return format_datetime(moment, format="medium", locale=language)


def format_number(value: float | None, language: str) -> str:
    """A number, as the page's language writes it."""
    return "" if value is None else format_decimal(value, locale=language)


def _asking_json(request: Request) -> Request:
    """The same request asking for JSON, uncompressed so that its body can be read."""
    scope = dict(request.scope)
    query = [(key, value) for key, value in request.query_params.multi_items() if key != "f"]
    query.append(("f", F_JSON))
    scope["query_string"] = urlencode(query).encode()
    scope["headers"] = [
        (name, value)
        for name, value in request.scope["headers"]
        if name not in (b"accept", b"accept-encoding")
    ] + [(b"accept", b"application/json")]
    return Request(scope, request.receive)


def _links(document: Any) -> list[dict[str, Any]]:
    links = document.get("links", []) if isinstance(document, dict) else []
    return [link for link in links if isinstance(link, dict) and link.get("href")]


def _formats(url: str, links: list[dict[str, Any]]) -> list[dict[str, str]]:
    found = [
        {
            "label": FORMAT_LABELS.get(link["type"], link["type"]),
            "type": link["type"],
            "href": link["href"],
        }
        for link in links
        if link.get("rel") in ("self", "alternate") and link.get("type") not in (None, "text/html")
    ]
    return found or [
        {"label": "JSON", "type": "application/json", "href": with_query(url, f=F_JSON)}
    ]


def _paging(links: list[dict[str, Any]], rel: str) -> str | None:
    href = next((link["href"] for link in links if link.get("rel") == rel), None)
    return with_query(href, f=F_HTML) if href else None


def _navigation(api: API, _: Callable[[str], str]) -> list[dict[str, str]]:
    base = api.base_url.rstrip("/")
    kinds = {resource.get("type") for resource in api.config.get("resources", {}).values()}
    items = []
    if "collection" in kinds:
        items.append({"label": _("Collections"), "href": f"{base}/collections?f=html"})
    if "process" in kinds:
        items.append({"label": _("Processes"), "href": f"{base}/processes?f=html"})
    items.append({"label": _("API"), "href": f"{base}/openapi?f=html"})
    return items


def _language_name(locale: Any) -> str:
    name = locale.language_name or str(locale)
    return name[:1].upper() + name[1:]


def _frame(
    api: API,
    request: APIRequest,
    url: str,
    links: list[dict[str, Any]],
    _: Callable[[str], str],
) -> dict[str, Any]:
    """What every page shows around its content: the bar, the head links, the crumbs."""
    locale = request.locale
    server = api.config["server"]
    root = server["url"].rstrip("/")
    title = l10n.translate(api.config["metadata"]["identification"]["title"], locale)
    return {
        "lang": l10n.locale2str(locale),
        "dir": locale.text_direction,
        "site": {
            "title": title,
            "home": f"{api.base_url.rstrip('/')}?f=html",
            "logo": server.get("logo") or f"{root}/static/img/logo.png",
            "icon": server.get("icon") or f"{root}/static/img/favicon.ico",
        },
        "nav": _navigation(api, _),
        "languages": [
            {
                "label": _language_name(each),
                "code": l10n.locale2str(each),
                "href": with_query(url, lang=l10n.locale2str(each)),
                "current": each == locale,
            }
            for each in api.locales
        ],
        "formats": _formats(url, links),
        "canonical": url,
        "prev": _paging(links, "prev"),
        "next": _paging(links, "next"),
        "crumbs": [],
        "description": "",
        "jsonld": {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "url": url,
            "isPartOf": {"@type": "DataCatalog", "@id": server["url"], "name": title},
        },
    }


def _headers(url: str, links: list[dict[str, Any]], locale: Any) -> dict[str, str]:
    variants = [f'<{url}>; rel="self"; type="text/html"'] + [
        f'<{each["href"]}>; rel="alternate"; type="{each["type"]}"' for each in _formats(url, links)
    ]
    return {
        "Content-Language": l10n.locale2str(locale),
        "Vary": "Accept, Accept-Language",
        "Link": ", ".join(variants),
    }
