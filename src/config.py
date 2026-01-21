"""Configuration management for Intelligence Agent."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class GitHubConfig(BaseModel):
    """GitHub Trending collector configuration."""
    enabled: bool = True
    languages: list[str] = Field(default_factory=lambda: ["python", "typescript", "go", "rust"])
    since: str = "daily"  # daily, weekly, monthly
    limit: int = 10
    keywords: list[str] = Field(default_factory=list)  # 关键词过滤


class HackerNewsConfig(BaseModel):
    """Hacker News collector configuration."""
    enabled: bool = True
    story_type: str = "top"  # top, new, best, show, ask
    limit: int = 10


class CollectorsConfig(BaseModel):
    """All collectors configuration."""
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)


class AnalyzerConfig(BaseModel):
    """LLM analyzer configuration."""
    provider: str = "openai"  # openai, local
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model: str = "gpt-4o-mini"
    enabled: bool = True


class FeishuConfig(BaseModel):
    """Feishu (Lark) notifier configuration."""
    enabled: bool = False
    webhook_url: Optional[str] = None
    app_id: Optional[str] = None  # WebSocket Bot
    app_secret: Optional[str] = None  # WebSocket Bot


class DingtalkConfig(BaseModel):
    """DingTalk notifier configuration."""
    enabled: bool = False
    webhook_url: Optional[str] = None
    secret: Optional[str] = None  # For signed messages


class NotifiersConfig(BaseModel):
    """All notifiers configuration."""
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    dingtalk: DingtalkConfig = Field(default_factory=DingtalkConfig)


class ScheduleConfig(BaseModel):
    """Scheduler configuration."""
    enabled: bool = False
    cron: str = "0 9 * * *"  # Default: 9:00 AM daily


class Config(BaseSettings):
    """Main configuration class."""
    collectors: CollectorsConfig = Field(default_factory=CollectorsConfig)
    analyzer: AnalyzerConfig = Field(default_factory=AnalyzerConfig)
    notifiers: NotifiersConfig = Field(default_factory=NotifiersConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """Load configuration from YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        # Support environment variable substitution for sensitive data
        cls._substitute_env_vars(data)
        
        return cls(**data)
    
    @classmethod
    def _substitute_env_vars(cls, data: dict) -> None:
        """Recursively substitute environment variables in config."""
        for key, value in data.items():
            if isinstance(value, dict):
                cls._substitute_env_vars(value)
            elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                data[key] = os.getenv(env_var, "")

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from file or use defaults."""
        if config_path:
            return cls.from_yaml(config_path)
        
        # Try default locations
        default_paths = [
            Path("config.yaml"),
            Path("config.yml"),
            Path.home() / ".intelligence-agent" / "config.yaml",
        ]
        
        for path in default_paths:
            if path.exists():
                return cls.from_yaml(path)
        
        # Return default configuration
        return cls()
