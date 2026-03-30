from abc import ABC, abstractmethod
from typing import Dict, Any, Type
from pydantic import BaseModel, Field


class ToolSchema(BaseModel):
    """工具 Schema 定义"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    parameters: Dict[str, Any] = Field(..., description="参数 Schema (JSON Schema)")


class Tool(ABC):
    """
    工具抽象基类

    ## planning_safe 语义说明
    ─────────────────────────────────────────────────────────────────────────
    `planning_safe = True`  （默认）
        只读型探查工具，调用后不会改变系统外部状态（文件、网络写入、进程）。
        Planning 阶段的 LLM tool-calling loop 允许调用此类工具来主动搜集信息，
        例如：search、http_request、file_read、list_dir、calculator、datetime。

    `planning_safe = False`
        有副作用的执行型工具，调用会改变外部状态（写文件、安装包、执行命令等）。
        Planning 阶段禁止调用此类工具——它们应当由 Execution Node 统一调度执行，
        这样 Reflection 引擎才能完整观察到执行结果并做出正确评估。
        如果允许此类工具在 Planning 阶段被调用，则会产生以下问题：
        1. 副作用已发生，但 run_memory 的执行记忆里没有相应记录；
        2. Reflection 看不到这部分历史，误判任务未完成，触发多余的重规划；
        3. 导致同一副作用（如 skill_install）被重复调用。
    ─────────────────────────────────────────────────────────────────────────
    子类若有副作用，必须覆盖类变量：`planning_safe: bool = False`
    """

    # 默认安全（只读），有副作用的子类必须覆盖为 False
    planning_safe: bool = True

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """获取工具 Schema"""
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Any:
        """
        执行工具

        Args:
            params: 工具参数字典

        Returns:
            Any: 执行结果
        """
        pass
