"""
pytest configuration — sets minimal environment variables so config.py
can be imported during unit tests without real credentials.
All tests that need specific config values should patch config directly.
"""
import os
import pytest


def pytest_configure(config):
    """Inject dummy credentials before any test module is imported."""
    os.environ.setdefault("GLINT_EMAIL", "test@example.com")
    os.environ.setdefault("GLINT_PASSWORD", "test_password_placeholder")
