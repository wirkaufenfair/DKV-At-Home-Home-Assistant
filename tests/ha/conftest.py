"""Fixtures for the Home Assistant level tests."""

import pytest


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/dkv_at_home."""
    return
