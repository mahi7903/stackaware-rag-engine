import logging
from typing import Any, Optional


# Intent: keep one shared logger name for API guard / admin / expensive route events.
logger = logging.getLogger("stackaware.api")


def log_info(event: str, **details: Any) -> None:
    """
    Small shared helper so I can log route events in one consistent shape
    without repeating print/log formatting in every router.
    """
    logger.info("%s | %s", event, details)


def log_warning(event: str, **details: Any) -> None:
    """
    warning level for recoverable issues like missing files, bad requests,
    or user-triggered states that are unexpected but not server crashes.
    """
    logger.warning("%s | %s", event, details)


def log_error(event: str, error: Optional[Exception] = None, **details: Any) -> None:
    """
    error level for failures in expensive flows like upload, reindex,
    or RAG generation so debugging is easier later.
    """
    if error is not None:
        details["error_type"] = type(error).__name__
        details["error_message"] = str(error)

    logger.error("%s | %s", event, details)



import time
from collections import defaultdict


# I am keeping a simple in-memory rate tracker per user to avoid abuse on expensive endpoints like RAG.
_rate_limit_store = defaultdict(list)


def check_rag_rate_limit(user_id: int, max_requests: int = 5, window_seconds: int = 60):
    """
    I am limiting how many RAG requests a user can make in a time window
    so the system doesn't get abused or rack up API costs.
    """
    now = time.time()

    # I am removing old requests outside the time window
    _rate_limit_store[user_id] = [
        t for t in _rate_limit_store[user_id]
        if now - t < window_seconds
    ]

    if len(_rate_limit_store[user_id]) >= max_requests:
        raise Exception("Rate limit exceeded. Please wait before making more requests.")

    _rate_limit_store[user_id].append(now)