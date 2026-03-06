"""
会话级任务摘要记忆系统 (Session Memory)
=====================================

本模块负责管理同一个对话会话（conversation_id）下的跨任务记忆。
每次单轮任务执行完毕后，将从 AgentRunMemory 中提取一条压缩的 TaskSummaryEntry（含结论和关键数据），
并在下一次属于该会话的任务执行前，将其作为上下文注入，帮助 LLM 了解此前的对话进展和累积的已知数据。

作者: AI Agent Team
创建时间: 2026-03-06
"""

from dataclasses import dataclass, field
import time
import uuid
import json
from loguru import logger
from colorama import Fore, Style
from typing import Dict, Any, List

from app.memory.agent_run_memory import AgentRunMemory

@dataclass
class TaskSummaryEntry:
    """一次 Agent 任务执行的压缩摘要条目"""
    task_id: str
    agent_id: str
    agent_name: str
    task: str
    success: bool
    summary: str
    key_data: dict
    tools_used: list[str]
    iterations: int
    started_at: float
    ended_at: float
    # 记录本次任务中用户的操作行为（如确认或拒绝某个工具）
    user_actions: list[dict] = field(default_factory=list)

    def to_context_message(self) -> dict:
        """
        将摘要转换为发给 LLM 的 user 消息对象
        作为后续任务启动时的前置上下文信息。
        """
        status = "✅ 成功" if self.success else "❌ 失败"
        lines = [
            f"【历史任务摘要】",
            f"任务: {self.task}",
            f"结果: {status}",
            f"结论: {self.summary}",
        ]
        
        if self.key_data:
            key_data_str = json.dumps(self.key_data, ensure_ascii=False)
            lines.append(f"关键数据: {key_data_str}")
            
        if self.tools_used:
            lines.append(f"使用工具: {', '.join(self.tools_used)}")
            
        if self.user_actions:
            action_desc = []
            for act in self.user_actions:
                tool = act.get("tool", "")
                action = act.get("action", "")
                if action == "reject":
                    action_desc.append(f"拒绝了 [{tool}] 操作")
                elif action == "confirm":
                    action_desc.append(f"确认了 [{tool}] 操作")
            if action_desc:
                lines.append(f"用户操作行为: {'; '.join(action_desc)}")
                
        lines.append(f"执行轮次: {self.iterations} 轮")
        
        return {"role": "user", "content": "\n".join(lines)}

class AgentSessionMemory:
    """会话级任务摘要仓库"""
    def __init__(self, conversation_id: str, max_entries: int = 10):
        self.conversation_id = conversation_id
        self.max_entries = max_entries
        self._entries: list[TaskSummaryEntry] = []

    def append_task_summary(self, entry: TaskSummaryEntry) -> None:
        """追加一条任务摘要，并维持最大数量限制"""
        self._entries.append(entry)
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]
            
        logger.debug(
            f"{Fore.CYAN}[会话记忆] 会话 {self.conversation_id} 新增任务摘要, "
            f"当前共 {len(self._entries)} 条{Style.RESET_ALL}"
        )

    def build_context_messages(self) -> list[dict]:
        """构建待注入到 messages 前置的列表"""
        return [entry.to_context_message() for entry in self._entries]

    def get_summary_list(self) -> list[dict]:
        """返回供调试或展示的条目列表"""
        from dataclasses import asdict
        return [asdict(e) for e in self._entries]

def extract_summary_from_run_memory(
    run_memory: AgentRunMemory, 
    final_result: Dict[str, Any]
) -> TaskSummaryEntry:
    """
    通过解析 AgentRunMemory 的内部记录，免 LLM 提取任务摘要。
    
    提取逻辑：
      - summary: 优先用最终的一条 reflection, 如果没有则用 final_result
      - key_data: 从 final_result 提取（排除常规的 success/messages 字段）
      - tools_used: 遍历消息列表找 tool_call 记录
      - user_actions: 遍历消息列表找 user_action 记录
      - iterations: 找到的最大 iteration 值
    """
    # 查找最大的迭代轮次
    iterations = 0
    tools_used = set()
    user_actions = []
    
    # 查找所有记录
    for msg in run_memory._messages:
        meta = msg.meta
        it = meta.get("iteration", 0)
        entry_type = meta.get("entry_type")
        
        if it > iterations:
            iterations = it
            
        if entry_type == "tool_call":
            if "tool_name" in meta:
                tools_used.add(meta["tool_name"])
                
        if entry_type == "skill_call":
            if "skill_id" in meta:
                tools_used.add(meta["skill_id"])
                
        if entry_type == "user_action":
            user_actions.append({
                "action": meta.get("action", ""),
                "tool": meta.get("tool_name", ""),
                "iteration": it
            })

    # 从最后一条 reflection 中提取 summary
    summary_text = ""
    # 反向遍历查找最后一个 reflection
    for msg in reversed(run_memory._messages):
        if msg.meta.get("entry_type") == "reflection":
            content = msg.content or ""
            # 简单切分获取内部的 "总结: xxx" 内容
            if "总结: " in content:
                summary_text = content.split("总结: ")[-1].split("\n")[0]
            else:
                summary_text = content
            break
            
    if not summary_text:
        summary_text = "任务执行完毕"

    success = final_result.get("success", False)
    
    # 收集 key_data，过滤掉框架返回的标准控制字段
    ignore_keys = {"success", "result", "messages", "iterations", "agent_id", "task"}
    key_data = {}
    
    # 尝试将实际的返回负载（如 final_result["result"] 或直接的外层字段）提炼
    data_source = final_result.get("result", final_result)
    if isinstance(data_source, dict):
        for k, v in data_source.items():
            if k not in ignore_keys:
                key_data[k] = v

    return TaskSummaryEntry(
        task_id=uuid.uuid4().hex,
        agent_id=run_memory.agent_id,
        agent_name=run_memory.agent_name,
        task=run_memory.task,
        success=success,
        summary=summary_text,
        key_data=key_data,
        tools_used=list(tools_used),
        user_actions=user_actions,
        iterations=iterations + 1,  # 从0开始计数的，转为实际次数
        started_at=run_memory.started_at,
        ended_at=time.time()
    )


# =============================================================================
# 全局注册表（原型单例实现）
# =============================================================================

_session_registry: Dict[str, AgentSessionMemory] = {}

def get_session_memory(conversation_id: str) -> AgentSessionMemory:
    """获取或新建会话记忆仓库"""
    if conversation_id not in _session_registry:
        _session_registry[conversation_id] = AgentSessionMemory(conversation_id)
    return _session_registry[conversation_id]

def clear_session_memory(conversation_id: str) -> None:
    """清空指定的会话记忆"""
    if conversation_id in _session_registry:
        del _session_registry[conversation_id]
        logger.info(f"{Fore.YELLOW}[会话记忆] 已清空 conversation_id={conversation_id}{Style.RESET_ALL}")
