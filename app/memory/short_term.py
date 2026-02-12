from typing import Dict, List, Any
import copy

class ShortTermMemory:
    """短期记忆（会话上下文）管理"""
    
    def __init__(self, max_messages: int = 10):
        """
        初始化
        
        Args:
            max_messages: 每个会话保留的最大消息数
        """
        self.max_messages = max_messages
        self.sessions: Dict[str, List[Dict[str, Any]]] = {}
    
    def add_message(self, conversation_id: str, message: Dict[str, Any]):
        """
        添加消息到会话
        
        Args:
            conversation_id: 会话 ID
            message: 消息对象
        """
        if conversation_id not in self.sessions:
            self.sessions[conversation_id] = []
        
        # 复制消息以避免引用问题
        self.sessions[conversation_id].append(copy.deepcopy(message))
        
        # 保持窗口大小
        if len(self.sessions[conversation_id]) > self.max_messages:
            self.sessions[conversation_id] = \
                self.sessions[conversation_id][-self.max_messages:]
    
    def get_context(self, conversation_id: str) -> List[Dict[str, Any]]:
        """
        获取会话上下文
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            List[Dict]: 消息列表副本
        """
        return copy.deepcopy(self.sessions.get(conversation_id, []))
    
    def clear(self, conversation_id: str):
        """
        清空会话
        
        Args:
            conversation_id: 会话 ID
        """
        if conversation_id in self.sessions:
            self.sessions[conversation_id] = []
