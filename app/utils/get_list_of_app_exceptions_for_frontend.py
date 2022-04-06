"""App exceptions for frontend module."""
from app.config.logging import create_logger
from app.utils.app_exceptions import AppException


logger = create_logger(
    name="app.utils.get_list_of_app_exceptions_for_frontend",
)


logger.debug([e for e in dir(AppException) if "__" not in e])
