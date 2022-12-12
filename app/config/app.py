"""App configuration module."""
from typing import Optional

from pydantic import BaseSettings
from pydantic import Field


class GlobalConfig(BaseSettings):
    """Global configurations."""

    # This variable will be loaded from the .env file. However, if there is a
    # shell environment variable having the same name, that will take precedence.

    ENV_STATE: Optional[str] = Field(None, env="ENV_STATE")

    class Config:
        """Loads the dotenv file."""

        env_file: str = ".env"


class DevConfig(GlobalConfig):
    """Development configurations."""

    ROOT_PATH: Optional[str] = Field(None, env="DEV_ROOT_PATH")
    AWS_LAMBDA_DEPLOY: Optional[bool] = Field(None, env="DEV_AWS_LAMBDA_DEPLOY")
    LOG_PATH: Optional[str] = Field(None, env="DEV_LOG_PATH")
    LOG_FILENAME: Optional[str] = Field(None, env="DEV_LOG_FILENAME")
    LOG_LEVEL: Optional[str] = Field(None, env="DEV_LOG_LEVEL")
    LOG_ENQUEUE: Optional[bool] = Field(None, env="DEV_LOG_ENQUEUE")
    LOG_ROTATION: Optional[str] = Field(None, env="DEV_LOG_ROTATION")
    LOG_RETENTION: Optional[str] = Field(None, env="DEV_LOG_RETENTION")
    LOG_FORMAT: Optional[str] = Field(None, env="DEV_LOG_FORMAT")
    OPA_ENABLED: Optional[bool] = Field(None, env="DEV_OPA_ENABLED")
    OPA_URL: Optional[str] = Field(None, env="DEV_OPA_URL")
    APP_URI: Optional[str] = Field(None, env="DEV_APP_URI")
    OIDC_WELL_KNOWN_ENDPOINT: Optional[str] = Field(
        None, env="DEV_OIDC_WELL_KNOWN_ENDPOINT"
    )
    OIDC_CLIENT_ID: Optional[str] = Field(None, env="DEV_OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET: Optional[str] = Field(None, env="DEV_OIDC_CLIENT_SECRET")
    API_KEY_ENABLED: Optional[bool] = Field(None, env="DEV_API_KEY_ENABLED")
    PYGEOAPI_KEY_GLOBAL: Optional[str] = Field(None, env="DEV_PYGEOAPI_KEY_GLOBAL")
    PYGEOAPI_CONFIG: Optional[str] = Field(None, env="DEV_PYGEOAPI_CONFIG")
    PYGEOAPI_OPENAPI: Optional[str] = Field(None, env="DEV_PYGEOAPI_OPENAPI")


class ProdConfig(GlobalConfig):
    """Production configurations."""

    ROOT_PATH: Optional[str] = Field(None, env="PROD_ROOT_PATH")
    AWS_LAMBDA_DEPLOY: Optional[bool] = Field(None, env="PROD_AWS_LAMBDA_DEPLOY")
    LOG_PATH: Optional[str] = Field(None, env="PROD_LOG_PATH")
    LOG_FILENAME: Optional[str] = Field(None, env="PROD_LOG_FILENAME")
    LOG_LEVEL: Optional[str] = Field(None, env="PROD_LOG_LEVEL")
    LOG_ENQUEUE: Optional[bool] = Field(None, env="PROD_LOG_ENQUEUE")
    LOG_ROTATION: Optional[str] = Field(None, env="PROD_LOG_ROTATION")
    LOG_RETENTION: Optional[str] = Field(None, env="PROD_LOG_RETENTION")
    LOG_FORMAT: Optional[str] = Field(None, env="PROD_LOG_FORMAT")
    OPA_ENABLED: Optional[bool] = Field(None, env="PROD_OPA_ENABLED")
    OPA_URL: Optional[str] = Field(None, env="PROD_OPA_URL")
    APP_URI: Optional[str] = Field(None, env="PROD_APP_URI")
    OIDC_WELL_KNOWN_ENDPOINT: Optional[str] = Field(
        None, env="PROD_OIDC_WELL_KNOWN_ENDPOINT"
    )
    OIDC_CLIENT_ID: Optional[str] = Field(None, env="PROD_OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET: Optional[str] = Field(None, env="PROD_OIDC_CLIENT_SECRET")
    API_KEY_ENABLED: Optional[bool] = Field(None, env="PROD_API_KEY_ENABLED")
    PYGEOAPI_KEY_GLOBAL: Optional[str] = Field(None, env="PROD_PYGEOAPI_KEY_GLOBAL")
    PYGEOAPI_CONFIG: Optional[str] = Field(None, env="PROD_PYGEOAPI_CONFIG")
    PYGEOAPI_OPENAPI: Optional[str] = Field(None, env="PROD_PYGEOAPI_OPENAPI")


class FactoryConfig:
    """Returns a config instance dependending on the ENV_STATE variable."""

    def __init__(self, env_state: Optional[str]):
        """Initialize factory configuration."""
        self.env_state = env_state

    def __call__(self):
        """Handle runtime configuration."""
        if self.env_state == "dev":
            return DevConfig()

        elif self.env_state == "prod":
            return ProdConfig()


configuration = FactoryConfig(GlobalConfig().ENV_STATE)()
