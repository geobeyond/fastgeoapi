"""App exceptions module."""
from fastapi import Request
from starlette.responses import JSONResponse


class AppExceptionError(Exception):
    """Application exception base error class."""

    def __init__(self, status_code: int, error: str, context: dict):
        """Handle application exceptions initialization."""
        self.exception_case = self.__class__.__name__
        self.status_code = status_code
        self.error = error
        self.context = context

    def __str__(self):
        """Define representation of application exception instance."""
        return (
            f"<AppExceptionError {self.exception_case} - error={self.error}"
            + f"status_code={self.status_code} - context={self.context}>"
        )


async def app_exception_handler(request: Request, exc: AppExceptionError):
    """Handle json representation of application exception."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error,
            "context": exc.context,
        },
    )


class AppException:
    """Application exception class."""

    pass
