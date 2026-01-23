"""Conversation memory management for the bot."""

import time
from collections import deque
from typing import Dict, List, Optional
from dataclasses import dataclass, field

@dataclass
class ConversationContext:
    """Holds conversation history for a specific chat."""
    history: deque
    last_updated: float = field(default_factory=time.time)
    
    def add_message(self, role: str, content: str):
        """Add a message to history."""
        self.history.append({"role": role, "content": content})
        self.last_updated = time.time()
        
    def get_messages(self) -> List[Dict[str, str]]:
        """Get messages as list."""
        return list(self.history)

class ConversationMemory:
    """In-memory conversation history manager."""
    
    def __init__(self, max_history: int = 10, ttl_seconds: int = 3600):
        self._conversations: Dict[str, ConversationContext] = {}
        self.max_history = max_history
        self.ttl_seconds = ttl_seconds
        
    def get_history(self, chat_id: str) -> List[Dict[str, str]]:
        """Get conversation history for a chat_id."""
        self._cleanup_expired()
        
        if chat_id not in self._conversations:
            return []
            
        return self._conversations[chat_id].get_messages()
        
    def add_user_message(self, chat_id: str, content: str):
        """Add a user message to history."""
        self._ensure_context(chat_id)
        self._conversations[chat_id].add_message("user", content)
        
    def add_assistant_message(self, chat_id: str, content: str):
        """Add an assistant message to history."""
        self._ensure_context(chat_id)
        self._conversations[chat_id].add_message("assistant", content)
        
    def clear(self, chat_id: str):
        """Clear history for a chat."""
        if chat_id in self._conversations:
            del self._conversations[chat_id]
            
    def _ensure_context(self, chat_id: str):
        """Ensure context exists for chat_id."""
        if chat_id not in self._conversations:
            self._conversations[chat_id] = ConversationContext(
                history=deque(maxlen=self.max_history)
            )
            
    def _cleanup_expired(self):
        """Remove expired conversations."""
        now = time.time()
        expired = [
            cid for cid, ctx in self._conversations.items() 
            if now - ctx.last_updated > self.ttl_seconds
        ]
        for cid in expired:
            del self._conversations[cid]
