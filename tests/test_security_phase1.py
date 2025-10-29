"""Security Phase 1 regression tests."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable

import pytest
from flask import Flask
from pydantic import ValidationError

# Ensure project root is importable when tests run from repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _reload(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def _with_env(monkeypatch, env: dict, func: Callable):
    for key in ("OPENAI_API_KEY", "RATE_LIMIT_PER_MIN"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return func()


def test_settings_requires_api_key(monkeypatch):
    def _import():
        with pytest.raises(ValidationError):
            _reload("config.settings")

    _with_env(monkeypatch, {"RATE_LIMIT_PER_MIN": "10"}, _import)


def test_settings_reads_from_environment(monkeypatch):
    def _assert_loaded():
        settings_module = _reload("config.settings")
        settings = settings_module.get_settings()
        assert settings.openai_api_key == "sk-live-test"
        assert settings.rate_limit_per_min == 25

    _with_env(
        monkeypatch,
        {"OPENAI_API_KEY": "sk-live-test", "RATE_LIMIT_PER_MIN": "25"},
        _assert_loaded,
    )


def test_rate_limit_enforces_throttle(monkeypatch):
    def _exercise():
        settings_module = _reload("config.settings")
        rate_limit_module = _reload("app.middleware.rate_limit")

        app = Flask(__name__)
        app.config["TESTING"] = True

        limiter = rate_limit_module.init_rate_limit(app)

        @app.route("/ping")
        @limiter.limit("2 per minute")
        def ping():
            return {"status": "ok"}

        client = app.test_client()
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 200
        third_response = client.get("/ping")
        assert third_response.status_code == 429
        payload = third_response.get_json()
        assert payload
        assert "Too many requests" in payload["message"]

    _with_env(
        monkeypatch,
        {"OPENAI_API_KEY": "sk-live-test", "RATE_LIMIT_PER_MIN": "2"},
        _exercise,
    )


def test_redact_pii_replaces_sensitive_entities():
    from app.utils.privacy_utils import redact_pii

    text = "My name is John Doe. Email me at john.doe@example.com or call +1 555 123 4567."
    sanitized, detected = redact_pii(text)

    assert "[PERSON]" in sanitized or "[EMAIL]" in sanitized
    labels = {label for label, _ in detected}
    assert {"PERSON", "EMAIL", "PHONE_NUMBER"} & labels
    for _, entity_text in detected:
        assert entity_text not in sanitized


def test_redact_pii_handles_clean_text():
    from app.utils.privacy_utils import redact_pii

    text = "The sermon focuses on hope and grace."
    sanitized, detected = redact_pii(text)

    assert sanitized == text
    assert detected == []
