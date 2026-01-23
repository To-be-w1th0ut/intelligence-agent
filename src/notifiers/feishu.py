"""Feishu (Lark) notifier - supports both Webhook and Bot API."""

import json
from typing import Optional

import httpx
import lark_oapi as lark

from ..config import FeishuConfig
from ..analyzers.llm_analyzer import ProjectAnalysis


class FeishuNotifier:
    """Send notifications to Feishu via Bot API or Webhook."""
    
    def __init__(self, config: FeishuConfig):
        self.config = config
        self.http_client = httpx.Client(timeout=30.0)
        
        # Initialize Lark Client if app credentials available
        self.lark_client = None
        if config.app_id and config.app_secret:
            self.lark_client = lark.Client.builder() \
                .app_id(config.app_id) \
                .app_secret(config.app_secret) \
                .build()
    
    def send(self, analyses: list[ProjectAnalysis], chat_id: str = None) -> bool:
        """Send project analyses to Feishu.
        
        If chat_id is provided and Bot API is available, send via Bot.
        Otherwise, fall back to Webhook.
        """
        if not self.config.enabled:
            return False
        
        # Build card
        card = self._build_card(analyses)
        
        # Prefer Bot API if available
        if self.lark_client and chat_id:
            return self._send_via_bot(card, chat_id)
        elif self.lark_client and self.config.app_id:
            # Try to send to a default chat (need to get chat_id first)
            # For now, we'll try to use webhook as fallback
            pass
        
        # Fall back to Webhook
        if self.config.webhook_url:
            return self._send_via_webhook(card)
        
        print("❌ No valid Feishu sending method configured")
        return False
    
    def send_to_chat(self, analyses: list[ProjectAnalysis], chat_id: str) -> bool:
        """Send analyses to a specific chat via Bot API."""
        if not self.lark_client:
            print("❌ Bot API not configured (missing app_id/app_secret)")
            return False
        
        card = self._build_card(analyses)
        return self._send_via_bot(card, chat_id)
    
    def _send_via_bot(self, card: dict, chat_id: str) -> bool:
        """Send card message via Bot API."""
        try:
            content = json.dumps(card)
            
            request = lark.im.v1.CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(lark.im.v1.CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("interactive")
                    .content(content)
                    .build()) \
                .build()
            
            response = self.lark_client.im.v1.message.create(request)
            
            if response.success():
                print("✅ Feishu Bot notification sent successfully")
                return True
            else:
                print(f"❌ Feishu Bot error: {response.code} - {response.msg}")
                return False
                
        except Exception as e:
            print(f"❌ Feishu Bot exception: {e}")
            return False
    
    def _send_via_webhook(self, card: dict) -> bool:
        """Send card message via Webhook."""
        try:
            payload = {
                "msg_type": "interactive",
                "card": card,
            }
            
            response = self.http_client.post(
                self.config.webhook_url,
                json=payload,
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get("code") == 0:
                print("✅ Feishu Webhook notification sent successfully")
                return True
            else:
                print(f"❌ Feishu Webhook error: {result.get('msg')}")
                return False
                
        except httpx.HTTPError as e:
            print(f"❌ Feishu Webhook HTTP error: {e}")
            return False
    
    def _build_card(self, analyses: list[ProjectAnalysis]) -> dict:
        """Build Feishu interactive card."""
        elements = []
        
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
        # Build highlights
        highlights = ""
        if analysis.highlights:
            highlights = "\n".join(f"• {h}" for h in analysis.highlights)
            
        # Build competitors
        competitors = ""
        # Check if 'competitors' attribute exists (it was dynamically added to dict but maybe not dataclass yet if not updated)
        # Safely access attributes
        if hasattr(analysis, "competitors") and analysis.competitors:
             competitors = f"**🥊 竞品对比**: {analysis.competitors}"
        elif isinstance(analysis.raw_data, dict) and "competitors" in analysis.raw_data:
             competitors = f"**🥊 竞品对比**: {analysis.raw_data['competitors']}"

        # Construct content
        content = f"**[{analysis.title}]({analysis.url})**\n\n{analysis.summary}"
        
        if highlights:
            content += f"\n\n**✨ 核心亮点**:\n{highlights}"
            
        if competitors:
            content += f"\n\n{competitors}"
            
        if analysis.potential:
            content += f"\n\n**🚀 潜力**: {analysis.potential}"

        return {
            "tag": "markdown",
            "content": content.strip(),
        }
    
    def send_test(self) -> bool:
        """Send a test message."""
        # Prefer Bot API
        if self.lark_client:
            print("ℹ️ Bot API test requires a chat_id. Use Webhook test instead.")
        
        if not self.config.webhook_url:
            print("❌ Feishu Webhook not configured")
            return False
        
        payload = {
            "msg_type": "text",
            "content": {
                "text": "🎉 Intelligence Agent 测试消息 - 飞书机器人配置成功！"
            }
        }
        
        try:
            response = self.http_client.post(self.config.webhook_url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("code") == 0
        except httpx.HTTPError as e:
            print(f"❌ Feishu test failed: {e}")
            return False
    
    def close(self):
        """Close the HTTP client."""
        self.http_client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
