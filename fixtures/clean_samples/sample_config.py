class AppSettings:
    """Standard application settings."""
    MAX_RETRIES: int = 3
    TIMEOUT_SECONDS: int = 30
    ENABLE_METRICS: bool = True
    LOG_LEVEL: str = "INFO"
