"""Pytest configuration and fixtures."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from src.norms import store as norms_store
from tests.show.builders import pr_node
from tests.show.fake_github import FakeGitHub


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


@pytest.fixture(autouse=True)
def diff_timelines(monkeypatch) -> Generator[FakeGitHub, None, None]:
    """The GitHub endpoint `pr list --diff --format json` reads timelines from.

    It serves an empty PR by default; a test sets `.item` for a richer one and reads
    `.requests` to see what was fetched.
    """
    fake = FakeGitHub("pullRequest", pr_node([]))
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_USERNAME", "alice")
    monkeypatch.setattr("src.show.delta.GitHubClient", lambda *_: fake.client())
    yield fake
