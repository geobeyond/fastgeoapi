# Using UV with FastGeoAPI

UV is a fast Python package installer and resolver written in Rust. This document explains how to use our UV-based setup for FastGeoAPI development.

## Prerequisites

Install UV before getting started:

### macOS / Linux

```bash
curl -sSf https://install.ultraviolet.dev | sh
```

### Windows - PowerShell

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Getting Started with the UV-based FastGeoAPI

### 1. Clone the repository

```bash
git clone https://github.com/geobeyond/fastgeoapi.git
cd fastgeoapi
```

### 2. Install dependencies

The project is already configured with `pyproject.toml`. Simply run:

```bash
uv sync
```

This automatically:

- Creates a virtual environment in `.venv`
- Installs all required dependencies
- Sets up FastGeoAPI in development mode

### 3. Activate the Virtual Environment

After running `uv sync`, you'll need to activate the virtual environment to use FastGeoAPI:

**macOS / Linux:**

```bash
source .venv/bin/activate
```

**Windows (Command Prompt):**

```cmd
.venv\Scripts\activate.bat
```

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

You'll know the environment is activated when you see `(.venv)` at the beginning of your command prompt.

## Working with Git Dependencies

This project uses git-based dependencies. UV automatically handles these based on the `pyproject.toml` configuration. Notable git dependencies include:

- pygeoapi (from github.com/geopython/pygeoapi.git, branch: master)
- pygeofilter (from github.com/geopython/pygeofilter.git, tag: v0.3.1)
- fencer (from github.com/abunuwas/fencer.git, branch: main)

These are defined in the `[tool.uv.sources]` section of the pyproject.toml file.

```bash
uv sync
```

## Working with Optional Dependencies

We've configured the project with a dev dependency group. You can install it as needed:

```bash
# Install with the dev group
uv pip install --group dev
```

Available dependency groups:

- `dev`: Development and testing tools (pytest, black, pre-commit, etc.)

## Daily Development Workflow

### Update dependencies

To update all dependencies to their latest compatible versions:

```bash
uv sync --upgrade
```

### Running FastGeoAPI

After Keycloak and OPA have been started then you have to configure the required variables for the FastGeoAPI configuration:

```shell
export PYGEOAPI_CONFIG=pygeoapi-config.yml
export PYGEOAPI_OPENAPI=pygeoapi-openapi.yml
export FASTGEOAPI_CONTEXT='/geoapi'
```

Finally, you can start FastGeoAPI in development mode:

```shell
uv run fastapi run app/main.py --app app --host 0.0.0.0 --port 5000 --reload
```

### Common UV Commands

```bash
# View installed packages
uv pip list

# Install a new package
uv pip install package-name

# Install a specific version
uv pip install package-name==1.2.3

# Uninstall a package
uv pip uninstall package-name

# Generate requirements.txt
uv pip freeze > requirements.txt
```

## Additional Resources

- [UV Documentation](https://github.com/astral-sh/uv)
- [FastGeoAPI Documentation](https://fastgeoapi.readthedocs.io)
