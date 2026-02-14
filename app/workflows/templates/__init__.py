"""
工作流模板模块

本模块包含预定义的工作流模板。

可用工作流:
- INTENT_ROUTING_WORKFLOW: 意图路由工作流
"""

from app.workflows.templates.intent_routing import INTENT_ROUTING_WORKFLOW

__all__ = [
    "INTENT_ROUTING_WORKFLOW",
]
