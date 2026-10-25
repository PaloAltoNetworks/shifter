"""Privacy boundary for standalone model processes' transport diagnostics."""

import logging

_TRANSPORT_LOGGERS = ("httpx", "httpcore", "botocore", "boto3", "google.auth", "urllib3", "requests")


def isolate_transport_diagnostics() -> None:
    """Drop SDK wire diagnostics, including when a deployment enables DEBUG.

    Provider headers, signing inputs and SDK exception arguments are not safe
    telemetry. A field-name scrubber cannot identify arbitrary prompt or answer
    content. The standalone listeners expose only their fixed error codes;
    these dependency loggers must neither handle nor propagate wire records.
    Future child loggers inherit the non-propagating namespace boundary.
    """
    names = set(_TRANSPORT_LOGGERS)
    names.update(
        name
        for name in logging.root.manager.loggerDict
        if any(name.startswith(root + ".") for root in _TRANSPORT_LOGGERS)
    )
    for name in names:
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
