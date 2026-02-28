class MFSQuotaExceededError(OSError):
    """Raised when the quota limit is exceeded. Subclass of OSError."""
    def __init__(self, requested: int, available: int) -> None:
        self.requested = requested
        self.available = available
        super().__init__(
            f"MFS quota exceeded: requested {requested} bytes, "
            f"only {available} bytes available."
        )


class MFSNodeLimitExceededError(MFSQuotaExceededError):
    """Raised when the node count limit is exceeded. Subclass of MFSQuotaExceededError."""
    def __init__(self, current: int, limit: int) -> None:
        self.current = current
        self.limit = limit
        super().__init__(requested=current + 1, available=limit - current)
        self.args = (
            f"MFS node limit exceeded: current {current} nodes, limit is {limit}.",
        )
