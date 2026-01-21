"""Feishu WebSocket Bot implementation."""

import asyncio
import json
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1.model import P2ImMessageReceiveV1

from ..config import Config
from ..analyzers.llm_analyzer import LLMAnalyzer


class FeishuBot:
    """Feishu Bot using WebSocket."""
    
    SYSTEM_PROMPT = """你是一个智能助手，专注于技术项目分析和信息安全领域。
如果你不知道，就说不知道。用简洁、专业的中文回答。
"""
    
    def __init__(self, config: Config):
        self.config = config
        self.feishu_config = config.notifiers.feishu
        self.analyzer = LLMAnalyzer(config.analyzer)
        
        # Initialize Client
        self.client = lark.Client.builder() \
            .app_id(self.feishu_config.app_id) \
            .app_secret(self.feishu_config.app_secret) \
            .build()
        
    def start(self):
        """Start the WebSocket client."""
        if not self.feishu_config.app_id or not self.feishu_config.app_secret:
            print("❌ Feishu App ID/Secret not configured")
            return

        print(f"🤖 Starting Feishu Bot (App ID: {self.feishu_config.app_id})...")
        
        # Register event handler
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._handle_message) \
            .build()
            
        # Start WS client
        ws_client = lark.ws.Client(
            self.feishu_config.app_id,
            self.feishu_config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.DEBUG,
        )
        
        ws_client.start()
        
    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        """Handle incoming message."""
        try:
            event = data.event
            
            # Extract content (it's a JSON string)
            content_json = json.loads(event.message.content)
            user_text = content_json.get("text", "").strip()
            
            # Check for mentions
            mentions = event.message.mentions or []
            is_group = event.message.chat_type == "group"
            
            # If group chat, verified we are mentioned
            if is_group:
                # If mentions is empty, update logic to ignore unless mentioned
                # (Assuming 'im:message:group_at_msg' permission usually handles this, 
                # but 'read_all' might override it. We enforce it here.)
                if not mentions:
                    print(f"Ignored group message (no mention): {user_text}")
                    return

                # Clean @mention from text (remove @name)
                # Usually mentions appear as "@_user_1" in content text, 
                # and mentions array has {key: "@_user_1", name: "BotName"}
                for mention in mentions:
                    # Remove the mention key from text (e.g. "@_user_1")
                    user_text = user_text.replace(mention.key, "").strip()

            chat_id = event.message.chat_id
            
            print(f"📩 Received: {user_text}")
            
            # Simple command handling
            if user_text == "/ping":
                self._reply_text(data, "Pong! 🏓")
                return
            
            # Call LLM
            reply_text = self._call_llm(user_text)
            
            # Reply
            self._reply_text(data, reply_text)
            
        except Exception as e:
            print(f"Error handling message: {e}")
            self._reply_text(data, "❌ Error processing request")

    def _call_llm(self, user_text: str) -> str:
        """Call GLM-4.7 via OpenAI SDK."""
        if not self.analyzer.client:
            return "❌ AI Analyzer not configured"
            
        try:
            response = self.analyzer.client.chat.completions.create(
                model=self.config.analyzer.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.7,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"LLM Error: {e}")
            return f"Error calling AI: {str(e)}"

    def _reply_text(self, data: P2ImMessageReceiveV1, text: str):
        """Reply with text message."""
        try:
            # We need to construct the reply request manually or use client
            # The WS 'data' object doesn't have a direct reply method in SDK v1.2
            # We use the HTTP client to send message
            
            content = json.dumps({"text": text})
            
            request = lark.im.v1.CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(lark.im.v1.CreateMessageRequestBody.builder()
                    .receive_id(data.event.message.chat_id)
                    .msg_type("text")
                    .content(content)
                    .build()) \
                .build()
                
            response = self.client.im.v1.message.create(request)
            
            if not response.success():
                print(f"Failed to reply: {response.code} {response.msg}")
                
        except Exception as e:
            print(f"Error sending reply: {e}")

