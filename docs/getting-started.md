# Getting started

## Development

### Prerequisites

Install [UV](https://github.com/astral-sh/uv) - a fast Python package installer and resolver:

**macOS / Linux:**

```bash
curl -sSf https://install.ultraviolet.dev | sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Setup

After cloning the repository, use UV to install dependencies:

```shell
git clone https://github.com/geobeyond/fastgeoapi.git
cd fastgeoapi
uv sync
```

This automatically:

- Creates a virtual environment in `.venv`
- Installs all required dependencies including git-based packages from `[tool.uv.sources]`
- Sets up fastgeoapi in development mode

For development, UV uses git-based dependencies defined in `[tool.uv.sources]` to get the latest features from upstream projects (pygeoapi master, pygeofilter, fencer). The PyPI release uses stable published versions.

### Activate the Virtual Environment

**macOS / Linux:**

```bash
source .venv/bin/activate
```

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

### Running fastgeoapi

Once Keycloak and OPA have been started, configure the required environment variables:

```shell
export PYGEOAPI_CONFIG=pygeoapi-config.yml
export PYGEOAPI_OPENAPI=pygeoapi-openapi.yml
export FASTGEOAPI_CONTEXT='/geoapi'
```

Start fastgeoapi in development mode:

```shell
uv run fastapi run app/main.py --app app --host 0.0.0.0 --port 5000 --reload
```

## Release Workflow

This project uses a branching strategy with automated releases via GitHub Actions:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   develop   │────▶│    main     │────▶│    PyPI     │
│             │     │             │     │  (release)  │
└──────┬──────┘     └─────────────┘     └─────────────┘
       │
       ▼
┌─────────────┐
│  TestPyPI   │
│    (dev)    │
└─────────────┘
```

### Branches and Targets

| Branch | Target | Description |
|--------|--------|-------------|
| `develop` | [TestPyPI](https://test.pypi.org/project/fastgeoapi/) | Development releases with `.dev` suffix |
| `main` | [PyPI](https://pypi.org/project/fastgeoapi/) | Production releases when version is bumped |

### Development Releases (TestPyPI)

Every push to the `develop` branch triggers automatic publishing to TestPyPI:

```bash
git checkout develop
# Make changes
git commit -m "feat: add new feature"
git push origin develop
```

The workflow automatically:

1. Bumps the version with a `.dev` suffix (e.g., `0.0.4.dev.1733912345`)
2. Builds the package
3. Publishes to TestPyPI using trusted publisher

You can install the development version:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ fastgeoapi
```

### Production Releases (PyPI)

To create a production release:

1. Update the version in `pyproject.toml` (e.g., `0.0.3` → `0.0.4`)
2. Merge changes to `main` branch
3. Push to trigger the release workflow

```bash
# Update version in pyproject.toml
git checkout main
git merge develop
git push origin main
```

The workflow automatically:

1. Detects the version change
2. Creates a git tag (e.g., `v0.0.4`)
3. Builds the package
4. Publishes to PyPI using trusted publisher
5. Creates release notes via Release Drafter

### Trusted Publisher

Both PyPI and TestPyPI publishing use [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) (OIDC) for secure, tokenless authentication. This eliminates the need for API tokens and provides better security through short-lived credentials.

## Production

### Behind a proxy

If the deployment is operated behind a proxy (i.e. Traefik, Nginx, WSO2 Gateway, etc), fastgeoapi provides a reverse proxy configuration to return the pygeoapi links accordingly to the urls called by the users.
The configuration is disabled by default with the following configuration `PROD_FASTGEOAPI_REVERSE_PROXY=false` in the `.env` file. The most relevant configurations for production in a reverse proxy scenario are:

- `PROD_FASTGEOAPI_CONTEXT`: the base path where pygeoapi is operated, i.e. `/geoapi`
- `PROD_FASTGEOAPI_REVERSE_PROXY`: boolean flag to enable or disable the reverse proxy configuration, i.e. `true`

At runtime, if the variable `FASTGEOAPI_REVERSE_PROXY` has the value `true` the returned pygeoapi links are dynamic. This means, for example, that a Kubernetes Ingress with multiple hosts might be supported
in a transparent way:

```yml
# snippet example of a kubernetes ingress with multiple hosts
spec:
  rules:
    - host: public.pygeoapi.io
      http:
        paths:
          - backend:
              serviceName: fastgeoapi-svc
              servicePort: 5000
            path: /geoapi
            pathType: ImplementationSpecific
    - host: private.pygeoapi.io
      http:
        paths:
          - backend:
              serviceName: fastgeoapi-svc
              servicePort: 5000
            path: /geoapi
            pathType: ImplementationSpecific
```

If the user calls the public url `http://public.pygeoapi.io` the response contains the links which respect this base url without the need to have it hard-coded in the pygeoapi configuration `pygeoapi-config.yml`.

<!-- termynal -->

```shell
# Using a security scheme driven by an api-key
$ curl -H "X-API-KEY: pygeoapi" http://public.pygeoapi.io/geoapi/collections/obs

{
    "id":"obs",
    "title":"Observations",
    "description":"My cool observations",
    "keywords":[
        "observations",
        "monitoring"
    ],
    "links":[
        {
            "type":"text/csv",
            "rel":"canonical",
            "title":"data",
            "href":"https://github.com/mapserver/mapserver/blob/branch-7-0/msautotest/wxs/data/obs.csv",
            "hreflang":"en-US"
        },
        {
            "type":"text/csv",
            "rel":"alternate",
            "title":"data",
            "href":"https://raw.githubusercontent.com/mapserver/mapserver/branch-7-0/msautotest/wxs/data/obs.csv",
            "hreflang":"en-US"
        },
        {
            "type":"application/json",
            "rel":"root",
            "title":"The landing page of this server as JSON",
            "href":"http://public.pygeoapi.io/geoapi?f=json"
        },
        {
            "type":"text/html",
            "rel":"root",
            "title":"The landing page of this server as HTML",
            "href":"http://public.pygeoapi.io/geoapi?f=html"
        },
        {
            "type":"application/json",
            "rel":"self",
            "title":"This document as JSON",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs?f=json"
        },
        {
            "type":"application/ld+json",
            "rel":"alternate",
            "title":"This document as RDF (JSON-LD)",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs?f=jsonld"
        },
        {
            "type":"text/html",
            "rel":"alternate",
            "title":"This document as HTML",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs?f=html"
        },
        {
            "type":"application/schema+json",
            "rel":"http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "title":"Queryables for this collection as JSON",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/queryables?f=json"
        },
        {
            "type":"text/html",
            "rel":"http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "title":"Queryables for this collection as HTML",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/queryables?f=html"
        },
        {
            "type":"application/geo+json",
            "rel":"items",
            "title":"items as GeoJSON",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/items?f=json"
        },
        {
            "type":"application/ld+json",
            "rel":"items",
            "title":"items as RDF (GeoJSON-LD)",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/items?f=jsonld"
        },
        {
            "type":"text/html",
            "rel":"items",
            "title":"Items as HTML",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/items?f=html"
        }
    ],
    "extent":{
        "spatial":{
            "bbox":[
                [
                    -180,
                    -90,
                    180,
                    90
                ]
            ],
            "crs":"http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        },
        "temporal":{
            "interval":[
                [
                    "2000-10-30T18:24:39+00:00",
                    "2007-10-30T08:57:29+00:00"
                ]
            ]
        }
    },
    "itemType":"feature",
    "crs":[
        "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    ],
    "storageCRS":"http://www.opengis.net/def/crs/OGC/1.3/CRS84"
}
```

The same result would have been got if a private endpoint is hit, i.e. `http://private.pygeoapi.io/geoapi/collections/obs`
