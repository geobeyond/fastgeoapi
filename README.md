# fastgeoapi

A FastAPI application leveraged by pygeoapi

[![PyPI](https://img.shields.io/pypi/v/fastgeoapi.svg)](https://pypi.org/project/fastgeoapi/)
[![Status](https://img.shields.io/pypi/status/fastgeoapi.svg)](https://pypi.org/project/fastgeoapi/)
[![Python Version](https://img.shields.io/pypi/pyversions/fastgeoapi)](https://pypi.org/project/fastgeoapi)
[![License](https://img.shields.io/pypi/l/fastgeoapi)](https://opensource.org/licenses/MIT)

[![Read the documentation at https://fastgeoapi.readthedocs.io/](https://img.shields.io/readthedocs/fastgeoapi/latest.svg?label=Read%20the%20Docs)](https://fastgeoapi.readthedocs.io/)
[![Tests](https://github.com/geobeyond/fastgeoapi/workflows/Tests/badge.svg)](https://github.com/geobeyond/fastgeoapi/actions?workflow=Tests)
[![Codecov](https://codecov.io/gh/geobeyond/fastgeoapi/branch/main/graph/badge.svg)](https://codecov.io/gh/geobeyond/fastgeoapi)

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Poetry](https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json)](https://python-poetry.org/)

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

```console
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
uvicorn app.main:app --port 5000 --loop asyncio --reload
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
