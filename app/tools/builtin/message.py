"""
消息发送工具模块 (Message Tool Module)

本模块实现了 MessageAgentTool 类，允许 LLM 在执行过程中向用户发送实时消息。
这在执行耗时较长的任务时非常有用，可以用来反馈进度或发送中间状态。

功能特点：
1. 实时反馈：通过 stream_callback 发送消息，前端可以立即显示。
2. 异步支持：适配本项目的异步执行引擎。
3. 结构化日志：使用 colorama 提供清晰的调试日志。

参考来源：
- 参考并移植 app/tools/example/message.py 的核心设计思维。
- 适配本项目的 Tool 架构。
"""

from typing import Any, Dict, Optional, Callable
from colorama import Fore, Style
from loguru import logger

from app.tools.base import Tool, ToolSchema


class MessageAgentTool(Tool):
    """
    消息发送工具

    允许 Agent 在执行任务的过程中主动向用户发起消息沟通。
    在复杂的长任务（例如：规划、搜索、写入文件等多步操作）中，
    可以使用此工具告知用户当前正在进行的具体子任务。

    属性：
        name: 工具名称，固定为 "send_message"
        description: 工具描述
    """

    def __init__(self, stream_callback: Optional[Callable] = None):
        """
        初始化消息发送工具

        Args:
            stream_callback: 用于发送实时事件的回调函数。
                             通常在 LangGraphAgentExecutor 执行时动态注入。
        """
        self._name = "send_message"
        self._description = (
            "向用户发送一条实时消息。适用于在长耗时任务中反馈进度，"
            "或在完成最终任务前与用户进行必要的中间沟通。"
        )
        self._stream_callback = stream_callback

        logger.info(
            f"{Fore.CYAN}[MessageAgentTool] 初始化完成 "
            f"| 流式回调={'已注入' if stream_callback else '未注入'}{Style.RESET_ALL}"
        )

    def update_context(self, stream_callback: Optional[Callable] = None) -> None:
        """
        更新运行时上下文

        在 Agent 每次执行任务前由执行引擎调用，注入当前会话的流式回调。

        Args:
            stream_callback: 当前任务的 SSE 流式回调函数
        """
        if stream_callback is not None:
            self._stream_callback = stream_callback
            logger.debug(f"{Fore.BLUE}[MessageAgentTool] 流式回调已更新{Style.RESET_ALL}")

    @property
    def name(self) -> str:
        """获取工具名称"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema

        参数：
        - content: 消息内容（必需）
        - importance: 消息重要性 (low/normal/high)

        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要发送给用户的信息内容，支持 Markdown 格式"
                    },
                    "importance": {
                        "type": "string",
                        "enum": ["low", "normal", "high"],
                        "default": "normal",
                        "description": "消息的重要性等级"
                    }
                },
                "required": ["content"],
                "additionalProperties": False
            }
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行发送消息操作

        工作流程：
        1. 提取 content 和 importance 参数。
        2. 检查流式回调是否存在。
        3. 构造子 Agent/中间过程消息事件并发送。
        4. 返回执行结果状态。

        Args:
            params: 包含 content 的参数字典

        Returns:
            Dict[str, Any]: 包含 success 和结果描述的字典
        """
        content = params.get("content", "").strip()
        importance = params.get("importance", "normal")

        if not content:
            logger.warning(f"{Fore.YELLOW}[MessageAgentTool] 消息内容为空，拒绝发送{Style.RESET_ALL}")
            return {"success": False, "error": "消息内容不能为空"}

        logger.info(
            f"{Fore.CYAN}[MessageAgentTool] 尝试发送消息 "
            f"| 长度={len(content)} "
            f"| 等级={importance}{Style.RESET_ALL}"
        )

        if not self._stream_callback:
            logger.error(f"{Fore.RED}[MessageAgentTool] 未配置流式回调，无法发送消息{Style.RESET_ALL}")
            return {
                "success": False, 
                "error": "工具未配置流式回调环境，消息无法到达终端"
            }

        try:
            # 构造自定义事件给前端
            # 前端 AgentsView 可以捕获此 event 并渲染为特殊的提示消息
            import time
            event_data = {
                "event": "agent_message",
                "timestamp": time.time() * 1000,
                "data": {
                    "content": content,
                    "importance": importance
                }
            }

            import asyncio
            if asyncio.iscoroutinefunction(self._stream_callback):
                await self._stream_callback(event_data)
            else:
                self._stream_callback(event_data)

            logger.info(f"{Fore.GREEN}[MessageAgentTool] 消息已成功推送到流式频道{Style.RESET_ALL}")
            return {
                "success": True,
                "message": f"消息已发送 (等级: {importance})",
                "content": content
            }

        except Exception as e:
            logger.exception(f"{Fore.RED}[MessageAgentTool] 发送消息时发生异常: {e}{Style.RESET_ALL}")
            return {"success": False, "error": f"发送失败: {str(e)}"}
