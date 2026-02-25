"""
Automation API Endpoints (自动化服务接口)
================================

本模块提供自动化服务相关的 REST API 端点。

消息流向（遵循分层架构）：
    前端 HTTP 请求
      ↓
    RESTAPIAdapter（渠道层：标准化消息格式）
      ↓
    ChannelManager.route_message(service_type="automation")
      ↓
    AutomationService（应用层）
      ↓
    ToolHub / SkillManager / LLM Hub（能力层与统一推理）
      ↓
    响应返回

包含的具体端点：
  1. POST /data-processing    - 数据处理自动化
  2. POST /report-generation  - 报告生成自动化
  3. POST /code-generation    - 代码生成自动化

作者: AI Agent Team
创建时间: 2026-02-25
"""

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger
from colorama import Fore, Style

from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.schemas.automation_data import (
    DataProcessingRequest,
    ReportGenerationRequest,
    CodeGenerationRequest,
    get_automation_services,
    AutomationServiceInfo
)
from app.services.automation_service import AutomationService
from app.utils.dependencies import get_automation_service

# 创建路由器
router = APIRouter()

# ── API 路由 ───────────────────────────────────────────────────────

@router.get("/services")
async def list_automation_services() -> ApiResponseData:
    """
    获取自动化服务列表（含参数元数据）
    
    返回所有自动化服务及其参数说明、示例等信息，供前端渲染表单和示例。
    """
    logger.info(f"{Fore.CYAN}【自动化接口】获取服务列表{Style.RESET_ALL}")
    
    try:
        services = get_automation_services()
        logger.info(f"{Fore.GREEN}【自动化接口】服务列表获取成功，共 {len(services)} 个服务{Style.RESET_ALL}")
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/automation/services",
            data=[service.model_dump() for service in services],
            ret=["success"],
            v=1
        )
        
    except Exception as e:
        logger.error(f"{Fore.RED}【自动化接口】获取服务列表失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"获取服务列表失败: {str(e)}")

@router.post("/data-processing")
async def data_processing(
    request: DataProcessingRequest,
    automation_service: AutomationService = Depends(get_automation_service)
) -> ApiResponseData:
    """数据处理端点（经 Channel Layer）"""
    logger.info(f"{Fore.CYAN}【自动化接口】接收到数据处理请求{Style.RESET_ALL}")

    try:
        from app.channels.manager import get_channel_manager
        channel_manager = get_channel_manager()

        if channel_manager.get_adapter("rest_api") is not None:
            # 构建渠道层原始消息
            raw_message = {
                "user_id": "api_user",
                "content": str(request.data),  # 数据可能非字符串，转成字符串传递
                "metadata": {
                    "service_type": "automation",
                    "automation_type": "data_processing",
                    "processing_config": request.processing_config
                }
            }
            result = await channel_manager.route_message("rest_api", raw_message)
        else:
            # 降级模式
            logger.info(
                f"{Fore.YELLOW}【自动化接口】Channel Layer 未就绪，"
                f"降级为直接调用 AutomationService{Style.RESET_ALL}"
            )
            result = await automation_service.data_processing(
                data=request.data,
                processing_config=request.processing_config
            )

        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/automation/data-processing",
            data=result,
            ret=["success"],
            v=1
        )

    except Exception as e:
        logger.error(f"{Fore.RED}【自动化接口】数据处理失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"数据处理失败: {str(e)}")


@router.post("/report-generation")
async def report_generation(
    request: ReportGenerationRequest,
    automation_service: AutomationService = Depends(get_automation_service)
) -> ApiResponseData:
    """报告生成端点（经 Channel Layer）"""
    logger.info(f"{Fore.CYAN}【自动化接口】接收到报告生成请求{Style.RESET_ALL}")

    try:
        from app.channels.manager import get_channel_manager
        channel_manager = get_channel_manager()

        if channel_manager.get_adapter("rest_api") is not None:
            raw_message = {
                "user_id": "api_user",
                "content": request.data_source,
                "metadata": {
                    "service_type": "automation",
                    "automation_type": "report_generation",
                    "template": request.template,
                    "report_config": request.report_config
                }
            }
            result = await channel_manager.route_message("rest_api", raw_message)
        else:
            result = await automation_service.report_generation(
                data_source=request.data_source,
                template=request.template,
                report_config=request.report_config
            )

        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/automation/report-generation",
            data=result,
            ret=["success"],
            v=1
        )

    except Exception as e:
        logger.error(f"{Fore.RED}【自动化接口】报告生成失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"报告生成失败: {str(e)}")


@router.post("/code-generation")
async def code_generation(
    request: CodeGenerationRequest,
    automation_service: AutomationService = Depends(get_automation_service)
) -> ApiResponseData:
    """代码生成端点（经 Channel Layer）"""
    logger.info(f"{Fore.CYAN}【自动化接口】接收到代码生成请求{Style.RESET_ALL}")

    try:
        from app.channels.manager import get_channel_manager
        channel_manager = get_channel_manager()

        if channel_manager.get_adapter("rest_api") is not None:
            raw_message = {
                "user_id": "api_user",
                "content": request.requirements,
                "metadata": {
                    "service_type": "automation",
                    "automation_type": "code_generation",
                    "language": request.language,
                    "framework": request.framework,
                    "code_config": request.code_config
                }
            }
            result = await channel_manager.route_message("rest_api", raw_message)
        else:
            result = await automation_service.code_generation(
                requirements=request.requirements,
                language=request.language,
                framework=request.framework,
                code_config=request.code_config
            )

        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/automation/code-generation",
            data=result,
            ret=["success"],
            v=1
        )

    except Exception as e:
        logger.error(f"{Fore.RED}【自动化接口】代码生成失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"代码生成失败: {str(e)}")
