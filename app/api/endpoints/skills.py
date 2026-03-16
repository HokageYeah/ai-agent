"""
Skills API Endpoints (技能接口)
================================

本模块提供技能相关的 REST API 端点。

功能特点：
1. GET /skills - 列出所有技能
2. POST /skills/{skill_id}/execute - 执行技能

作者: AI Agent Team
创建时间: 2026-02-17
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from loguru import logger
from colorama import Fore, Style

from app.schemas.agent_data import (
    SkillExecuteRequest, SkillExecuteResponse,
    SkillInfo, SkillParamSchema
)
from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.skills.manager import SkillManager
from app.utils.dependencies import get_skill_manager
from app.llm_hub.inference import InferenceEngine
from app.tools.hub import ToolHub

# 创建路由器
router = APIRouter()


@router.get("/skills")
async def list_skills(
    skill_manager: SkillManager = Depends(get_skill_manager)
) -> ApiResponseData:
    """
    列出所有技能
    
    Args:
        skill_manager: 技能管理器
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}列出所有技能{Style.RESET_ALL}")
    
    try:
        # 获取所有技能
        skills = skill_manager.list_skills()
        
        # 构建响应
        skills_info = []
        for skill in skills:
            # NOTE: 将 Skill 模型的 param_schemas 转换为 API 层的 SkillParamSchema 格式
            # key 为参数名（对应 prompt_template 中 {key}），value 包含说明和示例
            api_param_schemas = {
                param_name: SkillParamSchema(
                    label=param_schema.label,
                    description=param_schema.description,
                    examples=param_schema.examples,
                    required=param_schema.required
                )
                for param_name, param_schema in skill.param_schemas.items()
            }
            logger.debug(
                f"{Fore.CYAN}[技能列表] {skill.skill_id} 包含 {len(api_param_schemas)} 个参数元数据{Style.RESET_ALL}"
            )
            skills_info.append(
                SkillInfo(
                    skill_id=skill.skill_id,
                    name=skill.name,
                    description=skill.description,
                    required_tools=skill.required_tools,
                    optional_tools=skill.optional_tools,
                    tags=skill.tags,
                    param_schemas=api_param_schemas
                )
            )
        
        logger.info(f"{Fore.GREEN}成功列出 {len(skills_info)} 个技能，参数元数据已携带{Style.RESET_ALL}")
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/skills",
            data=[info.model_dump() for info in skills_info],
            ret=["success"],
            v=1
        )
        
    except Exception as e:
        logger.error(f"{Fore.RED}列出技能失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"列出技能失败: {str(e)}")


@router.post("/skills/{skill_id}/execute")
async def execute_skill(
    skill_id: str,
    request: SkillExecuteRequest,
    skill_manager: SkillManager = Depends(get_skill_manager)
) -> ApiResponseData:
    """
    执行技能
    
    Args:
        skill_id: 技能 ID
        request: 执行请求
        skill_manager: 技能管理器
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}接收到技能执行请求 - Skill ID: {skill_id}{Style.RESET_ALL}")
    
    try:
        # 获取技能
        skill = skill_manager.get_skill(skill_id)
        if not skill:
            logger.error(f"{Fore.RED}技能不存在: {skill_id}{Style.RESET_ALL}")
            raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
        
        # 创建执行上下文
        # NOTE: InferenceEngine 需要 provider 和 model_registry 两个必填参数
        # 与 agents.py 和 chat.py 保持一致的初始化方式
        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.llm_hub.tool_gateway import ToolCallingGateway
        from app.core.config import settings
        
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        model_registry = ModelRegistry()
        
        # 创建工具中心并注册所有内置工具
        tool_hub = ToolHub()
        from app.tools.builtin import register_all_builtin_tools
        register_all_builtin_tools(tool_hub)
        
        # 创建工具调用网关并注册工具
        tool_gateway = ToolCallingGateway()
        # 注册工具到网关
        for tool in tool_hub.list_tools():
            tool_gateway.register_tool(
                name=tool.name,
                tool_instance=tool,
                schema=tool.schema.model_dump()
            )
        logger.info(f"{Fore.CYAN}技能执行 - 已创建 ToolCallingGateway，注册 {len(tool_hub.list_tools())} 个工具{Style.RESET_ALL}")
        
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry,
            tool_gateway=tool_gateway
        )
        logger.info(f"{Fore.CYAN}技能执行 - 已创建 InferenceEngine (带工具网关){Style.RESET_ALL}")
        
        # 获取工具定义列表（用于 LLM function calling）
        all_tools = tool_hub.get_schemas()
        logger.info(f"{Fore.CYAN}技能执行 - 已注册 {len(all_tools)} 个工具定义{Style.RESET_ALL}")

        # 与 ExecutionEngine 保持一致：优先按技能声明工具白名单过滤，降低无关工具循环
        skill_required_tools = {
            str(x).strip()
            for x in (skill.required_tools or [])
            if isinstance(x, str) and str(x).strip()
        }
        skill_optional_tools = {
            str(x).strip()
            for x in (skill.optional_tools or [])
            if isinstance(x, str) and str(x).strip()
        }
        declared_skill_tools = skill_required_tools | skill_optional_tools

        # 敏感工具不允许在技能内部隐式调用（需走 Agent 主链路确认机制）
        sensitive_tools = {"file_write"}
        filtered_tools = []
        available_tool_names = set()
        for schema in all_tools:
            tool_name = (
                schema.get("function", {}).get("name")
                if isinstance(schema, dict)
                else None
            )
            if not tool_name:
                continue
            available_tool_names.add(tool_name)
            if tool_name in sensitive_tools:
                continue
            if declared_skill_tools and tool_name not in declared_skill_tools:
                continue
            filtered_tools.append(schema)

        selected_tool_names = {
            s.get("function", {}).get("name")
            for s in filtered_tools
            if isinstance(s, dict)
        }
        missing_required = sorted(
            x for x in skill_required_tools if x not in selected_tool_names
        )
        if missing_required:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"技能 '{skill_id}' 缺失必需工具: {missing_required}。"
                    f" 当前可用工具: {sorted(available_tool_names)}"
                )
            )

        logger.info(
            f"{Fore.CYAN}技能执行 - 工具过滤完成 | skill={skill_id} | "
            f"required={sorted(skill_required_tools)} | optional={sorted(skill_optional_tools)} | "
            f"selected={[s.get('function', {}).get('name') for s in filtered_tools]}{Style.RESET_ALL}"
        )

        # 执行推理
        from app.llm_hub.inference import InferenceConfig
        config = InferenceConfig(**request.config) if request.config else InferenceConfig()
        
        # 将工具定义传入配置
        config.tools = filtered_tools
        
        # 通过 SkillManager 运行时执行入口调用技能（动态加载 + Prompt 组装）
        user_request = request.parameters.get(
            "task",
            f"请根据以下参数执行技能：{request.parameters}"
        )
        result = await skill_manager.execute_skill_runtime(
            skill_name=skill_id,
            user_request=user_request,
            inputs=request.parameters,
            llm_hub=inference_engine,
            config=config
        )
        
        logger.info(f"{Fore.GREEN}技能执行成功{Style.RESET_ALL}")
        
        # 构建响应
        response = SkillExecuteResponse(
            skill_id=skill.skill_id,
            skill_name=skill.name,
            result={"content": result.content, "usage": result.usage},
            success=True
        )
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api=f"/skills/{skill_id}/execute",
            data=response.model_dump(),
            ret=["success"],
            v=1
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{Fore.RED}技能执行失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"技能执行失败: {str(e)}")
