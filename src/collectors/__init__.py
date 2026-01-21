"""Data collectors for various sources."""

from .github import GitHubCollector
from .hackernews import HackerNewsCollector

__all__ = ["GitHubCollector", "HackerNewsCollector"]
