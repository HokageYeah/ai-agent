import logging
import sys
import os
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel
from loguru import logger

from app.core.config import settings


class LoggingSettings(BaseModel):
    LOGGING_LEVEL: str = "INFO"
    LOGGERS: List[str] = [""]


logging_settings = LoggingSettings()

# NOTE: 第三方 HTTP/ASGI 库在 DEBUG 下会输出大量底层传输细节（如 callHandlers、httpcore trace），
#       会淹没业务日志且放大 429 场景下的噪音。
#       这里统一约束这些库最低为 WARNING，保留我们 app.* 的 DEBUG 可观测性。
_NOISY_THIRD_PARTY_LOGGERS: tuple[str, ...] = (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "httpx",
    "httpcore",
    "openai",
)


def setup_logging() -> None:
    """设置日志配置"""
    # 移除默认的处理器
    logger.remove()
    
    # 设置日志级别
    log_level = logging_settings.LOGGING_LEVEL if not settings.DEBUG else "DEBUG"
    
    # 创建日志目录，普通运行日志目录
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs", "app_run")
    os.makedirs(log_dir, exist_ok=True)
    
    # 创建日志文件名（按日期区分）
    log_filename = os.path.join(log_dir, f"app_run_{datetime.now().strftime('%Y-%m-%d')}.log")
    
    # 添加控制台处理器，使用彩色输出, 去除error级别日志
    logger.add(
        sink=sys.stderr,  # 使用 stderr 而不是 stdout 可以避免一些缓冲问题
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True,
        enqueue=True,  # 启用队列模式，避免多线程/多进程问题
        diagnose=True,  # 启用诊断信息（异常堆栈等）
    )
    
    # 添加文件日志处理器 主日志（排除 ERROR 及以上）
    logger.add(
        sink=log_filename,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level=log_level,  # 设置基础级别为 INFO
        filter=lambda record: record["level"].no < 40,  # 40=ERROR级别数值 过滤掉ERROR级别及以上的日志
        rotation="00:00",  # 每天午夜轮换日志文件
        retention="30 days",  # 保留30天的日志
        compression="zip",  # 压缩旧日志
        encoding="utf-8",
        enqueue=True,  # 启用队列模式，避免多线程/多进程问题
        diagnose=True,  # 启用诊断信息（异常堆栈等）
    )
    
    # 创建错误日志目录
    error_log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs", "app_error")
    os.makedirs(error_log_dir, exist_ok=True)

    # 添加错误日志文件处理器，专门记录错误级别及以上的日志 错误日志（仅 ERROR 及以上）
    error_log_filename = os.path.join(error_log_dir, f"app_error_{datetime.now().strftime('%Y-%m-%d')}.log")
    logger.add(
        sink=error_log_filename,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="ERROR",  # 只记录 ERROR 级别及以上的日志
        rotation="00:00",  # 每天午夜轮换日志文件
        retention="90 days",  # 保留90天的日志
        compression="zip",  # 压缩旧日志
        encoding="utf-8",
        enqueue=True,
        diagnose=True,
    )
    
    # 拦截标准库的日志
    # 这样通过 logging 模块记录的日志也会被 loguru 处理
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            # 第三方噪音降噪：丢弃低于 WARNING 的底层传输日志
            if (
                record.levelno < logging.WARNING
                and any(
                    record.name == noisy or record.name.startswith(f"{noisy}.")
                    for noisy in _NOISY_THIRD_PARTY_LOGGERS
                )
            ):
                return

            # 获取对应的 loguru 级别
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            
            # 找到调用者的信息
            frame, depth = logging.currentframe(), 2
            while frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            
            # 使用 loguru 记录日志
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )
    
    # 配置标准库日志处理器
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # 替换所有已存在的日志处理器
    for name in logging.root.manager.loggerDict.keys():
        current_logger = logging.getLogger(name)
        current_logger.handlers = []
        current_logger.propagate = True
        # NOTE: 仅抑制第三方库的低级别噪音，不影响 app.* 自身 DEBUG 日志。
        if any(name == noisy or name.startswith(f"{noisy}.") for noisy in _NOISY_THIRD_PARTY_LOGGERS):
            current_logger.setLevel(logging.WARNING)

    # 再次确保关键第三方父 logger 已被抬升到 WARNING。
    for module in _NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(module).setLevel(logging.WARNING)
    
    # 日志初始化完成信息
    logger.info("日志系统初始化完成 - 使用 loguru（第三方HTTP日志已降噪）")


# 提供与标准日志库兼容的接口
def get_logger(name=None):
    """获取命名的日志记录器"""
    return logger.bind(name=name)
