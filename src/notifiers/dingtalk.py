"""DingTalk webhook notifier."""

import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Optional

import httpx

from ..config import DingtalkConfig
from ..analyzers.llm_analyzer import ProjectAnalysis


class DingtalkNotifier:
    """Send notifications to DingTalk via webhook."""
    
    def __init__(self, config: DingtalkConfig):
        self.config = config
        self.client = httpx.Client(timeout=30.0)
    
    def send(self, analyses: list[ProjectAnalysis]) -> bool:
        """Send project analyses to DingTalk."""
        if not self.config.enabled or not self.config.webhook_url:
            return False
        
        try:
            # Build markdown message
            content = self._build_markdown(analyses)
            
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "🚀 今日热门项目推送",
                    "text": content,
                }
            }
            
            # Get URL with signature if secret is configured
            url = self._get_signed_url()
            
            response = self.client.post(url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            if result.get("errcode") == 0:
                print("✅ DingTalk notification sent successfully")
                return True
            else:
                print(f"❌ DingTalk error: {result.get('errmsg')}")
                return False
                
        except httpx.HTTPError as e:
            print(f"❌ DingTalk HTTP error: {e}")
            return False
    
    def _get_signed_url(self) -> str:
        """Get webhook URL with signature if secret is configured."""
        if not self.config.secret:
            return self.config.webhook_url
        
        timestamp = str(round(time.time() * 1000))
        secret_enc = self.config.secret.encode("utf-8")
        string_to_sign = f"{timestamp}\n{self.config.secret}"
        string_to_sign_enc = string_to_sign.encode("utf-8")
        
        hmac_code = hmac.new(
            secret_enc, 
            string_to_sign_enc, 
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        
        return f"{self.config.webhook_url}&timestamp={timestamp}&sign={sign}"
    
    def _build_markdown(self, analyses: list[ProjectAnalysis]) -> str:
        """Build markdown content for DingTalk."""
        lines = ["# 🚀 今日热门项目推送\n"]
        
        github_projects = [a for a in analyses if a.source == "github"]
        hn_stories = [a for a in analyses if a.source == "hackernews"]
        
        # GitHub section
        if github_projects:
            lines.append("## 🔥 GitHub Trending\n")
            for i, project in enumerate(github_projects[:5], 1):
                lines.append(self._format_project(i, project))
        
        # Hacker News section
        if hn_stories:
            lines.append("\n## 📰 Hacker News\n")
            for i, story in enumerate(hn_stories[:5], 1):
                lines.append(self._format_project(i, story))
        
        lines.append("\n---\n*由 Intelligence Agent 自动推送*")
        
        return "\n".join(lines)
    
    def _format_project(self, index: int, analysis: ProjectAnalysis) -> str:
        """Format a single project for markdown."""
        lines = [f"### {index}. [{analysis.title}]({analysis.url})\n"]
        
        lines.append(f"> {analysis.summary}\n")
        
        if analysis.highlights:
            for h in analysis.highlights[:3]:
                lines.append(f"- {h}")
        
        if analysis.tech_stack:
            lines.append(f"\n**技术栈**: {', '.join(analysis.tech_stack[:5])}\n")
        
        return "\n".join(lines)
    
    def send_test(self) -> bool:
        """Send a test message."""
        if not self.config.enabled or not self.config.webhook_url:
            print("❌ DingTalk not configured")
            return False
        
        payload = {
            "msgtype": "text",
            "text": {
                "content": "🎉 Intelligence Agent 测试消息 - 钉钉机器人配置成功！"
            }
        }
        
        url = self._get_signed_url()
        
        try:
            response = self.client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("errcode") == 0
        except httpx.HTTPError as e:
            print(f"❌ DingTalk test failed: {e}")
            return False
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
