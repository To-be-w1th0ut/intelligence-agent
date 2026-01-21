"""Feishu WebSocket Bot implementation."""

import json
import threading
from collections import deque
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1.model import P2ImMessageReceiveV1

from ..config import Config
from ..analyzers.llm_analyzer import LLMAnalyzer


class FeishuBot:
    """Feishu Bot using WebSocket."""
    
    SYSTEM_PROMPT = """你是一个真实、有个性的朋友，不是冰冷的机器人。

回复风格：
- 像朋友聊天一样自然，可以用口语、emoji、网络用语
- 简短有力，别啰嗦，别用"首先、其次、总之"这种套路
- 如果用户只是打招呼或者没说啥实质内容，随便回个俏皮话就行
- 遇到技术问题可以专业一点，但也别太死板
- 偶尔可以开个玩笑、吐槽一下

禁止事项：
- 别自称"我是AI助手"或类似的话
- 别用"亲爱的用户"这种客服腔
- 别列一堆条条框框
"""
    
    def __init__(self, config: Config):
        self.config = config
        self.feishu_config = config.notifiers.feishu
        self.analyzer = LLMAnalyzer(config.analyzer)
        
        # Thread-safe message deduplication (using message_id, not event_id)
        self._processed_messages: set[str] = set()
        self._lock = threading.Lock()
        self._max_cache_size = 500
        
        # Bot identity (fetched on start)
        self.bot_info = None
        
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

        # Get Bot Info manually (SDK missing bot module)
        try:
            import httpx
            # 1. Get Tenant Access Token
            token_res = httpx.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.feishu_config.app_id,
                    "app_secret": self.feishu_config.app_secret
                },
                timeout=10
            )
            token_data = token_res.json()
            if token_data.get("code") != 0:
                print(f"❌ Auth failed: {token_data}")
                return
            token = token_data["tenant_access_token"]
            
            # 2. Get Bot Info
            info_res = httpx.get(
                "https://open.feishu.cn/open-apis/bot/v3/info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            info_data = info_res.json()
            if info_data.get("code") != 0:
                 print(f"❌ Info failed: {info_data}")
                 return
                 
            self.bot_info = type('BotInfo', (object,), info_data["bot"])()
            print(f"✅ Identity Confirmed: {self.bot_info.app_name} (OpenID: {self.bot_info.open_id})")
            
        except Exception as e:
            print(f"❌ Failed to fetch bot identity: {e}")
            return

        # Register event handler
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._handle_message) \
            .build()
            
        # Start WS client
        ws_client = lark.ws.Client(
            self.feishu_config.app_id,
            self.feishu_config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,  # Reduce noise
        )
        
        ws_client.start()
        
    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        """Handle incoming message with thread-safe deduplication."""
        try:
            event = data.event
            message_id = event.message.message_id
            
            # ========== Thread-safe Deduplication ==========
            with self._lock:
                if message_id in self._processed_messages:
                    print(f"🔄 Duplicate message ignored: {message_id}")
                    return
                    
                # Add to cache
                self._processed_messages.add(message_id)
                
                # Prevent unbounded growth
                if len(self._processed_messages) > self._max_cache_size:
                    # Remove oldest entries (convert to list, slice, rebuild set)
                    oldest = list(self._processed_messages)[:self._max_cache_size // 2]
                    for old_id in oldest:
                        self._processed_messages.discard(old_id)
            
            # ========== Ignore Self ==========
            if hasattr(event, 'sender') and hasattr(event.sender, 'sender_id'):
                sender_id = event.sender.sender_id.open_id
                if self.bot_info and sender_id == self.bot_info.open_id:
                    print(f"🔄 Ignoring self-message")
                    return

            # ========== Extract Content ==========
            content_json = json.loads(event.message.content)
            user_text = content_json.get("text", "").strip()
            
            # ========== Group Chat Mention Filter ==========
            mentions = event.message.mentions or []
            is_group = event.message.chat_type == "group"
            
            if is_group:
                if not mentions:
                    print(f"Ignored group message (no mention): {user_text[:30]}...")
                    return

                # Verify it's us and clean mention
                mentioned_me = False
                for mention in mentions:
                    if self.bot_info and mention.id.open_id == self.bot_info.open_id:
                        mentioned_me = True
                        user_text = user_text.replace(mention.key, "").strip()
                
                if not mentioned_me:
                    print(f"Ignored group message (mentioned others)")
                    return

            print(f"📩 Processing [{message_id}]: {user_text[:50] if user_text else '(empty)'}...")
            
            # ========== Empty Message ==========
            if not user_text or len(user_text.strip()) < 2:
                self._reply_text(data, "你好！有什么可以帮你的？😊")
                return
            
            # ========== Commands ==========
            if user_text == "/ping":
                self._reply_text(data, "Pong! 🏓")
                return
            
            # ========== LLM Response ==========
            reply_text = self._call_llm(user_text)
            self._reply_text(data, reply_text)
            
        except Exception as e:
            print(f"Error handling message: {e}")
            import traceback
            traceback.print_exc()

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
        """Reply to a specific message with @mention."""
        try:
            event = data.event
            sender_open_id = event.sender.sender_id.open_id
            original_message_id = event.message.message_id
            is_group = event.message.chat_type == "group"
            
            # In group chat, @mention the sender; in private chat, just reply
            if is_group:
                # Feishu @mention format: <at user_id="open_id">Name</at>
                content = json.dumps({
                    "text": f"<at user_id=\"{sender_open_id}\"></at> {text}"
                })
            else:
                content = json.dumps({"text": text})
            
            # Use ReplyMessageRequest to reply to specific message
            request = lark.im.v1.ReplyMessageRequest.builder() \
                .message_id(original_message_id) \
                .request_body(lark.im.v1.ReplyMessageRequestBody.builder()
                    .msg_type("text")
                    .content(content)
                    .build()) \
                .build()
                
            response = self.client.im.v1.message.reply(request)
            
            if not response.success():
                print(f"Failed to reply: {response.code} {response.msg}")
                
        except Exception as e:
            print(f"Error sending reply: {e}")
            import traceback
            traceback.print_exc()
