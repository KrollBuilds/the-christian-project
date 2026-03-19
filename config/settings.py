"""Runtime settings for The Christian Project."""

from __future__ import annotations

import os
from dataclasses import dataclass


# OpenAI generation defaults
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "1024"))
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.7"))


@dataclass
class _Settings:
    rate_limit_per_min: int = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))


settings = _Settings()
