import logging

import structlog


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """JSON logs to stdout. Never log secrets, tokens, or raw PII."""
    logging.basicConfig(format="%(message)s", level=level)
    # The Azure SDKs log every HTTP request and response header at INFO; keep only their warnings.
    for noisy in ("azure", "azure.core.pipeline.policies.http_logging_policy", "uamqp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
    )
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
