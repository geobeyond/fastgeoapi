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
