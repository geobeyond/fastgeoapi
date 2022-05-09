"""Main module."""
from typing import Any

import loguru
import uvicorn
from app.config.app import configuration as cfg
from app.config.auth import opa_config
from app.config.logging import create_logger
from app.utils.app_exceptions import app_exception_handler
from app.utils.app_exceptions import AppExceptionError
from app.utils.request_exceptions import http_exception_handler
from app.utils.request_exceptions import request_validation_exception_handler
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi_opa import OPAMiddleware
from mangum import Mangum
from pygeoapi.starlette_app import app as pygeoapi_app
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware


class FastGeoAPI(FastAPI):
    """Subclass of FastAPI that possesses a logger attribute."""

    def __init__(self, **extra: Any):
        """Included the self.logger attribute."""
        super().__init__(**extra)
        self.logger: loguru.Logger = loguru.logger


def create_app() -> FastGeoAPI:
    """Handle application creation."""
    app = FastGeoAPI(title="Fastgeoapi", root_path=cfg.ROOT_PATH, debug=True)

    # Set all CORS enabled origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(request, e):
        return await http_exception_handler(request, e)

    @app.exception_handler(RequestValidationError)
    async def custom_validation_exception_handler(request, e):
        return await request_validation_exception_handler(request, e)

    @app.exception_handler(AppExceptionError)
    async def custom_app_exception_handler(request, e):
        return await app_exception_handler(request, e)

    # Add OPAMiddleware to the pygeoapi app
    pygeoapi_app.add_middleware(OPAMiddleware, config=opa_config)
    app.mount(path="/api", app=pygeoapi_app)

    app.logger = create_logger(name="app.main")

    return app


app = create_app()

app.logger.debug(f"Global config: {cfg.__repr__()}")

if cfg.AWS_LAMBDA_DEPLOY:
    # to make it work with Amazon Lambda,
    # we create a handler object
    handler = Mangum(app)

if __name__ == "__main__":
    uvicorn.run(app, port=5000)
