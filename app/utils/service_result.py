"""Service result module."""
import inspect

from app.config.logging import create_logger
from app.utils.app_exceptions import AppExceptionError


logger = create_logger("app.utils.service_result")


class ServiceResult:
    """Service result class."""

    def __init__(self, arg):
        """Initialize the service result class."""
        if isinstance(arg, AppExceptionError):
            self.success = False
            self.exception_case = arg.exception_case
            self.status_code = arg.status_code
        else:
            self.success = True
            self.exception_case = None
            self.status_code = None
        self.value = arg

    def __str__(self):
        """Handle class identity."""
        if self.success:
            return "[Success]"
        return f'[Exception] "{self.exception_case}"'

    def __repr__(self):
        """Handle class representation."""
        if self.success:
            return "<ServiceResult Success>"
        return f"<ServiceResult AppException {self.exception_case}>"

    def __enter__(self):
        """Handle runtime instantiation."""
        return self.value

    def __exit__(self, *kwargs):
        """Handle runtime exit."""
        pass


def caller_info() -> str:
    """Handle information for the caller."""
    info = inspect.getframeinfo(inspect.stack()[2][0])
    return f"{info.filename}:{info.function}:{info.lineno}"


def handle_result(result: ServiceResult):
    """Handle result of a service."""
    if not result.success:
        with result as exception:
            logger.error(f"{exception} | caller={caller_info()}")
            raise exception
    with result as result:
        return result
