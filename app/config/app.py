"""App configuration module."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GlobalConfig(BaseSettings):
    """Global configurations."""

    # This variable will be loaded from the .env file. However, if there is a
    # shell environment variable having the same name, that will take precedence.

    ENV_STATE: str | None = None
    HOST: str
    PORT: str

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

    # Override inherited fields to use unprefixed env vars
    HOST: str = Field(validation_alias="HOST")
    PORT: str = Field(validation_alias="PORT")

    ROOT_PATH: str | None = None
    AWS_LAMBDA_DEPLOY: bool | None = None
    # 12-factor defaults: a container must boot from environment
    # variables alone, with no .env on disk (create_logger builds
    # Path(LOG_PATH)/LOG_FILENAME at import time).
    LOG_PATH: str = "/tmp"  # noqa: S108
    LOG_FILENAME: str = "fastgeoapi.log"
    LOG_LEVEL: str = "info"
    LOG_ENQUEUE: bool = True
    LOG_ROTATION: str = "1 days"
    LOG_RETENTION: str = "1 months"
    LOG_FORMAT: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "[id:{extra[request_id]}] - <level>{message}</level>"
    )
    OPA_ENABLED: bool | None = None
    OPA_URL: str | None = None
    APP_URI: str | None = None
    OIDC_WELL_KNOWN_ENDPOINT: str | None = None
    OIDC_CLIENT_ID: str | None = None
    OIDC_CLIENT_SECRET: str | None = None
    API_KEY_ENABLED: bool | None = None
    JWKS_ENABLED: bool | None = None
    OAUTH2_JWKS_ENDPOINT: str | None = None
    OAUTH2_TOKEN_ENDPOINT: str | None = None
    OAUTH2_EXPECTED_AUDIENCE: str | None = None
    OAUTH2_EXPECTED_ISSUER: str | None = None
    PYGEOAPI_KEY_GLOBAL: str | None = None
    PYGEOAPI_BASEURL: str
    PYGEOAPI_CONFIG: str
    PYGEOAPI_OPENAPI: str
    PYGEOAPI_SECURITY_SCHEME: str | None = None
    FASTGEOAPI_CONTEXT: str
    FASTGEOAPI_REVERSE_PROXY: bool | None = None
    FASTGEOAPI_WITH_MCP: bool = False
    FASTGEOAPI_MCP_CONSENT_MODE: str | None = None
    FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED: bool = False
    FASTGEOAPI_CACHE_DIR: str | None = None
    FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS: int | None = None

    model_config = SettingsConfigDict(
        env_prefix="DEV_",
        env_file=".env",
        env_file_encoding="utf-8",
    )


class ProdConfig(GlobalConfig):
    """Production configurations."""

    # Override inherited fields to use unprefixed env vars
    HOST: str = Field(validation_alias="HOST")
    PORT: str = Field(validation_alias="PORT")

    ROOT_PATH: str | None = None
    AWS_LAMBDA_DEPLOY: bool | None = None
    # 12-factor defaults: a container must boot from environment
    # variables alone, with no .env on disk (create_logger builds
    # Path(LOG_PATH)/LOG_FILENAME at import time).
    LOG_PATH: str = "/tmp"  # noqa: S108
    LOG_FILENAME: str = "fastgeoapi.log"
    LOG_LEVEL: str = "info"
    LOG_ENQUEUE: bool = True
    LOG_ROTATION: str = "1 days"
    LOG_RETENTION: str = "1 months"
    LOG_FORMAT: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "[id:{extra[request_id]}] - <level>{message}</level>"
    )
    OPA_ENABLED: bool | None = None
    OPA_URL: str | None = None
    APP_URI: str | None = None
    OIDC_WELL_KNOWN_ENDPOINT: str | None = None
    OIDC_CLIENT_ID: str | None = None
    OIDC_CLIENT_SECRET: str | None = None
    API_KEY_ENABLED: bool | None = None
    JWKS_ENABLED: bool | None = None
    OAUTH2_JWKS_ENDPOINT: str | None = None
    OAUTH2_TOKEN_ENDPOINT: str | None = None
    OAUTH2_EXPECTED_AUDIENCE: str | None = None
    OAUTH2_EXPECTED_ISSUER: str | None = None
    PYGEOAPI_KEY_GLOBAL: str | None = None
    PYGEOAPI_BASEURL: str
    PYGEOAPI_CONFIG: str
    PYGEOAPI_OPENAPI: str
    PYGEOAPI_SECURITY_SCHEME: str | None = None
    FASTGEOAPI_CONTEXT: str
    FASTGEOAPI_REVERSE_PROXY: bool | None = None
    FASTGEOAPI_WITH_MCP: bool = False
    FASTGEOAPI_MCP_CONSENT_MODE: str | None = None
    FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED: bool = False
    FASTGEOAPI_CACHE_DIR: str | None = None
    FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS: int | None = None

    model_config = SettingsConfigDict(
        env_prefix="PROD_",
        env_file=".env",
        env_file_encoding="utf-8",
    )


class FactoryConfig:
    """Returns a config instance depending on the ENV_STATE variable."""

    def __init__(self, env_state: str | None):
        """Initialize factory configuration."""
        self.env_state = env_state

    def __call__(self):
        """Handle runtime configuration."""
        return self.get_config(self.env_state)

    @classmethod
    @lru_cache
    def get_config(cls, env_state: str):
        """Get configuration based on environment state with caching."""
        if env_state == "dev":
            return DevConfig()

        elif env_state == "prod":
            return ProdConfig()


configuration = FactoryConfig(env_state=GlobalConfig().ENV_STATE)()
