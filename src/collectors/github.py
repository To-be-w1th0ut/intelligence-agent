"""GitHub Trending collector with enhanced filtering."""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    created_at: Optional[datetime] = None  # Repo creation date
    growth_rate: float = 0.0  # stars_today / stars (as percentage)
    readme_content: Optional[str] = None  # New: Truncated README content
    

class GitHubCollector:
    """Collects trending projects from GitHub with smart filtering."""
    
    BASE_URL = "https://github.com/trending"
    API_URL = "https://api.github.com/repos"
    SEARCH_API_URL = "https://api.github.com/search/repositories"
    RAW_BASE_URL = "https://raw.githubusercontent.com"
    HISTORY_FILE = ".github_history.json"
    
    def __init__(self, config: GitHubConfig):
        self.config = config
        self.client = httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/vnd.github.v3+json",
            }
        )
        self._history = self._load_history()
    
    def collect(self) -> list[GitHubProject]:
        """Collect trending projects with enhanced filtering."""
        if not self.config.enabled:
            return []
        
        all_projects = []
        
        # Collect for each configured language
        languages = self.config.languages or [None]
        
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

        # ========== NEW: Exclude noise ==========
        unique_projects = self._filter_by_excluded_keywords(unique_projects)
        
        # ========== NEW: Fetch creation dates via API ==========
        unique_projects = self._enrich_with_api_data(unique_projects)
        
        # ========== NEW: Filter by age (< 60 days) ==========
        max_age_days = getattr(self.config, 'max_age_days', 60)
        if max_age_days:
            unique_projects = self._filter_by_age(unique_projects, max_age_days)
        
        # ========== NEW: Calculate growth rate ==========
        for project in unique_projects:
            if project.stars > 0:
                project.growth_rate = (project.stars_today / project.stars) * 100
        
        # ========== NEW: Sort by growth rate instead of raw stars ==========
        unique_projects.sort(key=lambda p: p.growth_rate, reverse=True)
        
        # ========== NEW: Filter out already-seen projects ==========
        unique_projects = self._filter_by_history(unique_projects)
        
        # Limit results
        result = unique_projects[:self.config.limit]
        
        # ========== NEW: Fetch README for deep analysis ==========
        result = self._fetch_readmes(result)
        
        # ========== NEW: Save to history ==========
        self._update_history(result)
        
        return result
    
    def _fetch_readmes(self, projects: list[GitHubProject]) -> list[GitHubProject]:
        """Fetch README content for projects."""
        for project in projects:
            try:
                # Try master then main
                for branch in ["main", "master"]:
                    url = f"{self.RAW_BASE_URL}/{project.name}/{branch}/README.md"
                    res = self.client.get(url)
                    if res.status_code == 200:
                        # Truncate to 3000 chars to save tokens
                        project.readme_content = res.text[:3000]
                        break
            except Exception as e:
                print(f"  ⚠️ Failed to fetch README for {project.name}: {e}")
        return projects

    def fetch_project(self, repo_name: str) -> Optional[GitHubProject]:
        """Fetch a single project by owner/repo name."""
        try:
            # Get metadata
            res = self.client.get(f"{self.API_URL}/{repo_name}")
            if res.status_code != 200:
                print(f"❌ Failed to fetch repo metadata: {res.status_code}")
                return None
            
            data = res.json()
            project = GitHubProject(
                name=data["full_name"],
                url=data["html_url"],
                description=data["description"],
                language=data["language"],
                stars=data["stargazers_count"],
                stars_today=0,  # Not available from standard API without tracking
                forks=data["forks_count"],
                created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
                # readme_content is fetched below
            )
            
            # Get README
            self._fetch_readmes([project])
            return project
            
        except Exception as e:
            print(f"❌ Error fetching project {repo_name}: {e}")
            return None

    def search_repository(self, query: str) -> Optional[GitHubProject]:
        """Search for the best matching repository by name."""
        try:
            # Search for repositories matching the query, sorted by stars
            params = {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": 1
            }
            res = self.client.get(self.SEARCH_API_URL, params=params)
            
            if res.status_code != 200:
                print(f"❌ Search failed: {res.status_code}")
                return None
            
            data = res.json()
            items = data.get("items", [])
            
            if not items:
                return None
                
            # Use the top result
            item = items[0]
            repo_name = item["full_name"]
            
            # Fetch full details using existing method (to ensure consistent data structure)
            return self.fetch_project(repo_name)
            
        except Exception as e:
            print(f"❌ Error searching repository {query}: {e}")
            return None

    def _enrich_with_api_data(self, projects: list[GitHubProject]) -> list[GitHubProject]:
        """Fetch additional data from GitHub API."""
        for project in projects:
            try:
                # Rate limit: be gentle
                response = self.client.get(f"{self.API_URL}/{project.name}")
                if response.status_code == 200:
                    data = response.json()
                    created_str = data.get("created_at")
                    if created_str:
                        project.created_at = datetime.fromisoformat(
                            created_str.replace("Z", "+00:00")
                        )
            except Exception as e:
                # API call failed, continue without creation date
                print(f"  ⚠️ API lookup failed for {project.name}: {e}")
                continue
        return projects
    
    def _filter_by_age(
        self, 
        projects: list[GitHubProject], 
        max_age_days: int
    ) -> list[GitHubProject]:
        """Filter to only include recently created projects."""
        cutoff = datetime.now().astimezone() - timedelta(days=max_age_days)
        filtered = []
        
        for project in projects:
            if project.created_at:
                if project.created_at > cutoff:
                    filtered.append(project)
                else:
                    print(f"  📅 Skipped old project: {project.name} (created {project.created_at.date()})")
            else:
                # If we couldn't get creation date, include it anyway
                filtered.append(project)
        
        return filtered
    
    def _filter_by_history(self, projects: list[GitHubProject]) -> list[GitHubProject]:
        """Filter out projects that were already recommended."""
        filtered = []
        for project in projects:
            if project.name not in self._history:
                filtered.append(project)
            else:
                print(f"  🔄 Skipped already-seen: {project.name}")
        return filtered
    
    def _load_history(self) -> set:
        """Load recommendation history from file."""
        try:
            if os.path.exists(self.HISTORY_FILE):
                with open(self.HISTORY_FILE, "r") as f:
                    data = json.load(f)
                    # Clean old entries (> 30 days)
                    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
                    return {k for k, v in data.items() if v > cutoff}
        except Exception:
            pass
        return set()
    
    def _update_history(self, projects: list[GitHubProject]):
        """Update history file with newly recommended projects."""
        try:
            # Load existing
            history = {}
            if os.path.exists(self.HISTORY_FILE):
                with open(self.HISTORY_FILE, "r") as f:
                    history = json.load(f)
            
            # Add new
            now = datetime.now().isoformat()
            for project in projects:
                history[project.name] = now
            
            # Clean old entries
            cutoff = (datetime.now() - timedelta(days=30)).isoformat()
            history = {k: v for k, v in history.items() if v > cutoff}
            
            # Save
            with open(self.HISTORY_FILE, "w") as f:
                json.dump(history, f, indent=2)
                
        except Exception as e:
            print(f"  ⚠️ Failed to update history: {e}")
    
    
    def _filter_by_excluded_keywords(self, projects: list[GitHubProject]) -> list[GitHubProject]:
        """Filter out projects containing excluded keywords (noise)."""
        # If no excluded keywords, return all
        if not hasattr(self.config, 'excluded_keywords') or not self.config.excluded_keywords:
            return projects
            
        excluded = [kw.lower() for kw in self.config.excluded_keywords]
        filtered = []
        
        for project in projects:
            text = f"{project.name} {project.description or ''}".lower()
            if any(noise in text for noise in excluded):
                print(f"  🗑️ Skipped noise ({next(kw for kw in excluded if kw in text)}): {project.name}")
                continue
            filtered.append(project)
        
        return filtered
            
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
            stars_today = self._parse_number(text.split()[0].replace(",", ""))
        
        return GitHubProject(
            name=name,
            url=url,
            description=description,
            language=language,
            stars=stars,
            stars_today=stars_today,
            forks=forks,
            readme_content=None
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
