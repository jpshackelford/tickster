"""Pytest configuration and fixtures."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from src.norms import store as norms_store


@pytest.fixture
def temp_workspace() -> Generator[Path, None, None]:
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def no_norms_fetch() -> Generator[None, None, None]:
    """Keep tests off the network: no repo has a norms file unless a test installs one."""
    norms_store.set_loader(lambda _repo: None)
    yield
    norms_store.set_loader(None)
