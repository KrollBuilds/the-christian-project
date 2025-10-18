"""Configuration loader for the Christian Project."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

_SETTINGS_PATH = Path(__file__).resolve().parent / "settings.yml"

with _SETTINGS_PATH.open("r", encoding="utf-8") as settings_file:
    SETTINGS: Dict[str, Any] = yaml.safe_load(settings_file) or {}

__all__ = ["SETTINGS"]
