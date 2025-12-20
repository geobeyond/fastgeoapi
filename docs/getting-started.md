# Getting started

## Live Demo Server

A public demo server is available for testing and exploration:

**Demo URL:** [https://fastgeoapi.fly.dev/geoapi](https://fastgeoapi.fly.dev/geoapi)

The demo server is protected with **OAuth2 client-credentials flow**, demonstrating fastgeoapi's security capabilities in a real-world scenario.

### Obtaining an Access Token

To access the demo server, you need to obtain an OAuth2 access token using the client-credentials grant:

```bash
curl -X POST https://76hxgq.logto.app/oidc/token \
  -H "Authorization: Basic czRyZjIzbnlucmNvdGM4NnhuaWVxOlc2RHJhQWJ1MTZnb29yR0xWSE02WFlSUnI4aWpObUww" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&resource=http://localhost:5000/geoapi/&scope=openid profile ci"
```

The response will contain an `access_token`:

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### Making Authenticated Requests

Include the access token in the `Authorization` header:

```bash
# Store the token in a variable
TOKEN=$(curl -s -X POST https://76hxgq.logto.app/oidc/token \
  -H "Authorization: Basic czRyZjIzbnlucmNvdGM4NnhuaWVxOlc2RHJhQWJ1MTZnb29yR0xWSE02WFlSUnI4aWpObUww" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&resource=http://localhost:5000/geoapi/&scope=openid profile ci" \
  | jq -r '.access_token')

# Landing page
curl -H "Authorization: Bearer $TOKEN" \
  "https://fastgeoapi.fly.dev/geoapi/?f=json"

# List available collections
curl -H "Authorization: Bearer $TOKEN" \
  "https://fastgeoapi.fly.dev/geoapi/collections?f=json"

# View conformance classes
curl -H "Authorization: Bearer $TOKEN" \
  "https://fastgeoapi.fly.dev/geoapi/conformance?f=json"

# Access OpenAPI specification
curl -H "Authorization: Bearer $TOKEN" \
  "https://fastgeoapi.fly.dev/geoapi/openapi?f=json"
```

### OAuth2 Configuration Details

| Parameter      | Value                                 |
| -------------- | ------------------------------------- |
| Token Endpoint | `https://76hxgq.logto.app/oidc/token` |
| Grant Type     | `client_credentials`                  |
| Scope          | `openid profile ci`                   |
| Resource       | `http://localhost:5000/geoapi/`       |

The Basic Authentication header contains the base64-encoded `client_id:client_secret` credentials for the demo application.

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

#### Development workflow

This workflow is for contributing to fastgeoapi itself by cloning the repository.

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

#### Application workflow

This workflow is for using fastgeoapi as a Python package to build your own FastAPI application.

##### Installation

Install fastgeoapi in your project:

```shell
pip install fastgeoapi
```

Or with UV:

```shell
uv add fastgeoapi
```

##### Running Your Application

When using fastgeoapi as an installed package, you can start the server using the `fastgeoapi` CLI:

```shell
fastgeoapi run
```

With options:

```shell
fastgeoapi run --host 0.0.0.0 --port 5000 --reload
```

Or using uvicorn directly:

```shell
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

##### Verifying the Setup

Once running, verify the endpoints are accessible:

```shell
# Landing page
curl http://localhost:5000/geoapi/?f=json

# OpenAPI specification
curl http://localhost:5000/geoapi/openapi?f=json

# Collections
curl http://localhost:5000/geoapi/collections?f=json

# Conformance
curl http://localhost:5000/geoapi/conformance?f=json
```

#### Environment Configuration

The following configuration applies to both the Development and Application workflows.

fastgeoapi uses environment variables to configure its behavior. The main variable is `ENV_STATE` which determines whether to load development (`dev`) or production (`prod`) configuration.

Create a `.env` file in your project root:

```shell
# Environment state: 'dev' or 'prod'
ENV_STATE=dev

# Server configuration
HOST=0.0.0.0
PORT=5000

# Logging (required)
DEV_LOG_PATH=/tmp
DEV_LOG_FILENAME=fastgeoapi.log
DEV_LOG_LEVEL=debug
DEV_LOG_ENQUEUE=true
DEV_LOG_ROTATION=1 days
DEV_LOG_RETENTION=1 months

# Pygeoapi configuration
DEV_PYGEOAPI_BASEURL=http://localhost:5000
DEV_PYGEOAPI_CONFIG=pygeoapi-config.yml
DEV_PYGEOAPI_OPENAPI=pygeoapi-openapi.yml
DEV_FASTGEOAPI_CONTEXT=/geoapi
```

#### Authentication Options

The following authentication options apply to both the Development and Application workflows.

fastgeoapi supports three mutually exclusive authentication methods. Only one can be enabled at a time.

**Option 1: No Authentication (Open Access)**

```shell
DEV_API_KEY_ENABLED=false
DEV_JWKS_ENABLED=false
DEV_OPA_ENABLED=false
```

**Option 2: API Key Authentication**

```shell
DEV_API_KEY_ENABLED=true
DEV_PYGEOAPI_KEY_GLOBAL=your-secret-api-key
DEV_JWKS_ENABLED=false
DEV_OPA_ENABLED=false
```

Clients must include the `X-API-KEY` header in requests:

```shell
curl -H "X-API-KEY: your-secret-api-key" http://localhost:5000/geoapi/collections
```

**Option 3: OAuth2/JWKS Authentication**

```shell
DEV_JWKS_ENABLED=true
DEV_OAUTH2_JWKS_ENDPOINT=https://your-auth-server/.well-known/jwks.json
DEV_OAUTH2_TOKEN_ENDPOINT=https://your-auth-server/oauth/token
DEV_API_KEY_ENABLED=false
DEV_OPA_ENABLED=false
```

**Option 4: Open Policy Agent (OPA) Authorization**

```shell
DEV_OPA_ENABLED=true
DEV_OPA_URL=http://localhost:8181
DEV_OIDC_WELL_KNOWN_ENDPOINT=http://localhost:8080/realms/master/.well-known/openid-configuration
DEV_OIDC_CLIENT_ID=your-client-id
DEV_OIDC_CLIENT_SECRET=your-client-secret
DEV_API_KEY_ENABLED=false
DEV_JWKS_ENABLED=false
```

#### Startup Flow

The following startup flow applies to both the Development and Application workflows.

When the application starts, fastgeoapi performs the following steps:

1. **Load Configuration**: Reads `ENV_STATE` to determine which configuration to use (`DevConfig` or `ProdConfig`)
2. **Initialize FastAPI**: Creates the FastAPI application with CORS middleware
3. **Set Pygeoapi Variables**: Configures pygeoapi environment variables (`PYGEOAPI_CONFIG`, `PYGEOAPI_OPENAPI`, etc.)
4. **Generate OpenAPI**: If `pygeoapi-openapi.yml` doesn't exist, generates it from `pygeoapi-config.yml`
5. **Apply Authentication**: Based on configuration, adds the appropriate authentication middleware
6. **Mount Pygeoapi**: Mounts the pygeoapi application at the configured context path (e.g., `/geoapi`)

#### AWS Lambda Deployment

The following configuration applies to both the Development and Application workflows.

To deploy on AWS Lambda, enable the Mangum handler:

```shell
DEV_AWS_LAMBDA_DEPLOY=true
# Disable log enqueue for Lambda compatibility
DEV_LOG_ENQUEUE=false
```

The application automatically creates a `handler` object compatible with AWS Lambda when `AWS_LAMBDA_DEPLOY=true`.

#### Example: Complete Application Setup with API Key

This example demonstrates how to create a new project using fastgeoapi as a package with API Key authentication.

##### Step 1: Create a new project

```shell
mkdir my-geoapi-app
cd my-geoapi-app
uv init --name my-geoapi-app
```

##### Step 2: Install fastgeoapi

```shell
uv add fastgeoapi
```

##### Step 3: Create the pygeoapi configuration

Create a `pygeoapi-config.yml` file with your data sources. Here's a minimal example:

```yaml
server:
  bind:
    host: ${HOST}
    port: ${PORT}
  url: ${PYGEOAPI_BASEURL}${FASTGEOAPI_CONTEXT}
  mimetype: application/json; charset=UTF-8
  encoding: utf-8
  languages:
    - en-US
  pretty_print: true
  limits:
    default_items: 20
    max_items: 50

logging:
  level: ERROR

metadata:
  identification:
    title: My GeoAPI Instance
    description: My geospatial data API
    keywords:
      - geospatial
      - api
    terms_of_service: https://creativecommons.org/licenses/by/4.0/
    url: https://example.org
  license:
    name: CC-BY 4.0 license
    url: https://creativecommons.org/licenses/by/4.0/
  provider:
    name: My Organization
    url: https://example.org
  contact:
    name: Contact Name
    email: contact@example.org

resources:
  # Add your data sources here
```

##### Step 4: Create the environment file

Create a `.env` file with all required configuration:

```shell
# Environment state
ENV_STATE=dev

# Server configuration
HOST=0.0.0.0
PORT=5000

# Logging (required)
DEV_LOG_PATH=/tmp
DEV_LOG_FILENAME=fastgeoapi.log
DEV_LOG_LEVEL=debug
DEV_LOG_ENQUEUE=true
DEV_LOG_ROTATION=1 days
DEV_LOG_RETENTION=1 months

# Pygeoapi configuration
DEV_PYGEOAPI_BASEURL=http://localhost:5000
DEV_PYGEOAPI_CONFIG=pygeoapi-config.yml
DEV_PYGEOAPI_OPENAPI=pygeoapi-openapi.yml
DEV_FASTGEOAPI_CONTEXT=/geoapi

# API Key authentication
DEV_API_KEY_ENABLED=true
DEV_PYGEOAPI_KEY_GLOBAL=my-secret-api-key
DEV_JWKS_ENABLED=false
DEV_OPA_ENABLED=false
```

##### Step 5: Start the server

```shell
# Set the API key environment variable for the middleware
export PYGEOAPI_KEY_GLOBAL=my-secret-api-key

# Start the server using the fastgeoapi CLI
fastgeoapi run

# Or with options
fastgeoapi run --host 0.0.0.0 --port 5000

# Alternatively, using uvicorn directly
uvicorn app.main:app --host 0.0.0.0 --port 5000
```

##### Step 6: Verify the endpoints

Test that the API is running correctly:

```shell
# OpenAPI specification (public, no auth required)
curl http://localhost:5000/geoapi/openapi?f=json

# Landing page without API key (should return 401)
curl http://localhost:5000/geoapi/?f=json
# Response: {"detail":"no api key"}

# Landing page with API key (should return 200)
curl -H "X-API-KEY: my-secret-api-key" http://localhost:5000/geoapi/?f=json

# Collections with API key
curl -H "X-API-KEY: my-secret-api-key" http://localhost:5000/geoapi/collections?f=json

# Conformance with API key
curl -H "X-API-KEY: my-secret-api-key" http://localhost:5000/geoapi/conformance?f=json
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

| Branch    | Target                                                | Description                                |
| --------- | ----------------------------------------------------- | ------------------------------------------ |
| `develop` | [TestPyPI](https://test.pypi.org/project/fastgeoapi/) | Development releases with `.dev` suffix    |
| `main`    | [PyPI](https://pypi.org/project/fastgeoapi/)          | Production releases when version is bumped |

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
