from src.app.exceptions.base import BaseAppException


class UnauthorizedError(BaseAppException):
    """Raised when a request carries no valid API key."""

    status_code = 401
    error_code = "invalid_api_key"
    default_detail = "A valid X-API-Key header is required for this operation."
