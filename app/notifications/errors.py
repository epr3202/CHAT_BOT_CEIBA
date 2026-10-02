class OutboundSendError(RuntimeError):
    """Transport-independent failure understood by the notification queue."""

    def __init__(self, message: str, *, code: int | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
