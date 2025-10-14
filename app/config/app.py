"""App configuration module."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class GlobalConfig(BaseSettings):
    """Global configurations."""

    # This variable will be loaded from the .env file. However, if there is a
    # shell environment variable having the same name, that will take precedence.

    ENV_STATE: Optional[str] = None
    HOST: Optional[str] = None
    PORT: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
        env_prefix="",
        env_nested_delimiter="_",
        env_file_encoding="utf-8",
    )


class DevConfig(GlobalConfig):
    """Development configurations."""

    ROOT_PATH: Optional[str] = None
    AWS_LAMBDA_DEPLOY: Optional[bool] = None
    LOG_PATH: Optional[str] = None
    LOG_FILENAME: Optional[str] = None
    LOG_LEVEL: Optional[str] = None
    LOG_ENQUEUE: Optional[bool] = None
    LOG_ROTATION: Optional[str] = None
    LOG_RETENTION: Optional[str] = None
    LOG_FORMAT: Optional[str] = None
    OPA_ENABLED: Optional[bool] = None
    OPA_URL: Optional[str] = None
    APP_URI: Optional[str] = None
    OIDC_WELL_KNOWN_ENDPOINT: Optional[str] = None
    OIDC_CLIENT_ID: Optional[str] = None
    OIDC_CLIENT_SECRET: Optional[str] = None
    API_KEY_ENABLED: Optional[bool] = None
    JWKS_ENABLED: Optional[bool] = None
    OAUTH2_JWKS_ENDPOINT: Optional[str] = None
    OAUTH2_TOKEN_ENDPOINT: Optional[str] = None
    PYGEOAPI_KEY_GLOBAL: Optional[str] = None
    PYGEOAPI_BASEURL: Optional[str] = None
    PYGEOAPI_CONFIG: Optional[str] = None
    PYGEOAPI_OPENAPI: Optional[str] = None
    PYGEOAPI_SECURITY_SCHEME: Optional[str] = None
    FASTGEOAPI_CONTEXT: Optional[str] = None
    FASTGEOAPI_REVERSE_PROXY: Optional[bool] = None

    model_config = SettingsConfigDict(
        env_prefix="DEV_",
        env_file=".env",
        env_file_encoding="utf-8",
    )


class ProdConfig(GlobalConfig):
    """Production configurations."""

    ROOT_PATH: Optional[str] = None
    AWS_LAMBDA_DEPLOY: Optional[bool] = None
    LOG_PATH: Optional[str] = None
    LOG_FILENAME: Optional[str] = None
    LOG_LEVEL: Optional[str] = None
    LOG_ENQUEUE: Optional[bool] = None
    LOG_ROTATION: Optional[str] = None
    LOG_RETENTION: Optional[str] = None
    LOG_FORMAT: Optional[str] = None
    OPA_ENABLED: Optional[bool] = None
    OPA_URL: Optional[str] = None
    APP_URI: Optional[str] = None
    OIDC_WELL_KNOWN_ENDPOINT: Optional[str] = None
    OIDC_CLIENT_ID: Optional[str] = None
    OIDC_CLIENT_SECRET: Optional[str] = None
    API_KEY_ENABLED: Optional[bool] = None
    JWKS_ENABLED: Optional[bool] = None
    OAUTH2_JWKS_ENDPOINT: Optional[str] = None
    OAUTH2_TOKEN_ENDPOINT: Optional[str] = None
    PYGEOAPI_KEY_GLOBAL: Optional[str] = None
    PYGEOAPI_BASEURL: Optional[str] = None
    PYGEOAPI_CONFIG: Optional[str] = None
    PYGEOAPI_OPENAPI: Optional[str] = None
    PYGEOAPI_SECURITY_SCHEME: Optional[str] = None
    FASTGEOAPI_CONTEXT: Optional[str] = None
    FASTGEOAPI_REVERSE_PROXY: Optional[bool] = None

    model_config = SettingsConfigDict(
        env_prefix="PROD_",
        env_file=".env",
        env_file_encoding="utf-8",
    )


class FactoryConfig:
    """Returns a config instance depending on the ENV_STATE variable."""

    def __init__(self, env_state: Optional[str]):
        """Initialize factory configuration."""
        self.env_state = env_state

    def __call__(self):
        """Handle runtime configuration."""
        return self.get_config(self.env_state)

    @classmethod
    @lru_cache()
    def get_config(cls, env_state: str):
        """Get configuration based on environment state with caching."""
        if env_state == "dev":
            return DevConfig()

        elif env_state == "prod":
            return ProdConfig()


configuration = FactoryConfig(env_state=GlobalConfig().ENV_STATE)()
