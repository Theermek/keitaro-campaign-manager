from typing import Any


class AppError(Exception):
    """Expected error returned to the client as {"error": message, ...extra}."""

    def __init__(self, status_code: int, message: str, **extra: Any):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.extra = extra
