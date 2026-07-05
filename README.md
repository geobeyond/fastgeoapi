# fastgeoapi

<img width="60" height="60" alt="fastgeoapi logo" src="docs/images/fastgeoapi_logo.png" style="vertical-align: middle;" /> A modern, high-performance geospatial API framework that extends [pygeoapi](https://github.com/geopython/pygeoapi) with authentication, authorization, and security features using FastAPI, OpenID Connect, and Open Policy Agent (OPA) 🗺️🔒.

<div align="center">
  <a href="https://pygeoapi.io">
    <img src="https://pygeoapi.io/img/pygeoapi-logo.png" alt="pygeoapi logo" width="150"/>
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://www.openpolicyagent.org">
    <img src="https://www.openpolicyagent.org/img/logos/opa-horizontal-color.png" alt="Open Policy Agent logo" width="150"/>
  </a>
</div>

[![PyPI](https://img.shields.io/pypi/v/fastgeoapi?logo=pypi&logoColor=white&style=flat-square&label=pypi%20package)](https://pypi.org/project/fastgeoapi/)
[![Status](https://img.shields.io/pypi/status/fastgeoapi?style=flat-square)](https://pypi.org/project/fastgeoapi/)
[![Python](https://img.shields.io/badge/python-3.12%20|%203.13-blue?logo=python&logoColor=white&style=flat-square)](https://www.python.org)
[![License](https://img.shields.io/github/license/geobeyond/fastgeoapi?style=flat-square&label=license)](https://github.com/geobeyond/fastgeoapi/blob/main/LICENSE)

[![Documentation](https://img.shields.io/badge/docs-github%20pages-blue?logo=github&logoColor=white&style=flat-square)](https://geobeyond.github.io/fastgeoapi/)
[![Tests](https://img.shields.io/github/actions/workflow/status/geobeyond/fastgeoapi/tests.yml?branch=main&logo=github&logoColor=white&style=flat-square&label=tests)](https://github.com/geobeyond/fastgeoapi/actions?workflow=Tests)
[![Contract Tests](https://img.shields.io/github/actions/workflow/status/geobeyond/fastgeoapi/contract-tests.yml?branch=main&logo=openapi-initiative&logoColor=white&style=flat-square&label=contract%20tests)](https://github.com/geobeyond/fastgeoapi/actions/workflows/contract-tests.yml)
[![ZAP Scan](https://img.shields.io/github/actions/workflow/status/geobeyond/fastgeoapi/zap-scan.yml?branch=main&logo=owasp&logoColor=white&style=flat-square&label=security)](https://github.com/geobeyond/fastgeoapi/actions/workflows/zap-scan.yml)
[![Codecov](https://img.shields.io/codecov/c/github/geobeyond/fastgeoapi?logo=codecov&logoColor=white&style=flat-square)](https://codecov.io/gh/geobeyond/fastgeoapi)

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=flat-square)](https://github.com/pre-commit/pre-commit)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff&logoColor=white&style=flat-square)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/badge/package%20manager-uv-6366f1?logo=uv&logoColor=white&style=flat-square)](https://github.com/astral-sh/uv)

## Architecture

This diagram gives an overview of the basic architecture:

![general architecture](docs/images/fastgeoapi_architecture.png)

## Features

### 🔐 Security & Authentication

- **OpenID Connect (OIDC) Integration** - OAuth2/JWT Bearer token authentication with JWKS support
- **API Key Authentication** - Flexible API key-based authentication for programmatic access
- **Open Policy Agent (OPA)** - Policy-based authorization with fine-grained access control
- **Multi-scheme Support** - Seamlessly switch between authentication methods based on your needs

### 🚀 Performance & Modern Stack

- **FastAPI Framework** - High-performance async API built on Starlette and Pydantic
- **Async I/O** - Non-blocking operations for better scalability
- **Modern Python** - Python 3.12+ with type hints and modern language features
- **Fast Dependency Management** - UV-based tooling for lightning-fast installations

### 🗺️ Geospatial API Standards

- **OGC API Compliance** - Full support for OGC API - Features, Processes, and more
- **OpenAPI Integration** - Auto-generated, security-enhanced OpenAPI specifications
- **Geospatial Data Access** - Seamless access to vector and raster geospatial data
- **pygeoapi Extension** - Extends vanilla pygeoapi with enterprise-ready security

### 🛡️ Security Testing & Quality

- **Contract Testing** - Automated OpenAPI contract validation with Schemathesis
- **Security Scanning** - OWASP ZAP integration for continuous security testing
- **Pre-commit Hooks** - Code quality checks with Ruff formatting and linting
- **Comprehensive Test Coverage** - Full test suite with pytest and coverage reporting

### 📋 OGC API Conformance

- **Specification Validation** - Automated validation against OGC API standards using [ogcapi-registry](https://github.com/francbartoli/ogcapi-registry)
- **OpenAPI Document Verification** - Ensures generated OpenAPI documents conform to OGC API specifications
- **Conformance Class Reporting** - Detailed reports on declared conformance classes (OGC API - Features, Common, GeoJSON, etc.)
- **CI/CD Integration** - Continuous validation on every deployment to the demo server

## Live Demo

A public demo server is available at **[https://fastgeoapi.fly.dev/geoapi](https://fastgeoapi.fly.dev/geoapi)**.

🔐 The API endpoints are protected with **OAuth2 client-credentials flow**, showcasing fastgeoapi's enterprise-ready security features. This allows you to test the full authentication workflow in a real environment.

The **Swagger UI** documentation is publicly accessible without authentication at [https://fastgeoapi.fly.dev/geoapi/openapi](https://fastgeoapi.fly.dev/geoapi/openapi), allowing you to explore the API specification and available endpoints before authenticating.

### Getting an Access Token

The demo server requires OAuth2 authentication. To obtain an access token:

```bash
curl -X POST https://76hxgq.logto.app/oidc/token \
  -H "Authorization: Basic czRyZjIzbnlucmNvdGM4NnhuaWVxOlc2RHJhQWJ1MTZnb29yR0xWSE02WFlSUnI4aWpObUww" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&resource=http://localhost:5000/geoapi/&scope=openid profile ci"
```

### Using the Access Token

Once you have the token, include it in your requests:

```bash
# Get the landing page
curl -H "Authorization: Bearer <your_access_token>" \
  "https://fastgeoapi.fly.dev/geoapi/?f=json"

# List collections
curl -H "Authorization: Bearer <your_access_token>" \
  "https://fastgeoapi.fly.dev/geoapi/collections?f=json"

# Check conformance
curl -H "Authorization: Bearer <your_access_token>" \
  "https://fastgeoapi.fly.dev/geoapi/conformance?f=json"
```

## Requirements

- [pygeoapi](https://github.com/geopython/pygeoapi/)
- [fastapi-opa](https://github.com/busykoala/fastapi-opa)
- An OpenID Connect provider (Keycloak, WSO2, etc)
- Open Policy Agent (OPA)

## Installation

You can install _fastgeoapi_ via [pip](https://pip.pypa.io/) from [PyPI](https://pypi.org/):

```shell
pip install fastgeoapi
```

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
- Installs all required dependencies including git-based packages from `[tool.uv.sources]` (pygeoapi master, pygeofilter, fencer)
- Sets up fastgeoapi in development mode

> **Note:** For development, UV uses git-based dependencies defined in `[tool.uv.sources]` to get the latest features from upstream projects. The PyPI release uses stable published versions. See [uv.md](uv.md) for more details.

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

## Quick Start (Package Installation)

Install fastgeoapi:

```shell
pip install fastgeoapi
```

Create a `.env` file with the required configuration:

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

# Authentication (choose one, all others must be false)
DEV_API_KEY_ENABLED=false
DEV_JWKS_ENABLED=false
DEV_OPA_ENABLED=false
```

Start the server:

```shell
fastgeoapi run
```

With options:

```shell
fastgeoapi run --host 0.0.0.0 --port 5000 --reload
```

See the [Getting Started guide](https://geobeyond.github.io/fastgeoapi/getting-started/) for complete setup instructions including authentication options and examples.

### Common UV Commands

```bash
# Update dependencies
uv sync --upgrade

# View installed packages
uv pip list

# Install a new package
uv pip install package-name

# Install dev dependencies
uv pip install --group dev
```

For more details, see [uv.md](uv.md).

## Release Workflow

This project uses a branching strategy with automated releases:

| Branch    | Target   | Description                                |
| --------- | -------- | ------------------------------------------ |
| `develop` | TestPyPI | Development releases with `.dev` suffix    |
| `main`    | PyPI     | Production releases when version is bumped |

### Development Releases

Push to `develop` branch triggers automatic publishing to [TestPyPI](https://test.pypi.org/project/fastgeoapi/):

```bash
git checkout develop
# Make changes
git commit -m "feat: add new feature"
git push origin develop
```

The workflow automatically creates a dev version (e.g., `0.0.4.dev.1733912345`) and publishes to TestPyPI.

### Production Releases

To create a production release on [PyPI](https://pypi.org/project/fastgeoapi/):

1. Update the version in `pyproject.toml`
2. Merge to `main` branch
3. The workflow detects the version change, creates a git tag, and publishes to PyPI

```bash
# Update version in pyproject.toml to e.g., 0.0.4
git checkout main
git merge develop
git push origin main
```

Both workflows use [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) (OIDC) for secure, tokenless authentication with PyPI/TestPyPI.

## Usage

Please see the [Command-line
Reference](https://geobeyond.github.io/fastgeoapi/reference/) for
details.

Please have a look at the `docker-compose.yml` file under `scripts/iam` to start the stack with **Keycloak** and **Open Policy Agent** locally. There is a `README.md` file that explains how to use it.

The file `scripts/iam/keycloak/realm-export.json` can be used to import an already configured realm into Keycloak.

The files under `scripts/postman` can be used to setup Postman with a configuration that is ready to perform the requests for the whole stack.

## Contributing

Contributions are very welcome. To learn more, see the [Contributor
Guide](CONTRIBUTING.rst).

## License

Distributed under the terms of the [MIT
license](https://opensource.org/licenses/MIT), _fastgeoapi_ is free and open-source software.

## Issues

If you encounter any problems, please [file an
issue](https://github.com/geobeyond/fastgeoapi/issues) along with a detailed description.

## MCP Server (Model Context Protocol)

fastgeoapi includes an optional integrated MCP server that exposes OGC API endpoints as tools for AI assistants and LLM-based applications. The MCP server is built using [FastMCP](https://github.com/jlowin/fastmcp) and automatically generates tools from the pygeoapi OpenAPI specification.

### Features

- **Automatic Tool Generation** - Tools are generated from the OGC API OpenAPI spec
- **OAuth Authentication** - Supports OIDC authentication with any OAuth provider (Logto, Auth0, Keycloak, etc.)
- **RFC 9728 Compliant** - Implements OAuth 2.0 Protected Resource Metadata
- **Dynamic Client Registration** - Compatible with mcp-remote and other MCP clients
- **Provider Agnostic** - Uses [mcpauth](https://github.com/alonsosilvaallende/mcpauth) for multi-IdP support

### Enabling the MCP Server

To enable the MCP server, set the `FASTGEOAPI_WITH_MCP` environment variable:

```shell
# In your .env file
DEV_FASTGEOAPI_WITH_MCP=true

# Or for production
PROD_FASTGEOAPI_WITH_MCP=true
```

The MCP server will be mounted at `/mcp` endpoint.

### Configuration

#### Basic Configuration (No Authentication)

```shell
# .env file
ENV_STATE=dev
DEV_FASTGEOAPI_WITH_MCP=true
DEV_PYGEOAPI_CONFIG=pygeoapi-config.yml
DEV_PYGEOAPI_OPENAPI=pygeoapi-openapi.yml
```

#### With OAuth Authentication

To enable OAuth authentication for the MCP server, configure JWKS:

```shell
# .env file
ENV_STATE=dev
DEV_FASTGEOAPI_WITH_MCP=true
DEV_JWKS_ENABLED=true
DEV_OIDC_WELL_KNOWN_ENDPOINT=https://your-idp.example.com/.well-known/openid-configuration
DEV_OIDC_CLIENT_ID=your-client-id
DEV_OIDC_CLIENT_SECRET=your-client-secret

# Optional MCP OAuth tuning (see docs/mcp-server.md for details)
# Consent screen behavior: always | remember | external | never
DEV_FASTGEOAPI_MCP_CONSENT_MODE=remember
# Client-facing access-token lifetime, decoupled from the IdP expires_in
DEV_FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS=86400
```

The requested scopes include `offline_access` by default, so the IdP issues a refresh token and MCP clients can renew silently instead of re-running the browser authorization on every token expiry (make sure your IdP allows that scope for the client).

### Security & Authentication Flows

The MCP server supports multiple security configurations depending on your deployment needs.

#### Supported OAuth 2.0 Flows

| Flow                                  | Use Case                                         | Configuration                        |
| ------------------------------------- | ------------------------------------------------ | ------------------------------------ |
| **Authorization Code + PKCE**         | Interactive clients (Claude Desktop, mcp-remote) | `JWKS_ENABLED=true` with OIDC config |
| **Client Credentials**                | Machine-to-machine, service accounts             | `JWKS_ENABLED=true` with OIDC config |
| **Dynamic Client Registration (DCR)** | Auto-registration for MCP clients                | Enabled automatically with OIDC      |

#### OAuth Proxy Architecture

When OAuth is enabled, the MCP server acts as an **OAuth Proxy** implementing:

- **RFC 8414** - OAuth 2.0 Authorization Server Metadata
- **RFC 9728** - OAuth 2.0 Protected Resource Metadata
- **RFC 7636** - Proof Key for Code Exchange (PKCE)
- **RFC 7591** - OAuth 2.0 Dynamic Client Registration

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   MCP Client    │────▶│   MCP Server    │────▶│   Identity      │
│  (mcp-remote)   │     │  (OAuth Proxy)  │     │   Provider      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        │  1. Discovery         │                       │
        │──────────────────────▶│                       │
        │  /.well-known/...     │                       │
        │                       │                       │
        │  2. DCR (register)    │                       │
        │──────────────────────▶│                       │
        │                       │                       │
        │  3. Authorization     │  4. Redirect to IdP   │
        │──────────────────────▶│──────────────────────▶│
        │                       │                       │
        │                       │  5. Auth Code         │
        │                       │◀──────────────────────│
        │  6. Token Exchange    │                       │
        │◀──────────────────────│                       │
        │                       │                       │
        │  7. MCP Requests      │  8. In-process ASGI   │
        │  (with Bearer token)  │     call to pygeoapi  │
        │──────────────────────▶│──────────────────────▶│
```

#### Security Features

| Feature                       | Description                                                                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **JWT Validation**            | Tokens are validated using JWKS from the IdP                                                                                   |
| **Opaque Token Support**      | Supports IdPs that return opaque tokens (e.g., Logto without API Resources)                                                    |
| **RFC 6750 Compliance**       | Proper error handling for missing vs invalid tokens                                                                            |
| **In-Process Internal Calls** | MCP-to-pygeoapi calls run in-process via `httpx.ASGITransport` on a non-routable virtual host — no bypass key or header exists |
| **Scope Validation**          | Configurable required scopes for access control                                                                                |

#### Supported Identity Providers

The MCP server is provider-agnostic and works with any OIDC-compliant IdP:

- **Logto** - Tested with OAuth proxy and DCR
- **Auth0** - Full OIDC support
- **Keycloak** - Full OIDC and OPA integration
- **Okta** - Standard OIDC flows
- **Azure AD** - Microsoft identity platform
- **Google** - Google OAuth 2.0

### Using the MCP Server

#### With Claude Desktop (native connector, recommended)

Claude Desktop supports remote MCP servers natively as **custom connectors** — no local shim or config-file edit required:

1. Open **Settings → Connectors → Add custom connector**
2. Paste the server URL: `https://your-domain.com/mcp/` (trailing slash optional)
3. Complete the OAuth login in the browser popup on first use

If an older `mcp-remote`-based entry for the same server is still in `claude_desktop_config.json`, remove it — the two clients race through the OAuth flow and can leave the tools list stuck.

#### With stdio-only clients (mcp-remote)

For MCP clients that only speak stdio, front the server with [mcp-remote](https://www.npmjs.com/package/mcp-remote):

```json
{
  "mcpServers": {
    "fastgeoapi": {
      "command": "npx",
      "args": ["mcp-remote", "https://your-domain.com/mcp/"]
    }
  }
}
```

For local development over plain HTTP, add the `--allow-http` flag. Note that mcp-remote keeps tokens only in process memory, so every restart re-runs the full OAuth dance.

#### Direct Streamable HTTP Connection

fastmcp 3.x serves MCP over the Streamable HTTP transport (the legacy `/mcp/sse` endpoint no longer exists). Clients with native remote MCP support connect directly to:

```
http://localhost:5000/mcp/
```

### Available Tools

The MCP server exposes all OGC API endpoints as tools. Names come from the OpenAPI `operationId`s, so collection-specific tools embed the collection name (the demo configuration yields 27 tools). For example:

| Tool                        | Description                                                  |
| --------------------------- | ------------------------------------------------------------ |
| `getLandingPage`            | Get the API landing page                                     |
| `getConformanceDeclaration` | Get OGC API conformance classes                              |
| `getCollections`            | List all feature collections                                 |
| `describeLakesCollection`   | Get metadata for the `lakes` collection                      |
| `getLakesFeatures`          | Query features from the `lakes` collection                   |
| `getLakesFeature`           | Get a specific `lakes` feature by ID                         |
| `getProcesses`              | List available processes (if OGC API - Processes is enabled) |

### OAuth Discovery Endpoints

When OAuth is enabled, the following RFC-compliant endpoints are available:

| Endpoint                                      | Description                                          |
| --------------------------------------------- | ---------------------------------------------------- |
| `/.well-known/oauth-protected-resource/mcp/`  | Protected resource metadata (RFC 9728)               |
| `/.well-known/oauth-authorization-server/mcp` | Authorization server metadata (RFC 8414, path-aware) |
| `/.well-known/openid-configuration`           | OIDC discovery alias (fastmcp >= 3.4)                |

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Desktop                        │
│                    or MCP Client                         │
└─────────────────────┬───────────────────────────────────┘
                      │ MCP Protocol (Streamable HTTP)
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   fastgeoapi                             │
│  ┌───────────────────────────────────────────────────┐  │
│  │              MCP Server (/mcp)                     │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │  │
│  │  │ OAuth Proxy │  │ Tool Router │  │ HTTP      │  │  │
│  │  └─────────────┘  └─────────────┘  └───────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
│                          │                               │
│                          ▼                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │           pygeoapi OGC API (/geoapi)              │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Credits

This project was generated from
[\@cjolowicz](https://github.com/cjolowicz)\'s [Hypermodern Python
Cookiecutter](https://github.com/cjolowicz/cookiecutter-hypermodern-python)
template.
