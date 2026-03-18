import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

from app.utils.resource_path import get_project_root

OPENAI_DEFAULT_MODEL_FALLBACK = "gpt-5.3-codex"
ANTHROPIC_DEFAULT_MODEL_FALLBACK = "claude-3-haiku-20240307"
DEFAULT_AGENT_WORKSPACE_DIR = "app/skills/skills_md"

# 获取当前环境
ENV = os.getenv("ENV", "development")
print(f"当前环境: {ENV}")
# 根据环境选择配置文件（老方法，根据文件名去拿文件配置，未使用dotenv库）以下使用dotenv库
# env_file = f".env.{ENV}" if os.path.exists(f".env.{ENV}") else ".env"
# 优先加载 .env 文件
env_file = ".env"
if ENV == "prod":
    env_file = ".env.production"
elif ENV == "test":
    env_file = ".env"
elif ENV == "dev":
    env_file = ".env.development"
print(f"加载配置文件: {env_file}")
# 清除dotenv缓存，重新加载
load_dotenv(env_file, override=True)

class Settings(BaseSettings):
    PROJECT_NAME: str = "微信公众号爬虫" # 项目名称
    PROJECT_DESCRIPTION: str = "用于爬取微信公众号资源的API" # 项目描述
    PROJECT_VERSION: str = "0.1.0" # 项目版本
    API_PREFIX: str = "/api/v1" # 接口前缀
    # DATABASE_URL: str # 数据库连接字符串 暂时不配置
    DEBUG: bool = False # 是否为调试模式
    ENVIRONMENT: str # 环境变量
    VERSION: int = 1 # 版本号

    # docker 数据库字段
    MYSQL_ROOT_PASSWORD: Optional[str] = "aa123456"
    MYSQL_DATABASE: Optional[str] = "order_agent_dev"
    MYSQL_USER: Optional[str] = "yy"
    MYSQL_PASSWORD: Optional[str] = "aa123456"


        # 数据库配置
    DB_DRIVER: Optional[str] = "mysql+mysqlconnector"
    DB_USER: Optional[str] = "root"
    DB_PASSWORD: Optional[str] = "aa123456"
    DB_HOST: Optional[str] = "localhost"
    DB_PORT: Optional[int] = 3306
    DB_NAME: Optional[str] = "order_agent_dev"
    DB_CHARSET: Optional[str] = "utf8mb4"
    DB_ECHO: Optional[bool] = True
    DB_POOL_SIZE: Optional[int] = 5
    DB_MAX_OVERFLOW: Optional[int] = 10
    DB_POOL_RECYCLE: Optional[int] = 3600
    DB_POOL_TIMEOUT: Optional[int] = 30

    # LLM 相关配置
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    DEFAULT_MODEL: Optional[str] = OPENAI_DEFAULT_MODEL_FALLBACK
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_BASE_URL: Optional[str] = None
    DEFAULT_ANTHROPIC_MODEL: Optional[str] = ANTHROPIC_DEFAULT_MODEL_FALLBACK
    AGENT_WORKSPACE_DIR: Optional[str] = DEFAULT_AGENT_WORKSPACE_DIR
    
    # 其他第三方服务配置
    N8N_WEBHOOK_URL: Optional[str] = None
    ACCESS_KEY_ID: Optional[str] = None
    ACCESS_KEY_SECRET: Optional[str] = None
    BUCKET_NAME: Optional[str] = None
    REGION: Optional[str] = None
    ENDPOINT: Optional[str] = None

    # @field_validator("DATABASE_URL")
    # def validate_database_url(cls, v: Optional[str]) -> Any:
    #     print('DATABASE_URL---', v)
    #     if not v:
    #         raise ValueError("DATABASE_URL must be provided")
    #     return v

    # NOTE: Pydantic V2 已废弃内部 Config 类，改用 model_config = ConfigDict(...)
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow"  # 允许额外字段，沿用原配置
    )


settings = Settings()


def resolve_agent_workspace_dir(raw_dir: Optional[str] = None) -> Path:
    """
    解析 Agent 工作区目录。

    设计原因：
    1. 统一收敛“技能安装目录 / 后续本地记忆目录”等工作区配置入口。
    2. 允许 .env 中填写相对路径，运行时自动相对项目根目录解析，避免受启动目录影响。
    """
    candidate = (raw_dir or settings.AGENT_WORKSPACE_DIR or DEFAULT_AGENT_WORKSPACE_DIR).strip()
    expanded = Path(os.path.expandvars(os.path.expanduser(candidate)))
    if not expanded.is_absolute():
        expanded = get_project_root() / expanded
    return expanded.resolve()


def get_agent_workspace_dir() -> Path:
    """获取当前生效的 Agent 工作区绝对路径。"""
    return resolve_agent_workspace_dir()


def get_default_model(provider: str = "openai") -> str:
    """
    统一获取项目默认模型，避免各层维护不一致的硬编码兜底值。
    """
    normalized_provider = (provider or "openai").strip().lower()
    if normalized_provider == "anthropic":
        return (settings.DEFAULT_ANTHROPIC_MODEL or ANTHROPIC_DEFAULT_MODEL_FALLBACK).strip()
    return (settings.DEFAULT_MODEL or OPENAI_DEFAULT_MODEL_FALLBACK).strip()


def infer_provider_from_model(model_name: Optional[str]) -> str:
    """
    根据模型名称推断供应商。

    当前项目主要接入两类模型：
    - `claude-*` 归类为 Anthropic
    - 其余模型默认走 OpenAI 兼容接口
    """
    normalized_model_name = (model_name or "").strip().lower()
    if normalized_model_name.startswith("claude"):
        return "anthropic"
    return "openai"
