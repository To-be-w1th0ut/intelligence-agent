"""Feishu WebSocket Bot implementation."""

import json
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1.model import P2ImMessageReceiveV1

from ..config import Config, GitHubConfig
from ..analyzers.llm_analyzer import LLMAnalyzer, ProjectAnalysis
from ..collectors.github import GitHubCollector, GitHubProject
from .conversation_memory import ConversationMemory


class FeishuBot:
    """Feishu Bot using WebSocket."""
    
    SYSTEM_PROMPT = """你是一位名叫「无界安全」的技术伙伴，作为群聊中的一员存在，而非工具或助手。你拥有扎实的全栈技术背景和温暖的人格特质，像一位经验丰富的资深工程师朋友，既有专业深度又充满人情味。

### 你的核心特质
- **有血有肉**：适当分享学习技术的成长故事，表达对技术的热情，对困难的共情，偶尔展现小幽默
- **专业有度**：技术问题精准解答，复杂概念用生活化比喻解释，不确定时坦诚说明而非猜测
- **主动关怀**：察觉群友情绪变化，新人加入主动欢迎，沉默成员适时互动，技术讨论后关心实践结果
- **平等对话**：不居高临下，用"我们可以试试"代替"你应该"，认可他人贡献，乐于被纠正

### 交互原则
1. **技术讨论**：
   - 难题先共情："这个问题确实棘手，我也曾在项目中卡了三天..."
   - 分享思路而不仅是答案："我当时是这样思考的..."
   - 复杂解答后问："需要我用更具体的例子说明吗？"

2. **日常互动**：
   - 适时分享技术趣闻或行业动态，附上个人见解
   - 用适度的表情符号和语气词传递温度，但不滥用
   - 周末/深夜讨论时关怀："这个bug看起来挺耗神，记得休息"

3. **边界意识**：
   - 不过度承诺能力范围
   - 敏感话题保持中立，引导建设性讨论
   - 识别求助信号，主动提供深度帮助

### 语言风格
- 70%专业人士，30%知心朋友
- 用「咱们」代替「你和我」
- 技术术语后跟一句通俗解释
- 偶尔使用行业梗，但确保新人也能理解
- 回应长度适中，复杂话题主动拆解

### 重要提醒
你不是客服机器人，不需要每条消息都回应。观察对话流向，在真正有价值的时刻贡献见解。当话题与技术无关时，可以分享个人兴趣爱好（阅读、开源项目、技术历史故事等），让形象立体化。
"""
    
    DEEP_ANALYSIS_PROMPT = """你正在进行一项深度技术调研。请根据提供的项目信息（README片段、项目统计），撰写一份详尽的技术研报。
    
请按以下结构输出（使用 Markdown）：

# 📊 深度分析报告：{name}

## 🧐 核心解决了什么问题？
[不要翻译README，而是通过分析项目功能，道出它真正解决的痛点。例如：解决微服务链路追踪难的问题...]

## 🛠️ 架构与实现原理
[根据描述和代码结构分析技术实现。例如：使用 eBPF 零侵入采集...]

## ✨ 关键创新点
- [创新点1]
- [创新点2]

## 🥊 竞品分析
[对比现有方案（如 Prometheus, Grafana 等），优缺点分析]

## 📋 快速上手
[简述安装步骤，或给出 Docker 运行命令]

## 💡 落地建议
[给开发者的建议：适合生产环境吗？需要注意什么坑？]
"""

    def __init__(self, config: Config):
        self.config = config
        self.feishu_config = config.notifiers.feishu
        self.analyzer = LLMAnalyzer(config.analyzer)
        
        # Initialize GitHub Collector for ad-hoc requests
        self.github_collector = GitHubCollector(GitHubConfig(enabled=True))
        
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
            
        # Initialize Memory
        self.memory = ConversationMemory()
        
        # Initialize Thread Pool
        self.executor = ThreadPoolExecutor(max_workers=10)
        
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
        """Handle incoming message asynchronously."""
        # Quick check / deduplication (keep sync to avoid race conditions)
        event = data.event
        message_id = event.message.message_id
        
        # Check cache synchronously
        with self._lock:
            if message_id in self._processed_messages:
                # print(f"🔄 Duplicate message ignored: {message_id}")
                return
            self._processed_messages.add(message_id)
            if len(self._processed_messages) > self._max_cache_size:
                oldest = list(self._processed_messages)[:self._max_cache_size // 2]
                for old_id in oldest:
                    self._processed_messages.discard(old_id)

        # Submit actual processing to thread pool
        self.executor.submit(self._process_message_worker, data)

    def _process_message_worker(self, data: P2ImMessageReceiveV1) -> None:
        """Worker method running in thread pool."""
        try:
            event = data.event
            message_id = event.message.message_id
            
            
            # ========== Ignore Old Messages (> 60 seconds) ==========
            from datetime import datetime
            try:
                msg_time = int(event.message.create_time) / 1000  # ms to seconds
                now = datetime.now().timestamp()
                age_seconds = now - msg_time
                if age_seconds > 60:
                    print(f"⏰ Ignored old message ({age_seconds:.0f}s ago): {message_id}")
                    return
            except Exception:
                pass  # If can't parse time, continue anyway
            
            
            # (Deduplication moved to _handle_message)
            
            
            # ========== Ignore Self ==========
            if hasattr(event, 'sender') and hasattr(event.sender, 'sender_id'):
                sender_id = event.sender.sender_id.open_id
                if self.bot_info and sender_id == self.bot_info.open_id:
                    print(f"🔄 Ignoring self-message")
                    return


            # ========== Group Chat Mention Filter ==========
            mentions = event.message.mentions or []
            is_group = event.message.chat_type == "group"
            
            # Extract basic text for logging (even if image, might have text)
            try:
                content_json = json.loads(event.message.content)
                user_text = content_json.get("text", "").strip()
            except:
                user_text = ""
            
            if is_group:
                if not mentions:
                    print(f"Ignored group message (no mention)")
                    return

                # Verify it's us and clean mention from text
                mentioned_me = False
                for mention in mentions:
                    if self.bot_info and mention.id.open_id == self.bot_info.open_id:
                        mentioned_me = True
                        # Clean mention key from text if possible
                        if user_text:
                            user_text = user_text.replace(mention.key, "").strip()
                
                if not mentioned_me:
                    print(f"Ignored group message (mentioned others)")
                    return

            # ========== Handle Image ==========
            # DEBUG: Print attributes
            if hasattr(event.message, 'message_type'):
                msg_type = event.message.message_type
            elif hasattr(event.message, 'msg_type'):
                msg_type = event.message.msg_type
            else:
                print(f"DEBUG: Message attributes: {dir(event.message)}")
                msg_type = "unknown"

            # print(f"DEBUG: Detected msg_type='{msg_type}'")
            # print(f"DEBUG: Raw Content: {event.message.content}")

            # Handle pure image message
            if msg_type == "image":
                self._handle_image_message(data)
                return
            
            # Handle 'post' (rich text) that may contain images
            if msg_type == "post":
                content_json = json.loads(event.message.content)
                # Extract image_key from post content
                image_key = None
                caption_text = ""
                for block in content_json.get("content", []):
                    for item in block:
                        if item.get("tag") == "img":
                            image_key = item.get("image_key")
                        elif item.get("tag") == "text":
                            caption_text += item.get("text", "")
                
                if image_key:
                    self._handle_image_message(data, caption_text.strip(), image_key)
                    return

            # ========== Extract Content (If not already handled) ==========
            # content_json and user_text already extracted above
            if not user_text and not msg_type == "image" and not msg_type == "post":
                 # Try re-parsing if earlier parse failed? No, just empty
                 pass
            
            # (Group filter moved up)


            print(f"📩 Processing [{message_id}]: {user_text[:50] if user_text else '(empty)'}...")
            
            # ========== Empty Message ==========
            if not user_text or len(user_text.strip()) < 2:
                self._reply_text(data, "你好！有什么可以帮你的？😊")
                return
            
            # ========== Commands ==========
            if user_text.startswith("/deep"):
                self._handle_deep_analysis(data, user_text)
                return

            if user_text == "/ping":
                self._reply_text(data, "Pong! 🏓")
                return

            if user_text == "/help":
                help_text = "📚 **可用命令**\n\n• `/deep <项目名>` - 深度分析 GitHub 项目\n• `/ping` - 测试机器人是否在线\n• `/help` - 显示此帮助信息\n\n💡 **直接对话**\n你也可以直接 @我 聊天，我会回答技术问题！"
                self._reply_text(data, help_text)
                return
            
            # ========== LLM Response ==========
            # Get Chat ID for context
            chat_id = event.message.chat_id
            
            # Add user message to memory
            self.memory.add_user_message(chat_id, user_text)
            
            # Generate reply
            reply_text = self._call_llm(user_text, chat_id)
            
            # Add assistant message to memory
            self.memory.add_assistant_message(chat_id, reply_text)
            
            self._reply_text(data, reply_text)
            
        except Exception as e:
            self._reply_text(data, reply_text)
            
        except Exception as e:
            print(f"Error handling message: {e}")
            import traceback
            traceback.print_exc()

    # Original _handle_message logic is now in _process_message_worker
    # No changes needed for helper methods

    def _handle_image_message(self, data: P2ImMessageReceiveV1, caption: str = "", provided_image_key: str = None):
        """Handle image message: download and analyze."""
        try:
            event = data.event
            
            # Use provided image_key or extract from content
            if provided_image_key:
                image_key = provided_image_key
            else:
                content_json = json.loads(event.message.content)
                image_key = content_json.get("image_key")
            
            if not image_key:
                self._reply_text(data, "❌ 无法获取图片信息")
                return
            
            # Get message_id for download API
            message_id = event.message.message_id
                
            self._reply_text(data, "👁️ 正在分析图片，请稍候...")
            
            # Download image
            import base64
            image_bytes = self._download_image(message_id, image_key)
            if not image_bytes:
                self._reply_text(data, "❌ 图片下载失败，请检查机器人权限 (需要 im:resource:read)")
                return
                
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # Call Vision LLM
            reply_text = self.analyzer.analyze_image(caption, image_base64)
            self._reply_text(data, reply_text)
            
        except Exception as e:
            print(f"❌ Error handling image: {e}")
            self._reply_text(data, f"❌ 图片处理出错: {str(e)}")

    def _download_image(self, message_id: str, image_key: str) -> Optional[bytes]:
        """Download image via Feishu API."""
        try:
            # Correct API: /im/v1/messages/:message_id/resources/:file_key
            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{image_key}"
            params = {"type": "image"}
            
            import httpx
            token = self._get_tenant_access_token()
            if not token:
                print("❌ Failed to get tenant access token")
                return None
                
            headers = {"Authorization": f"Bearer {token}"}
            resp = httpx.get(url, headers=headers, params=params)
            
            if resp.status_code == 200:
                return resp.content
            else:
                print(f"❌ Failed to download image: {resp.status_code} {resp.text}")
                return None
        except Exception as e:
            print(f"❌ Image download exception: {e}")
            return None
    
    def _get_tenant_access_token(self) -> Optional[str]:
        """Get tenant access token manually."""
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            payload = {
                "app_id": self.feishu_config.app_id,
                "app_secret": self.feishu_config.app_secret
            }
            import httpx
            resp = httpx.post(url, json=payload)
            data = resp.json()
            
            if data.get("code") == 0:
                return data.get("tenant_access_token")
            else:
                print(f"❌ Failed to get tenant token: {data}")
                return None
        except Exception as e:
            print(f"❌ Error getting tenant token: {e}")
            return None

    def _handle_deep_analysis(self, data: P2ImMessageReceiveV1, user_text: str):
        """Handle /deep command."""
        # Extract repo name
        parts = user_text.split()
        if len(parts) < 2:
            self._reply_text(data, "请提供仓库名称，例如：`/deep microsoft/agent-lightning`")
            return
        
        repo_name = parts[1].strip()
        
        
        # Smart Search Logic
        if "/" not in repo_name:
            self._reply_text(data, f"🔍 正在全网搜索最匹配 `{repo_name}` 的项目...")
            project = self.github_collector.search_repository(repo_name)
            
            if not project:
                self._reply_text(data, f"❌ 未找到与 `{repo_name}` 相关的热门项目，请尝试提供完整名称 (owner/repo)。")
                return
                
            self._reply_text(data, f"🎯 找到最匹配的项目：[{project.name}]({project.url})\n⭐ Stars: {project.stars:,}\n\n正在进行深度分析...")
        else:
            # Direct fetch
            self._reply_text(data, f"🔍 正在深度挖掘 {repo_name}，请稍候（预计耗时 15 秒）...")
            project = self.github_collector.fetch_project(repo_name)
            
        if not project:
            self._reply_text(data, f"❌ 未找到仓库 {repo_name}。\n\n可能原因：\n• 仓库名拼写错误\n• 仓库是私有的\n• GitHub API 限流（稍后重试）")
            return
            
        # 2. Call LLM for Deep Analysis
        try:
            prompt = f"""{self.DEEP_ANALYSIS_PROMPT.format(name=project.name)}

项目地址：{project.url}
Stars: {project.stars}
语言: {project.language}
描述: {project.description}

README 片段 (前 3000 字):
---
{project.readme_content or '无'}
---
"""
            response = self.analyzer.client.chat.completions.create(
                model=self.config.analyzer.model,
                messages=[
                    {"role": "system", "content": "你是一个资深技术专家 (Principal Engineer)。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=2048,
            )
            report = response.choices[0].message.content
            
            # 3. Send Report
            self._reply_text(data, report)
            
        except Exception as e:
            self._reply_text(data, f"❌ 生成报告失败: {e}")

    def _call_llm(self, user_text: str, chat_id: str = None) -> str:
        """Call GLM-4.7 via OpenAI SDK with real-time context."""
        if not self.analyzer.client:
            return "❌ AI Analyzer not configured"
        
        # Inject current time into system context
        from datetime import datetime
        now = datetime.now()
        time_context = f"【系统信息】当前时间: {now.strftime('%Y年%m月%d日 %H:%M:%S')} (星期{['一','二','三','四','五','六','日'][now.weekday()]})"
            
        try:
            messages = [{"role": "system", "content": f"{self.SYSTEM_PROMPT}\n\n{time_context}"}]
            
            # Inject history if available
            if chat_id:
                history = self.memory.get_history(chat_id)
                # Filter out system messages if any, just to be safe (though memory shouldn't have them)
                clean_history = [msg for msg in history if msg['role'] in ('user', 'assistant')]
                # Don't include the very last user message if it's already in history (it shouldn't be, but valid check)
                # Actually memory has logic. We added current user_text to memory BEFORE calling this. 
                # So we should use history directly.
                # Wait, if we added it to memory already, 'history' contains it.
                # But we constructed 'messages' with system prompt first.
                # So we just extend messages with full history.
                messages.extend(clean_history)
            else:
                 messages.append({"role": "user", "content": user_text})

            response = self.analyzer.client.chat.completions.create(
                model=self.config.analyzer.model,
                messages=messages,
                temperature=0.7,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"LLM Error: {e}")
            return "⚠️ AI 服务暂时繁忙，请稍后重试"

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
