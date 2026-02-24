from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from app.core.config import settings
from app.core.logging import setup_logging
from app.api.api import api_router
from app.db.sqlalchemy_db import database
from fastapi.exceptions import RequestValidationError, HTTPException, ResponseValidationError
from app.middleware.exception_handlers import request_validation_error_handler, http_exception_handler, response_validation_error_handler
from app.middleware.response_validator import ResponseValidatorMiddleware
from app.schemas.common_data import ApiResponseData, PlatformEnum

# 初始化日志系统（这个是系统日志，操作复杂，设置复杂，所以先舍弃）
# setup_logging()

# 使用loguru初始化日志系统
from app.core.logging_uru import setup_logging
setup_logging()

from loguru import logger
from colorama import Fore, Style


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 应用生命周期管理器。

    startup 阶段：
    1. 连接 MySQL 数据库（SQLAlchemy）
    2. 预热 Agent 执行器（含工具注册 + SQLite 内存数据库种子数据初始化）

    shutdown 阶段：
    1. 关闭数据库连接
    """
    # ── Startup ──────────────────────────────────────────────
    logger.info(f"{Fore.CYAN}{'='*55}{Style.RESET_ALL}")
    logger.info(f"{Fore.CYAN}  AI Agent 服务启动中...{Style.RESET_ALL}")
    logger.info(f"{Fore.CYAN}{'='*55}{Style.RESET_ALL}")

    # 1. 连接 MySQL
    logger.info(f"{Fore.BLUE}[启动] 连接 MySQL 数据库...{Style.RESET_ALL}")
    database.connect()
    logger.info(f"{Fore.GREEN}[启动] MySQL 数据库连接成功{Style.RESET_ALL}")

    # 2. 预热 Agent 执行器（懒加载 → 提前初始化，确保种子数据在第一个请求前就已注入）
    logger.info(f"{Fore.BLUE}[启动] 预热 Agent 执行器（注册工具 + 初始化订单测试数据）...{Style.RESET_ALL}")
    try:
        from app.api.endpoints.agents import get_agent_executor, get_agent_registry
        get_agent_registry()   # 先确保 Agent 注册表初始化
        get_agent_executor()   # 触发工具注册 + 种子数据注入
        logger.info(f"{Fore.GREEN}[启动] Agent 执行器预热完成 ✅{Style.RESET_ALL}")
    except Exception as e:
        logger.error(f"{Fore.RED}[启动] Agent 执行器预热失败（不阻断启动）: {e}{Style.RESET_ALL}")

    logger.info(f"{Fore.GREEN}{'='*55}{Style.RESET_ALL}")
    logger.info(f"{Fore.GREEN}  AI Agent 服务启动完成，等待请求...{Style.RESET_ALL}")
    logger.info(f"{Fore.GREEN}{'='*55}{Style.RESET_ALL}")

    yield  # 服务运行中

    # ── Shutdown ─────────────────────────────────────────────
    logger.info(f"{Fore.YELLOW}[关闭] AI Agent 服务正在关闭...{Style.RESET_ALL}")
    try:
        database.close()
        logger.info(f"{Fore.YELLOW}[关闭] MySQL 数据库连接已释放{Style.RESET_ALL}")
    except Exception as e:
        logger.warning(f"{Fore.YELLOW}[关闭] 数据库关闭异常（可忽略）: {e}{Style.RESET_ALL}")
    logger.info(f"{Fore.YELLOW}[关闭] 服务已安全退出{Style.RESET_ALL}")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=settings.PROJECT_VERSION,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,          # 使用新的生命周期管理器
)

# 设置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 定义全局请求参数异常处理器exception_class : 要处理的异常类型、handler : 处理异常的函数
app.add_exception_handler(RequestValidationError, request_validation_error_handler)

# 定义全局错误处理器，单独封装成一个中间价，并且统一返回相同的格式
app.add_exception_handler(HTTPException, http_exception_handler)

# 定义全局响应格式验证异常处理器
app.add_exception_handler(ResponseValidationError, response_validation_error_handler)

# 添加响应格式验证中间件
app.add_middleware(ResponseValidatorMiddleware)


# 添加路由
app.include_router(api_router, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    return {"message": "微信公众号爬虫API"}

if __name__ == "__main__":
    import uvicorn
    logging.info("启动应用服务器...")
    uvicorn.run("app.main:app", host="localhost", port=8002, reload=True)
