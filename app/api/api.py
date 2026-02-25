from fastapi import APIRouter

from app.api.endpoints import wx_public, test_api, chat, agents, workflows, skills, tools, automation

api_router = APIRouter()

# 微信公众号相关接口
api_router.include_router(wx_public.router, prefix="/wx/public", tags=["微信公众号"])

# 测试接口
api_router.include_router(test_api.router, prefix="/test", tags=["引入库测试接口"])

# AI Agent 系统接口
api_router.include_router(chat.router, tags=["对话服务"])
api_router.include_router(agents.router, tags=["Agent 系统"])
api_router.include_router(workflows.router, tags=["工作流系统"])
api_router.include_router(skills.router, tags=["技能系统"])
api_router.include_router(tools.router, tags=["工具系统"])
api_router.include_router(automation.router, prefix="/automation", tags=["自动化服务"])
