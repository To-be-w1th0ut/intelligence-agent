"""Hacker News collector."""

from dataclasses import dataclass
from typing import Optional

import httpx

from ..config import HackerNewsConfig


@dataclass
class HNStory:
    """Represents a Hacker News story."""
    id: int
    title: str
    url: Optional[str]
    score: int
    author: str
    comments: int
    hn_url: str  # Hacker News discussion URL


class HackerNewsCollector:
    """Collects top stories from Hacker News using official API."""
    
    API_BASE = "https://hacker-news.firebaseio.com/v0"
    HN_ITEM_URL = "https://news.ycombinator.com/item?id={}"
    
    STORY_ENDPOINTS = {
        "top": "topstories",
        "new": "newstories", 
        "best": "beststories",
        "show": "showstories",
        "ask": "askstories",
    }
    
    def __init__(self, config: HackerNewsConfig):
        self.config = config
        self.client = httpx.Client(timeout=30.0)
    
    def collect(self) -> list[HNStory]:
        """Collect stories based on configuration."""
        if not self.config.enabled:
            return []
        
        story_type = self.config.story_type
        endpoint = self.STORY_ENDPOINTS.get(story_type, "topstories")
        
        try:
            # Get story IDs
            response = self.client.get(f"{self.API_BASE}/{endpoint}.json")
            response.raise_for_status()
            story_ids = response.json()[:self.config.limit]
            
            # Fetch each story
            stories = []
            for story_id in story_ids:
                story = self._fetch_story(story_id)
                if story:
                    stories.append(story)
            
            return stories
            
        except httpx.HTTPError as e:
            print(f"Error fetching Hacker News: {e}")
            return []
    
    def _fetch_story(self, story_id: int) -> Optional[HNStory]:
        """Fetch a single story by ID."""
        try:
            response = self.client.get(f"{self.API_BASE}/item/{story_id}.json")
            response.raise_for_status()
            data = response.json()
            
            if not data or data.get("type") != "story":
                return None
            
            return HNStory(
                id=data["id"],
                title=data.get("title", ""),
                url=data.get("url"),  # May be None for Ask HN
                score=data.get("score", 0),
                author=data.get("by", "unknown"),
                comments=data.get("descendants", 0),
                hn_url=self.HN_ITEM_URL.format(data["id"]),
            )
            
        except (httpx.HTTPError, KeyError) as e:
            print(f"Error fetching story {story_id}: {e}")
            return None
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
