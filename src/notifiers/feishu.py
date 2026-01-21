"""Feishu (Lark) webhook notifier."""

import json
from typing import Optional

import httpx

from ..config import FeishuConfig
from ..analyzers.llm_analyzer import ProjectAnalysis


class FeishuNotifier:
    """Send notifications to Feishu via webhook."""
    
    def __init__(self, config: FeishuConfig):
        self.config = config
        self.client = httpx.Client(timeout=30.0)
    
    def send(self, analyses: list[ProjectAnalysis]) -> bool:
        """Send project analyses to Feishu."""
        if not self.config.enabled or not self.config.webhook_url:
            return False
        
        try:
            # Build card message
            card = self._build_card(analyses)
            
            payload = {
                "msg_type": "interactive",
                "card": card,
            }
            
            response = self.client.post(
                self.config.webhook_url,
                json=payload,
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get("code") == 0:
                print("✅ Feishu notification sent successfully")
                return True
            else:
                print(f"❌ Feishu error: {result.get('msg')}")
                return False
                
        except httpx.HTTPError as e:
            print(f"❌ Feishu HTTP error: {e}")
            return False
    
    def _build_card(self, analyses: list[ProjectAnalysis]) -> dict:
        """Build Feishu interactive card."""
        elements = []
        
        # Header
        github_projects = [a for a in analyses if a.source == "github"]
        hn_stories = [a for a in analyses if a.source == "hackernews"]
        
        # GitHub section
        if github_projects:
            elements.append({
                "tag": "markdown",
                "content": "## 🔥 GitHub Trending"
            })
            elements.append({"tag": "hr"})
            
            for project in github_projects[:5]:
                elements.append(self._build_project_element(project))
                elements.append({"tag": "hr"})
        
        # Hacker News section
        if hn_stories:
            elements.append({
                "tag": "markdown",
                "content": "## 📰 Hacker News"
            })
            elements.append({"tag": "hr"})
            
            for story in hn_stories[:5]:
                elements.append(self._build_project_element(story))
                elements.append({"tag": "hr"})
        
        # Remove last hr
        if elements and elements[-1].get("tag") == "hr":
            elements.pop()
        
        return {
            "config": {
                "wide_screen_mode": True,
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🚀 今日热门项目推送",
                },
                "template": "blue",
            },
            "elements": elements,
        }
    
    def _build_project_element(self, analysis: ProjectAnalysis) -> dict:
        """Build element for a single project."""
        # Build highlights text
        highlights_text = ""
        if analysis.highlights:
            highlights_text = "\n".join(f"• {h}" for h in analysis.highlights[:3])
        
        # Build tech stack text
        tech_text = ""
        if analysis.tech_stack:
            tech_text = f"**技术栈**: {', '.join(analysis.tech_stack[:5])}"
        
        content = f"""**[{analysis.title}]({analysis.url})**

{analysis.summary}

{highlights_text}

{tech_text}
"""
        
        return {
            "tag": "markdown",
            "content": content.strip(),
        }
    
    def send_test(self) -> bool:
        """Send a test message."""
        if not self.config.enabled or not self.config.webhook_url:
            print("❌ Feishu not configured")
            return False
        
        payload = {
            "msg_type": "text",
            "content": {
                "text": "🎉 Intelligence Agent 测试消息 - 飞书机器人配置成功！"
            }
        }
        
        try:
            response = self.client.post(self.config.webhook_url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("code") == 0
        except httpx.HTTPError as e:
            print(f"❌ Feishu test failed: {e}")
            return False
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
