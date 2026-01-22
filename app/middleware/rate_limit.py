"""Per-user rate limiting middleware using an in-memory token bucket."""

from __future__ import annotations

import time
from functools import wraps
from collections import defaultdict, deque
from typing import Callable, Deque, Dict, Tuple

from flask import Flask, jsonify, request

from config.settings import settings

Limit = Tuple[int, float]  # (max_requests, window_seconds)


def _parse_limit(limit_expression: str) -> Limit:
    """
    Convert a textual limit like ``"10 per minute"`` into a tuple.

    Supported units: second(s), minute(s).
    """
    parts = limit_expression.lower().split()
    if len(parts) != 3 or parts[1] != "per":
        raise ValueError(f"Unsupported rate limit expression: {limit_expression!r}")

    count = int(parts[0])
    unit = parts[2]

    if unit.startswith("sec"):
        window = 1.0
    elif unit.startswith("min"):
        window = 60.0
    else:
        raise ValueError(f"Unsupported rate limit unit: {unit}")

    return count, window


class RateLimiter:
    """Simple in-memory rate limiter keyed by request source."""

    def __init__(self, key_func: Callable[[], str], default_expression: str):
        self.key_func = key_func
        self.default_limit = _parse_limit(default_expression)
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def init_app(self, _: Flask) -> RateLimiter:
        """No-op for compatibility with Flask integration patterns."""
        return self

    def limit(self, expression: str | None = None):
        limit = _parse_limit(expression) if expression else self.default_limit

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                key = f"{self.key_func()}:{request.endpoint}"
                if not self._allow_request(key, limit):
                    return self._ratelimited_response()
                return func(*args, **kwargs)
            return wrapper

        return decorator

    def _allow_request(self, key: str, limit: Limit) -> bool:
        max_requests, window = limit
        now = time.monotonic()
        bucket = self._buckets[key]

        while bucket and now - bucket[0] >= window:
            bucket.popleft()

        if len(bucket) >= max_requests:
            return False

        bucket.append(now)
        return True

    @staticmethod
    def _ratelimited_response():
        return (
            jsonify(
                {
                    "message": "Too many requests. Please slow down.",
                    "scripture": (
                        "Proverbs 25:28 – 'Like a city whose walls are broken through "
                        "is a person who lacks self-control.'"
                    ),
                }
            ),
            429,
        )


def _remote_address() -> str:
    return request.remote_addr or "anonymous"


def init_rate_limit(app: Flask) -> RateLimiter:
    """
    Attach in-memory rate limiting to a Flask app with a 429 response payload.
    """
    limiter = RateLimiter(
        key_func=_remote_address,
        default_expression=f"{settings.rate_limit_per_min} per minute",
    )
    return limiter.init_app(app)
