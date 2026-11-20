class KeitaroError(Exception):
    """Keitaro API call failed.

    Messages contain only the API path, never the base URL or the API key.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        path: str = "",
        timed_out: bool = False,
    ):
        super().__init__(message)
        self.message = message
        # None when Keitaro gave no HTTP response (timeout, network error)
        self.status_code = status_code
        self.path = path
        self.timed_out = timed_out


class ForbiddenCampaignError(Exception):
    """A mutating operation targets a campaign without the allowed prefix."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
