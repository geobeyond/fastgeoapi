"""App configuration module."""

from functools import lru_cache
from typing import Optional

import pydantic
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class GlobalConfig(BaseSettings):
    """Global configurations."""

    # This variable will be loaded from the .env file. However, if there is a
    # shell environment variable having the same name, that will take precedence.

    ENV_STATE: Optional[str] = pydantic.Field(None, env="ENV_STATE")  # type: ignore
    HOST: Optional[str] = pydantic.Field(None, env="HOST")  # type: ignore
    PORT: Optional[str] = pydantic.Field(None, env="PORT")  # type: ignore

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
        env_prefix="",
        env_nested_delimiter="_",
    )


class DevConfig(GlobalConfig):
    """Development configurations."""

    ROOT_PATH: Optional[str] = pydantic.Field(None, env="DEV_ROOT_PATH")  # type: ignore
    AWS_LAMBDA_DEPLOY: Optional[bool] = pydantic.Field(
        None, env="DEV_AWS_LAMBDA_DEPLOY"  # type: ignore
    )
    LOG_PATH: Optional[str] = pydantic.Field(None, env="DEV_LOG_PATH")  # type: ignore
    LOG_FILENAME: Optional[str] = pydantic.Field(
        None, env="DEV_LOG_FILENAME"  # type: ignore
    )
    LOG_LEVEL: Optional[str] = pydantic.Field(None, env="DEV_LOG_LEVEL")  # type: ignore
    LOG_ENQUEUE: Optional[bool] = pydantic.Field(
        None, env="DEV_LOG_ENQUEUE"  # type: ignore
    )
    LOG_ROTATION: Optional[str] = pydantic.Field(
        None, env="DEV_LOG_ROTATION"  # type: ignore
    )
    LOG_RETENTION: Optional[str] = pydantic.Field(
        None, env="DEV_LOG_RETENTION"  # type: ignore
    )
    LOG_FORMAT: Optional[str] = pydantic.Field(
        None, env="DEV_LOG_FORMAT"  # type: ignore
    )
    OPA_ENABLED: Optional[bool] = pydantic.Field(
        None, env="DEV_OPA_ENABLED"  # type: ignore
    )
    OPA_URL: Optional[str] = pydantic.Field(None, env="DEV_OPA_URL")  # type: ignore
    APP_URI: Optional[str] = pydantic.Field(None, env="DEV_APP_URI")  # type: ignore
    OIDC_WELL_KNOWN_ENDPOINT: Optional[str] = pydantic.Field(
        None, env="DEV_OIDC_WELL_KNOWN_ENDPOINT"  # type: ignore
    )
    OIDC_CLIENT_ID: Optional[str] = pydantic.Field(
        None, env="DEV_OIDC_CLIENT_ID"  # type: ignore
    )
    OIDC_CLIENT_SECRET: Optional[str] = pydantic.Field(
        None, env="DEV_OIDC_CLIENT_SECRET"  # type: ignore
    )
    API_KEY_ENABLED: Optional[bool] = pydantic.Field(
        None, env="DEV_API_KEY_ENABLED"  # type: ignore
    )
    JWKS_ENABLED: Optional[bool] = pydantic.Field(
        None, env="DEV_JWKS_ENABLED"  # type: ignore
    )
    OAUTH2_JWKS_ENDPOINT: Optional[str] = pydantic.Field(
        None, env="DEV_OAUTH2_JWKS_ENDPOINT"  # type: ignore
    )
    OAUTH2_TOKEN_ENDPOINT: Optional[str] = pydantic.Field(
        None, env="DEV_OAUTH2_TOKEN_ENDPOINT"  # type: ignore
    )
    PYGEOAPI_KEY_GLOBAL: Optional[str] = pydantic.Field(
        None, env="DEV_PYGEOAPI_KEY_GLOBAL"  # type: ignore
    )
    PYGEOAPI_BASEURL: Optional[str] = pydantic.Field(
        None, env="DEV_PYGEOAPI_BASEURL"  # type: ignore
    )
    PYGEOAPI_CONFIG: Optional[str] = pydantic.Field(
        None, env="DEV_PYGEOAPI_CONFIG"  # type: ignore
    )
    PYGEOAPI_OPENAPI: Optional[str] = pydantic.Field(
        None, env="DEV_PYGEOAPI_OPENAPI"  # type: ignore
    )
    PYGEOAPI_SECURITY_SCHEME: Optional[str] = pydantic.Field(
        None, env="DEV_PYGEOAPI_SECURITY_SCHEME"  # type: ignore
    )
    FASTGEOAPI_CONTEXT: Optional[str] = pydantic.Field(
        None, env="DEV_FASTGEOAPI_CONTEXT"  # type: ignore
    )
    FASTGEOAPI_REVERSE_PROXY: Optional[bool] = pydantic.Field(
        None, env="DEV_FASTGEOAPI_REVERSE_PROXY"  # type: ignore
    )

    model_config = SettingsConfigDict(env_prefix="DEV_")


