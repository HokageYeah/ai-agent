# Agent Library Package
"""
Agent Library
============

预定义的 Agent 集合，包含常见的业务场景 Agent。

作者: AI Agent Team
创建时间: 2026-02-15
"""

from app.agents.library.customer_service import (
    CUSTOMER_SERVICE_MASTER,
    ORDER_AGENT,
    REFUND_AGENT
)

__all__ = [
    "CUSTOMER_SERVICE_MASTER",
    "ORDER_AGENT",
    "REFUND_AGENT"
]
