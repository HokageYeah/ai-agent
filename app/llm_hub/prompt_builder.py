from typing import List, Dict, Any, Optional
from loguru import logger
from colorama import Fore, Style

class PromptBuilder:
    """
    Prompt 构建器
    负责组装 System Prompt、对话历史、用户输入，并适配不同模型的需求
    """
    
    def __init__(self):
        pass

    def build(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        context: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        构建完整 Prompt
        
        :param messages: 原始对话消息列表 [{"role": "user", "content": "..."}]
        :param system_prompt: 系统提示词（可选，如果 messages 中已有 system 则会被合并或追加）
        :param context: 上下文信息（如记忆检索结果）（可选）
        :param tools: 工具定义列表（可选，用于 function calling）
        :return: 构建后的消息列表
        """
        logger.debug(f"{Fore.BLUE}Building prompt with {len(messages)} messages{Style.RESET_ALL}")
        
        final_messages = []
        
        # 1. 处理 System Prompt
        # 如果参数传入了 system_prompt，优先作为一个单独的 System Message
        if system_prompt:
            final_messages.append({"role": "system", "content": system_prompt})
            
        # 2. 处理 Context (可选)
        # 如果有额外的上下文，可以作为 System 或 User message 的一部分插入
        if context:
            # 简单策略：将上下文作为 System message 的一部分，或者单独的消息
            context_str = "\n".join([str(c) for c in context])
            context_msg = f"Context information is below.\n---------------------\n{context_str}\n---------------------\n"
            # 插入到 system prompt 之后，或者作为第一条
            if final_messages and final_messages[0]["role"] == "system":
                final_messages[0]["content"] += f"\n\n{context_msg}"
            else:
                final_messages.insert(0, {"role": "system", "content": context_msg})

        # 3. 合并原始消息
        # 需要注意检查 messages 中是否已经包含了 system prompt，避免重复
        for msg in messages:
            if msg["role"] == "system" and system_prompt:
                # 如果已经有了 system prompt 且参数也传了，策略可以是：
                # A. 追加到现有 system prompt
                # B. 忽略参数中的 simple_prompt
                # 这里选择追加
                if final_messages and final_messages[0]["role"] == "system":
                     final_messages[0]["content"] += f"\n\n{msg['content']}"
                else:
                    final_messages.insert(0, msg)
            else:
                final_messages.append(msg)
                
        # 4. (Future) Handle Tools formatting if needed explicitly in prompt 
        # (For raw LLMs. For OpenAI/Anthropic API, tools are passed separately in API call, not in messages usually)
        
        return final_messages