class ProdConfig(GlobalConfig):
    """Production configurations."""

    ROOT_PATH: Optional[str] = pydantic.Field(
        None, env="PROD_ROOT_PATH"  # type: ignore
    )
    AWS_LAMBDA_DEPLOY: Optional[bool] = pydantic.Field(
        None, env="PROD_AWS_LAMBDA_DEPLOY"  # type: ignore
    )
    LOG_PATH: Optional[str] = pydantic.Field(None, env="PROD_LOG_PATH")  # type: ignore
    LOG_FILENAME: Optional[str] = pydantic.Field(
        None, env="PROD_LOG_FILENAME"  # type: ignore
    )
    LOG_LEVEL: Optional[str] = pydantic.Field(
        None, env="PROD_LOG_LEVEL"  # type: ignore
    )
    LOG_ENQUEUE: Optional[bool] = pydantic.Field(
        None, env="PROD_LOG_ENQUEUE"  # type: ignore
    )
    LOG_ROTATION: Optional[str] = pydantic.Field(
        None, env="PROD_LOG_ROTATION"  # type: ignore
    )
    LOG_RETENTION: Optional[str] = pydantic.Field(
        None, env="PROD_LOG_RETENTION"  # type: ignore
    )
    LOG_FORMAT: Optional[str] = pydantic.Field(
        None, env="PROD_LOG_FORMAT"  # type: ignore
    )
    OPA_ENABLED: Optional[bool] = pydantic.Field(
        None, env="PROD_OPA_ENABLED"  # type: ignore
    )
    OPA_URL: Optional[str] = pydantic.Field(None, env="PROD_OPA_URL")  # type: ignore
    APP_URI: Optional[str] = pydantic.Field(None, env="PROD_APP_URI")  # type: ignore
    OIDC_WELL_KNOWN_ENDPOINT: Optional[str] = pydantic.Field(
        None, env="PROD_OIDC_WELL_KNOWN_ENDPOINT"  # type: ignore
    )
    OIDC_CLIENT_ID: Optional[str] = pydantic.Field(
        None, env="PROD_OIDC_CLIENT_ID"  # type: ignore
    )
    OIDC_CLIENT_SECRET: Optional[str] = pydantic.Field(
        None, env="PROD_OIDC_CLIENT_SECRET"  # type: ignore
    )
    API_KEY_ENABLED: Optional[bool] = pydantic.Field(
        None, env="PROD_API_KEY_ENABLED"  # type: ignore
    )
    JWKS_ENABLED: Optional[bool] = pydantic.Field(
        None, env="PROD_JWKS_ENABLED"  # type: ignore
    )
    OAUTH2_JWKS_ENDPOINT: Optional[str] = pydantic.Field(
        None, env="PROD_OAUTH2_JWKS_ENDPOINT"  # type: ignore
    )
    OAUTH2_TOKEN_ENDPOINT: Optional[str] = pydantic.Field(
        None, env="PROD_OAUTH2_TOKEN_ENDPOINT"  # type: ignore
    )
    PYGEOAPI_KEY_GLOBAL: Optional[str] = pydantic.Field(
        None, env="PROD_PYGEOAPI_KEY_GLOBAL"  # type: ignore
    )
    PYGEOAPI_BASEURL: Optional[str] = pydantic.Field(
        None, env="PROD_PYGEOAPI_BASEURL"  # type: ignore
    )
    PYGEOAPI_CONFIG: Optional[str] = pydantic.Field(
        None, env="PROD_PYGEOAPI_CONFIG"  # type: ignore
    )
    PYGEOAPI_OPENAPI: Optional[str] = pydantic.Field(
        None, env="PROD_PYGEOAPI_OPENAPI"  # type: ignore
    )
    PYGEOAPI_SECURITY_SCHEME: Optional[str] = pydantic.Field(
        None, env="PROD_PYGEOAPI_SECURITY_SCHEME"  # type: ignore
    )
    FASTGEOAPI_CONTEXT: Optional[str] = pydantic.Field(
        None, env="PROD_FASTGEOAPI_CONTEXT"  # type: ignore
    )
    FASTGEOAPI_REVERSE_PROXY: Optional[bool] = pydantic.Field(
        None, env="PROD_FASTGEOAPI_REVERSE_PROXY"  # type: ignore
    )

    model_config = SettingsConfigDict(env_prefix="PROD_")


class FactoryConfig:
    """Returns a config instance depending on the ENV_STATE variable."""

    def __init__(self, env_state: Optional[str]):
        """Initialize factory configuration."""
        self.env_state = env_state

    @lru_cache()
    def __call__(self):
        """Handle runtime configuration."""
        if self.env_state == "dev":
            return DevConfig(**GlobalConfig().model_dump())

        elif self.env_state == "prod":
            return ProdConfig(**GlobalConfig().model_dump())


configuration = FactoryConfig(env_state=GlobalConfig().ENV_STATE)()
