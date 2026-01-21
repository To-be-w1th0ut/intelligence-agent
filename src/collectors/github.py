"""GitHub Trending collector."""

from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from ..config import GitHubConfig


@dataclass
class GitHubProject:
    """Represents a GitHub trending project."""
    name: str  # owner/repo
    url: str
    description: Optional[str]
    language: Optional[str]
    stars: int
    stars_today: int
    forks: int
    

class GitHubCollector:
    """Collects trending projects from GitHub."""
    
    BASE_URL = "https://github.com/trending"
    
    def __init__(self, config: GitHubConfig):
        self.config = config
        self.client = httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
        )
    
    def collect(self) -> list[GitHubProject]:
        """Collect trending projects based on configuration."""
        if not self.config.enabled:
            return []
        
        all_projects = []
        
        # Collect for each configured language
        languages = self.config.languages or [None]  # None means all languages
        
        for language in languages:
            projects = self._fetch_trending(language, self.config.since)
            all_projects.extend(projects)
        
        # Deduplicate by project name
        seen = set()
        unique_projects = []
        for project in all_projects:
            if project.name not in seen:
                seen.add(project.name)
                unique_projects.append(project)
        
        # Apply keyword filtering if configured
        if self.config.keywords:
            unique_projects = self._filter_by_keywords(unique_projects)
        
        # Sort by stars today and limit
        unique_projects.sort(key=lambda p: p.stars_today, reverse=True)
        return unique_projects[:self.config.limit]
    
    def _filter_by_keywords(self, projects: list[GitHubProject]) -> list[GitHubProject]:
        """Filter projects by keywords in name or description."""
        keywords = [kw.lower() for kw in self.config.keywords]
        filtered = []
        
        for project in projects:
            text = f"{project.name} {project.description or ''}".lower()
            if any(kw in text for kw in keywords):
                filtered.append(project)
        
        return filtered
    
    def _fetch_trending(
        self, 
        language: Optional[str] = None, 
        since: str = "daily"
    ) -> list[GitHubProject]:
        """Fetch trending page for a specific language."""
        url = self.BASE_URL
        if language:
            url = f"{url}/{language}"
        
        params = {"since": since}
        
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return self._parse_trending_page(response.text)
        except httpx.HTTPError as e:
            print(f"Error fetching GitHub trending: {e}")
            return []
    
    def _parse_trending_page(self, html: str) -> list[GitHubProject]:
        """Parse the trending page HTML."""
        soup = BeautifulSoup(html, "lxml")
        projects = []
        
        for article in soup.select("article.Box-row"):
            try:
                project = self._parse_project(article)
                if project:
                    projects.append(project)
            except Exception as e:
                print(f"Error parsing project: {e}")
                continue
        
        return projects
    
    def _parse_project(self, article) -> Optional[GitHubProject]:
        """Parse a single project from the article element."""
        # Project name (owner/repo)
        name_elem = article.select_one("h2 a")
        if not name_elem:
            return None
        
        name = name_elem.get("href", "").strip("/")
        if not name:
            return None
        
        url = f"https://github.com/{name}"
        
        # Description
        desc_elem = article.select_one("p")
        description = desc_elem.get_text(strip=True) if desc_elem else None
        
        # Language
        lang_elem = article.select_one("[itemprop='programmingLanguage']")
        language = lang_elem.get_text(strip=True) if lang_elem else None
        
        # Stars (total)
        stars = 0
        stars_link = article.select_one("a[href$='/stargazers']")
        if stars_link:
            stars_text = stars_link.get_text(strip=True).replace(",", "")
            stars = self._parse_number(stars_text)
        
        # Forks
        forks = 0
        forks_link = article.select_one("a[href$='/forks']")
        if forks_link:
            forks_text = forks_link.get_text(strip=True).replace(",", "")
            forks = self._parse_number(forks_text)
        
        # Stars today
        stars_today = 0
        stars_today_elem = article.select_one("span.d-inline-block.float-sm-right")
        if stars_today_elem:
            text = stars_today_elem.get_text(strip=True)
            # Extract number from "1,234 stars today"
            stars_today = self._parse_number(text.split()[0].replace(",", ""))
        
        return GitHubProject(
            name=name,
            url=url,
            description=description,
            language=language,
            stars=stars,
            stars_today=stars_today,
            forks=forks,
        )
    
    def _parse_number(self, text: str) -> int:
        """Parse a number from text, handling k/m suffixes."""
        text = text.lower().strip()
        if not text:
            return 0
        
        try:
            if text.endswith("k"):
                return int(float(text[:-1]) * 1000)
            elif text.endswith("m"):
                return int(float(text[:-1]) * 1000000)
            return int(text)
        except ValueError:
            return 0
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
