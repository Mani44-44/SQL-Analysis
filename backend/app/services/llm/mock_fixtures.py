"""Default handlers for the mock provider used in local dev without an API key.

Later phases register task handlers here (SQL generation fixtures, explanations, ...).
"""

from __future__ import annotations

from app.services.llm.mock import MockProvider


def build_default_mock() -> MockProvider:
    return MockProvider()
