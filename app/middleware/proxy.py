"""Reversed proxied pygeoapi links middleware module."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config.app import configuration as cfg
from app.config.logging import create_logger

logger = create_logger("app.middleware.proxy")


class ForwardedLinksMiddleware(BaseHTTPMiddleware):
    """Pygeoapi links behind a proxy middleware."""

    async def dispatch(self, request, call_next):
        """Dispatch response with reverse proxied links."""
        response_ = await call_next(request)
        logger.debug(f"Response headers: {response_.raw_headers}")
        response_body = b""
        async for chunk in response_.body_iterator:
            response_body += chunk
        response = Response(
            content=response_body,
            status_code=response_.status_code,
            headers=dict(response_.headers),
            media_type=response_.media_type,
        )
        if request.headers.get("x-forwarded-proto") and request.headers.get("x-forwarded-host"):
            logger.info(f"Forwarded protocol: {request.headers['x-forwarded-proto']}")
            logger.info(f"Forwarded host: {request.headers['x-forwarded-host']}")
            if response_.headers["content-type"] in [
                "text/html",
                "application/json",
                "application/ld+json",
                "application/schema+json",
                "application/vnd.oai.openapi+json;version=3.0",
            ]:
                body_ = response_body.decode("utf-8")
                proxied_base_url = f"{request.headers['x-forwarded-proto']}://{request.headers['x-forwarded-host']}"
                logger.info(
                    f"Replacing pygeoapi urls: {cfg.PYGEOAPI_BASEURL} --> {proxied_base_url}"
                )
                body = body_.replace(cfg.PYGEOAPI_BASEURL, proxied_base_url)
                response = Response(
                    content=body,
                    status_code=response_.status_code,
                    headers=dict(response_.headers),
                    media_type=response_.media_type,
                )
                response.headers["x-pygeoapi-forwarded-url"] = f"{proxied_base_url}"
        response.headers["content-length"] = str(len(response.body))
        return response
