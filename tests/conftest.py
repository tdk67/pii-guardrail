"""Pytest configuration and test suite hooks."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom command-line options for integration testing."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests requiring downloaded Julia-1 model weights.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration and slow tests unless explicitly enabled via --run-integration."""
    if config.getoption("--run-integration"):
        return

    skip_integration = pytest.mark.skip(
        reason="Integration test skipped by default (requires local Julia-1 model weights). Pass --run-integration to run."
    )
    for item in items:
        if "integration" in item.keywords or "slow" in item.keywords:
            item.add_marker(skip_integration)
