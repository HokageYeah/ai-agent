# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个基于 **FastAPI + LangGraph** 的全流程 AI Agent 智能体框架，包含：
- 后端：Python 3.13+, FastAPI, SQLAlchemy, LangGraph, LLM 适配器 (OpenAI/Anthropic)
- 前端：Vue 3 + TypeScript + Vite + Element Plus + Pinia
- 数据库：MySQL + Alembic 迁移

## 开发命令

```bash
# 后端启动 (项目根目录)
python run_app.py
# 或
poetry run uvicorn app.main:app --reload --port 8002

# 前端启动
cd web && npm run dev

# 测试
pytest

# 数据库迁移
alembic upgrade head
alembic revision --autogenerate -m "描述"
```

## 架构分层

```
app/
├── api/endpoints/     # REST API 端点 (chat, agents, skills, workflows, tools)
├── services/          # 业务服务层 (ChatService, AutomationService)
├── agents/            # Agent 引擎核心
│   ├── planning.py    # 规划引擎
│   ├── execution.py   # 执行引擎
│   ├── reflection.py  # 反思/纠错引擎
│   ├── langgraph_executor.py  # LangGraph 状态机调度
│   └── library/       # 预置 Agent 配置
├── llm_hub/           # LLM 适配层
│   ├── providers/     # OpenAI/Anthropic 适配
│   ├── inference.py   # 流式推理封装
│   └── tool_gateway.py
├── tools/             # 底层工具库 (search, http, database, calculator...)
├── skills/            # 高级技能库 (prompt-based)
├── workflows/         # 工作流引擎
├── channels/          # 多渠道适配层
├── memory/            # 短期记忆管理
├── db/                # SQLAlchemy 连接器
└── main.py            # FastAPI 入口
```

## Agent 执行流程

1. API 接收请求 → `agents.py` 端点
2. 路由到 `LangGraphAgentExecutor`
3. 依次经过：`Planning` → `Execution` → `Reflection`
4. 反思失败时触发重规划，携带 error_context
5. 工具调用通过 `ToolGateway` 白名单过滤

## 关键约定

- **语言**：代码英文标识符，注释/文档简体中文
- **后端**：FastAPI + Pydantic 类型校验 + Loguru 日志
- **前端**：Vue 3 Composition API + TypeScript + Pinia
- **数据库**：SQLAlchemy ORM + Alembic 迁移
- **Agent 工具**：白名单过滤机制，只传递授权工具 Schema

## 环境配置

环境变量在 `.env` 文件中配置，参考 `.env.example`。

## 内置 Demo

项目内置客服 Agent (cs_master) + 订单 Agent (order_agent) + 退款 Agent (refund_agent)，启动时自动注入测试订单数据 (1001-1010)。
