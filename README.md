# fastgeoapi

A FastAPI application leveraged by pygeoapi

[![PyPI](https://img.shields.io/pypi/v/fastgeoapi?logo=pypi&logoColor=white&style=flat-square)](https://pypi.org/project/fastgeoapi/)
[![Python Version](https://img.shields.io/pypi/pyversions/fastgeoapi?logo=python&logoColor=white&style=flat-square)](https://pypi.org/project/fastgeoapi)
[![License](https://img.shields.io/pypi/l/fastgeoapi?style=flat-square)](https://opensource.org/licenses/MIT)

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

- Provide authentication and authorization for vanilla [pygeoapi](https://github.com/geopython/pygeoapi/)

## Requirements

- [pygeoapi](https://github.com/geopython/pygeoapi/)
- [fastapi-opa](https://github.com/busykoala/fastapi-opa)
- An OpenID Connect provider (Keycloak, WSO2, etc)
- Open Policy Agent (OPA)

## Installation

You can install _fastgeoapi_ via [pip](https://pip.pypa.io/) from
[PyPI](https://pypi.org/):

```shell
pip install fastgeoapi
```

## Development

After cloning the repository, you should use `poetry` to create the virtual environment and install the dependencies:

```shell
poetry shell
```

```shell
poetry install
```

Once Keycloak and OPA have been started then you have to configure the required variables for the pygeoapi configuration:

```shell
export PYGEOAPI_CONFIG=example-config.yml
export PYGEOAPI_OPENAPI=example-openapi.yml
```

Finally, you can start fastgeoapi in development mode:

```shell
fastapi dev app/main.py --app app --host 0.0.0.0 --port 5000 --reload
```

## Usage

Please see the [Command-line
Reference](https://fastgeoapi.readthedocs.io/en/latest/usage.html) for
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

## Credits

This project was generated from
[\@cjolowicz](https://github.com/cjolowicz)\'s [Hypermodern Python
Cookiecutter](https://github.com/cjolowicz/cookiecutter-hypermodern-python)
template.
