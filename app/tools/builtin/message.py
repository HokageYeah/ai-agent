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

from typing import Any, Dict, Optional, Callable, List
import asyncio
import uuid
import time
from colorama import Fore, Style
from loguru import logger

from app.tools.base import Tool, ToolSchema


async def send_agent_message(
    stream_callback: Optional[Callable],
    message_type: str,
    content: str,
    importance: str = "normal",
    required_fields: Optional[List[Dict[str, Any]]] = None,
    confirm_action: Optional[str] = None,
    options: Optional[List[Dict[str, Any]]] = None,
    allow_multiple: bool = False,
    progress: Optional[Dict[str, Any]] = None,
    extra_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    通用消息发送辅助函数，可被框架其他部分直接调用。
    
    Args:
        stream_callback: SSE 流回调
        message_type: 消息类型 (info/input/confirm/select/progress)
        content: 消息内容
        importance: 重要程度
        required_fields: 输入类型所需的字段配置
        confirm_action: 确认类型的操作描述
        options: 选择类型的选项列表
        allow_multiple: 是否多选
        progress: 进度类型的进度数据
        extra_data: 附加的自定义数据，将合并到事件的 data 字段中
        
    Returns:
        str: message_id (用于后续关联待决事件)
    """
    if not stream_callback:
        logger.debug(f"{Fore.YELLOW}[MessageHelper] 未配置流式回调，放弃发送消息{Style.RESET_ALL}")
        return ""
        
    message_id = str(uuid.uuid4())
    
    message_data: Dict[str, Any] = {
        "message_id": message_id,
        "message_type": message_type,
        "content": content,
        "importance": importance,
    }
    
    # NOTE: 关键修复 —— 将 message_id 按各消息类型分别嵌入对应的 ID 字段。
    #   前端 TrajectoryPanel 的按钮读取 node.event?.data?.confirm_id 和
    #   node.event?.data?.input_request_id，而不是 message_id。
    #   如果这里不写入，前端按钮调用 API 时 ID 为 undefined → 404 → 操作无效。
    if message_type == "confirm":
        # confirm 类型：写入 confirm_id，与 /agents/confirm/{confirm_id} 接口对应
        message_data["confirm_id"] = message_id
    elif message_type in ("input", "select"):
        # input/select 类型：写入 input_request_id，与 /agents/input/{input_request_id} 接口对应
        message_data["input_request_id"] = message_id

    if required_fields and message_type in ("input", "select"):
        message_data["required_fields"] = required_fields
    
    if confirm_action and message_type == "confirm":
        message_data["confirm_action"] = confirm_action
        
    if options and message_type == "select":
        message_data["options"] = options
        message_data["allow_multiple"] = allow_multiple
        
    if progress and message_type == "progress":
        message_data["progress"] = progress

    if extra_data:
        message_data.update(extra_data)

    event_data = {
        "event": "agent_message",
        "timestamp": time.time() * 1000,
        "data": message_data
    }
    
    try:
        if asyncio.iscoroutinefunction(stream_callback):
            await stream_callback(event_data)
        else:
            stream_callback(event_data)
    except Exception as e:
        logger.warning(f"{Fore.YELLOW}[MessageHelper] 发送通用消息失败: {e}{Style.RESET_ALL}")
        
    return message_id


class MessageAgentTool(Tool):
    """
    消息发送工具

    允许 Agent 在执行任务的过程中主动向用户发起消息沟通。
    支持通知、请求输入、请求确认、请求选择等多种模式，执行引擎会根据消息类型自动挂起并等待用户反馈。

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
            "向用户发送实时消息，可用于反馈进度，或在执行过程中请求用户输入必要信息、确认操作等。"
        )
        self._stream_callback = stream_callback
        
        # 这些字典由执行引擎在运行时注入
        self._pending_confirmations: Optional[Dict[str, Any]] = None
        self._pending_user_inputs: Optional[Dict[str, Any]] = None

        logger.info(
            f"{Fore.CYAN}[MessageAgentTool] 初始化完成 "
            f"| 流式回调={'已注入' if stream_callback else '未注入'}{Style.RESET_ALL}"
        )

    def update_context(self, 
                       stream_callback: Optional[Callable] = None,
                       pending_confirmations: Optional[Dict[str, Any]] = None,
                       pending_user_inputs: Optional[Dict[str, Any]] = None,
                       **kwargs) -> None:
        """
        更新运行时上下文

        在 Agent 每次执行任务前由执行引擎调用，注入当前会话的流式回调和挂起字典。

        Args:
            stream_callback: 当前任务的 SSE 流式回调函数
            pending_confirmations: 等待用户确认的操作字典映射
            pending_user_inputs: 等待用户输入的字典映射
        """
        if stream_callback is not None:
            self._stream_callback = stream_callback
        if pending_confirmations is not None:
            self._pending_confirmations = pending_confirmations
        if pending_user_inputs is not None:
            self._pending_user_inputs = pending_user_inputs
            
        logger.debug(f"{Fore.BLUE}[MessageAgentTool] 运行时上下文已更新{Style.RESET_ALL}")

    @property
    def name(self) -> str:
        """获取工具名称"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema

        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "message_type": {
                        "type": "string",
                        "enum": ["info", "input", "confirm", "select", "progress"],
                        "description": "消息的交互类型：info纯信息展示, input请求用户输入, confirm请求确认, select请求选择, progress进度展示"
                    },
                    "content": {
                        "type": "string",
                        "description": "消息的正文内容，支持 Markdown 格式"
                    },
                    "importance": {
                        "type": "string",
                        "enum": ["low", "normal", "high"],
                        "default": "normal",
                        "description": "消息的重要性等级"
                    },
                    "required_fields": {
                        "type": "array",
                        "description": "当 message_type 为 input 时，定义需要用户输入的字段集合",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "字段唯一标识名"},
                                "label": {"type": "string", "description": "前端显示的字段标签"},
                                "type": {
                                    "type": "string", 
                                    "enum": ["text", "number", "email", "password", "textarea"]
                                },
                                "placeholder": {"type": "string"},
                                "default": {"type": "string"},
                                "required": {"type": "boolean", "default": True},
                                "secret": {"type": "boolean", "default": False}
                            },
                            "required": ["name", "label", "type"]
                        }
                    },
                    "confirm_action": {
                        "type": "string",
                        "description": "当 message_type 为 confirm 时，描述需要确认的具体操作（如 '删除文件'）"
                    },
                    "options": {
                        "type": "array",
                        "description": "当 message_type 为 select 时，提供的选项列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "选项的唯一ID"},
                                "label": {"type": "string", "description": "展示文本"},
                                "description": {"type": "string", "description": "详情补充说明"}
                            },
                            "required": ["id", "label"]
                        }
                    },
                    "allow_multiple": {
                        "type": "boolean",
                        "default": False,
                        "description": "当 message_type 为 select 时，是否允许多选"
                    },
                    "progress": {
                        "type": "object",
                        "description": "当 message_type 为 progress 时使用的进度对象",
                        "properties": {
                            "current": {"type": "integer"},
                            "total": {"type": "integer"},
                            "stage": {"type": "string", "description": "当前阶段说明"}
                        }
                    }
                },
                "required": ["message_type", "content"],
                "additionalProperties": False
            }
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行发送消息操作

        等待用户反馈的逻辑：
        如果在发送后，message_type 为 input/confirm/select，
        则通过 asyncio.Event 将执行挂起，直到后端对应的 API 接口触发事件的 set 操作，
        再收集结果返回给 LLM。

        Args:
            params: 消息参数字典

        Returns:
            Dict[str, Any]: 包含 success 和结果描述的字典
        """
        message_type = str(params.get("message_type", "info"))
        content = str(params.get("content", "")).strip()
        importance = str(params.get("importance", "normal"))
        required_fields = params.get("required_fields")
        confirm_action = params.get("confirm_action")
        options = params.get("options")
        allow_multiple = bool(params.get("allow_multiple", False))
        progress = params.get("progress")

        if not content:
            return {"success": False, "error": "消息内容不能为空"}
            
        if not self._stream_callback:
            return {"success": False, "error": "工具未配置流式回调环境，消息无法到达终端"}
            
        logger.info(
            f"{Fore.CYAN}[MessageAgentTool] 尝试发送消息 "
            f"| 类型={message_type} | 长度={len(content)}{Style.RESET_ALL}"
        )

        try:
            # 1. 发送消息到前端并获取分配的 ID
            message_id = await send_agent_message(
                stream_callback=self._stream_callback,
                message_type=message_type,
                content=content,
                importance=importance,
                required_fields=required_fields,
                confirm_action=confirm_action,
                options=options,
                allow_multiple=allow_multiple,
                progress=progress
            )
            
            # 2. 如果不需要挂起等待，直接返回成功
            if message_type in ("info", "progress"):
                return {
                    "success": True,
                    "message": "通知已送达",
                    "feedback": None
                }
                
            # 3. 如果需要等待用户反馈，建立挂起机制
            # 由于之前通过 message_id 下发给前端，这里我们期望前端带着 message_id 请求相应的 input/confirm API。
            # 这里重用现有的 pending_user_inputs 和 pending_confirmations 机制：
            # 如果是 confirm，放入 pending_confirmations；其他类型的输入我们都复用 pending_user_inputs 接口提交。
            
            wait_event = asyncio.Event()
            
            if message_type == "confirm":
                pending_conf_dict = self._pending_confirmations
                if pending_conf_dict is None:
                    return {"success": False, "error": "本工具目前所在的执行上下文中不支持挂起等待确认"}
                
                pending_conf: Dict[str, Any] = pending_conf_dict
                
                # 为了与原来的 confirm 接口兼容，我们这里使用相同的结构
                pending_conf[message_id] = {
                    "event": wait_event,
                    "action": None
                }
                
                try:
                    logger.info(f"{Fore.YELLOW}[MessageAgentTool] 工具挂起，等待用户确认 (confirm_id={message_id})...{Style.RESET_ALL}")
                    await asyncio.wait_for(wait_event.wait(), timeout=300)
                    action = pending_conf[message_id].get("action", "reject")
                    return {
                        "success": True,
                        "feedback": action,
                        "message": f"用户已反馈确认决定: {action}"
                    }
                except asyncio.TimeoutError:
                    return {"success": False, "error": "等待用户反馈超时(300秒)"}
                finally:
                    pending_conf.pop(message_id, None)
                    
            elif message_type in ("input", "select"):
                pending_inputs_dict = self._pending_user_inputs
                if pending_inputs_dict is None:
                    return {"success": False, "error": "本工具目前所在的执行上下文中不支持挂起等待用户输入/选择"}
                    
                pending_inputs: Dict[str, Any] = pending_inputs_dict
                    
                pending_inputs[message_id] = {
                    "event": wait_event,
                    "inputs": None
                }
                
                try:
                    logger.info(f"{Fore.YELLOW}[MessageAgentTool] 工具挂起，等待用户输入/选择 (input_request_id={message_id})...{Style.RESET_ALL}")
                    await asyncio.wait_for(wait_event.wait(), timeout=300)
                    user_inputs = pending_inputs[message_id].get("inputs", {})
                    return {
                        "success": True,
                        "feedback": user_inputs,
                        "message": "用户已提交相应的输入/选择"
                    }
                except asyncio.TimeoutError:
                    return {"success": False, "error": "等待用户反馈超时(300秒)"}
                finally:
                    pending_inputs.pop(message_id, None)
                    
            return {"success": False, "error": f"不支持的 message_type: {message_type}"}
                    
        except Exception as e:
            logger.exception(f"{Fore.RED}[MessageAgentTool] 发送消息或等待反馈时发生异常: {e}{Style.RESET_ALL}")
            return {"success": False, "error": f"发生异常: {str(e)}"}

