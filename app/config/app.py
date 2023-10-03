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

    ENV_STATE: Optional[str] = pydantic.Field(None, env="ENV_STATE")
    HOST: Optional[str] = pydantic.Field(None, env="HOST")
    PORT: Optional[str] = pydantic.Field(None, env="PORT")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
        env_prefix="",
        env_nested_delimiter="_",
    )


class DevConfig(GlobalConfig):
    """Development configurations."""

    ROOT_PATH: Optional[str] = pydantic.Field(None, env="DEV_ROOT_PATH")
    AWS_LAMBDA_DEPLOY: Optional[bool] = pydantic.Field(
        None, env="DEV_AWS_LAMBDA_DEPLOY"
    )
    LOG_PATH: Optional[str] = pydantic.Field(None, env="DEV_LOG_PATH")
    LOG_FILENAME: Optional[str] = pydantic.Field(None, env="DEV_LOG_FILENAME")
    LOG_LEVEL: Optional[str] = pydantic.Field(None, env="DEV_LOG_LEVEL")
    LOG_ENQUEUE: Optional[bool] = pydantic.Field(None, env="DEV_LOG_ENQUEUE")
    LOG_ROTATION: Optional[str] = pydantic.Field(None, env="DEV_LOG_ROTATION")
    LOG_RETENTION: Optional[str] = pydantic.Field(None, env="DEV_LOG_RETENTION")
    LOG_FORMAT: Optional[str] = pydantic.Field(None, env="DEV_LOG_FORMAT")
    OPA_ENABLED: Optional[bool] = pydantic.Field(None, env="DEV_OPA_ENABLED")
    OPA_URL: Optional[str] = pydantic.Field(None, env="DEV_OPA_URL")
    APP_URI: Optional[str] = pydantic.Field(None, env="DEV_APP_URI")
    OIDC_WELL_KNOWN_ENDPOINT: Optional[str] = pydantic.Field(
        None, env="DEV_OIDC_WELL_KNOWN_ENDPOINT"
    )
    OIDC_CLIENT_ID: Optional[str] = pydantic.Field(None, env="DEV_OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET: Optional[str] = pydantic.Field(
        None, env="DEV_OIDC_CLIENT_SECRET"
    )
    API_KEY_ENABLED: Optional[bool] = pydantic.Field(None, env="DEV_API_KEY_ENABLED")
    PYGEOAPI_KEY_GLOBAL: Optional[str] = pydantic.Field(
        None, env="DEV_PYGEOAPI_KEY_GLOBAL"
    )
    PYGEOAPI_BASEURL: Optional[str] = pydantic.Field(None, env="DEV_PYGEOAPI_BASEURL")
    PYGEOAPI_CONFIG: Optional[str] = pydantic.Field(None, env="DEV_PYGEOAPI_CONFIG")
    PYGEOAPI_OPENAPI: Optional[str] = pydantic.Field(None, env="DEV_PYGEOAPI_OPENAPI")
    FASTGEOAPI_CONTEXT: Optional[str] = pydantic.Field(
        None, env="DEV_FASTGEOAPI_CONTEXT"
    )

    model_config = SettingsConfigDict(env_prefix="DEV_")


class ProdConfig(GlobalConfig):
    """Production configurations."""

    ROOT_PATH: Optional[str] = pydantic.Field(None, env="PROD_ROOT_PATH")
    AWS_LAMBDA_DEPLOY: Optional[bool] = pydantic.Field(
        None, env="PROD_AWS_LAMBDA_DEPLOY"
    )
    LOG_PATH: Optional[str] = pydantic.Field(None, env="PROD_LOG_PATH")
    LOG_FILENAME: Optional[str] = pydantic.Field(None, env="PROD_LOG_FILENAME")
    LOG_LEVEL: Optional[str] = pydantic.Field(None, env="PROD_LOG_LEVEL")
    LOG_ENQUEUE: Optional[bool] = pydantic.Field(None, env="PROD_LOG_ENQUEUE")
    LOG_ROTATION: Optional[str] = pydantic.Field(None, env="PROD_LOG_ROTATION")
    LOG_RETENTION: Optional[str] = pydantic.Field(None, env="PROD_LOG_RETENTION")
    LOG_FORMAT: Optional[str] = pydantic.Field(None, env="PROD_LOG_FORMAT")
    OPA_ENABLED: Optional[bool] = pydantic.Field(None, env="PROD_OPA_ENABLED")
    OPA_URL: Optional[str] = pydantic.Field(None, env="PROD_OPA_URL")
    APP_URI: Optional[str] = pydantic.Field(None, env="PROD_APP_URI")
    OIDC_WELL_KNOWN_ENDPOINT: Optional[str] = pydantic.Field(
        None, env="PROD_OIDC_WELL_KNOWN_ENDPOINT"
    )
    OIDC_CLIENT_ID: Optional[str] = pydantic.Field(None, env="PROD_OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET: Optional[str] = pydantic.Field(
        None, env="PROD_OIDC_CLIENT_SECRET"
    )
    API_KEY_ENABLED: Optional[bool] = pydantic.Field(None, env="PROD_API_KEY_ENABLED")
    PYGEOAPI_KEY_GLOBAL: Optional[str] = pydantic.Field(
        None, env="PROD_PYGEOAPI_KEY_GLOBAL"
    )
    PYGEOAPI_BASEURL: Optional[str] = pydantic.Field(None, env="PROD_PYGEOAPI_BASEURL")
    PYGEOAPI_CONFIG: Optional[str] = pydantic.Field(None, env="PROD_PYGEOAPI_CONFIG")
    PYGEOAPI_OPENAPI: Optional[str] = pydantic.Field(None, env="PROD_PYGEOAPI_OPENAPI")
    FASTGEOAPI_CONTEXT: Optional[str] = pydantic.Field(
        None, env="PROD_FASTGEOAPI_CONTEXT"
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
