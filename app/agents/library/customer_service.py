"""
客服系统 Agent 库（YAML 配置驱动）
================================

设计说明：
1. Agent 的定义全部放在 `app/agents/config/{agent_id}.yml` 中。
2. 本模块只负责“加载 + 校验 + 注册”，不再硬编码具体 Agent 内容。
3. 保留旧常量导出（CUSTOMER_SERVICE_MASTER 等），保证历史代码兼容。

作者: AI Agent Team
创建时间: 2026-02-15
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml
from colorama import Fore, Style
from loguru import logger
from pydantic import ValidationError

from app.agents.base import Agent

# Agent 配置目录：app/agents/config/
AGENT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# 历史内置 Agent（用于兼容旧常量导出）
_CORE_AGENT_IDS = ["cs_master", "order_agent", "refund_agent", "general_agent"]


def _iter_agent_config_files() -> List[Path]:
    """
    获取配置目录中的所有 Agent YAML 文件。

    说明：
    - 支持 `.yml` / `.yaml`
    - 统一排序，保证加载顺序稳定，便于排障和结果可复现
    """
    yml_files = sorted(AGENT_CONFIG_DIR.glob("*.yml"))
    yaml_files = sorted(AGENT_CONFIG_DIR.glob("*.yaml"))
    all_files = sorted({*yml_files, *yaml_files})
    logger.debug(
        f"{Fore.BLUE}[客服 Agent 配置加载] 发现配置文件 {len(all_files)} 个："
        f"{[p.name for p in all_files]}{Style.RESET_ALL}"
    )
    return all_files


def _parse_single_agent_config(config_path: Path) -> Agent:
    """
    解析单个 Agent 配置文件并构建 Agent 对象。

    校验规则：
    1. 文件不能为空
    2. YAML 顶层必须是对象（dict）
    3. `agent_id` 必须与文件名一致（防止拷贝文件后忘记修改 id）
    """
    logger.debug(f"{Fore.BLUE}[客服 Agent 配置加载] 开始读取: {config_path}{Style.RESET_ALL}")

    raw_text = config_path.read_text(encoding="utf-8")
    if not raw_text.strip():
        raise ValueError(f"配置文件为空: {config_path.name}")

    parsed = yaml.safe_load(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"配置文件格式错误（顶层必须是对象）: {config_path.name}")

    file_agent_id = config_path.stem
    config_agent_id = parsed.get("agent_id")

    # 若省略 agent_id，则自动回填为文件名，简化自动生成配置文件场景
    if not config_agent_id:
        parsed["agent_id"] = file_agent_id
        logger.warning(
            f"{Fore.YELLOW}[客服 Agent 配置加载] {config_path.name} 未声明 agent_id，"
            f"已自动使用文件名: {file_agent_id}{Style.RESET_ALL}"
        )
    elif config_agent_id != file_agent_id:
        raise ValueError(
            f"agent_id 与文件名不一致: file={file_agent_id}, agent_id={config_agent_id}"
        )

    try:
        # 这里直接复用 Pydantic 的强校验，保证配置结构与代码模型一致
        agent = Agent(**parsed)
    except ValidationError as exc:
        raise ValueError(f"Agent 配置校验失败: {config_path.name}, 详情: {exc}") from exc

    logger.info(
        f"{Fore.CYAN}[客服 Agent 配置加载] 解析成功: {agent.agent_id} ({agent.name}){Style.RESET_ALL}"
    )
    return agent


def load_customer_service_agents() -> Dict[str, Agent]:
    """
    从配置目录加载全部客服 Agent。

    Returns:
        Dict[str, Agent]: key=agent_id, value=Agent 实例
    """
    if not AGENT_CONFIG_DIR.exists():
        raise FileNotFoundError(f"Agent 配置目录不存在: {AGENT_CONFIG_DIR}")

    config_files = _iter_agent_config_files()
    if not config_files:
        raise RuntimeError(f"未找到任何 Agent 配置文件: {AGENT_CONFIG_DIR}")

    agent_map: Dict[str, Agent] = {}
    for config_path in config_files:
        try:
            agent = _parse_single_agent_config(config_path)
        except Exception as exc:
            logger.error(
                f"{Fore.RED}[客服 Agent 配置加载] 解析失败: {config_path.name}, 错误: {exc}{Style.RESET_ALL}"
            )
            raise

        if agent.agent_id in agent_map:
            raise ValueError(f"发现重复 agent_id: {agent.agent_id}（文件: {config_path.name}）")

        agent_map[agent.agent_id] = agent

    missing_core_agents = [agent_id for agent_id in _CORE_AGENT_IDS if agent_id not in agent_map]
    if missing_core_agents:
        raise RuntimeError(
            f"缺失核心 Agent 配置: {missing_core_agents}。"
            f"请检查目录: {AGENT_CONFIG_DIR}"
        )

    logger.info(
        f"{Fore.GREEN}[客服 Agent 配置加载] 加载完成，共 {len(agent_map)} 个 Agent："
        f"{list(agent_map.keys())}{Style.RESET_ALL}"
    )
    return agent_map


# 在模块导入时加载一次：
# 1. 启动即校验配置，尽早暴露错误；
# 2. 保持与旧实现一致（模块级常量）
_AGENT_MAP = load_customer_service_agents()

# -----------------------------------------------------------------------------
# 兼容旧接口：保留四个历史常量，避免影响既有 import 代码
# -----------------------------------------------------------------------------
CUSTOMER_SERVICE_MASTER = _AGENT_MAP["cs_master"]
ORDER_AGENT = _AGENT_MAP["order_agent"]
REFUND_AGENT = _AGENT_MAP["refund_agent"]
GENERAL_AGENT = _AGENT_MAP["general_agent"]


def get_all_customer_service_agents() -> List[Agent]:
    """
    获取所有客服系统 Agent。

    返回顺序策略：
    1. 核心 Agent 优先按既有顺序（cs_master → order_agent → refund_agent → general_agent）
    2. 其他新增 Agent 再按 agent_id 字典序追加
    """
    order_priority = {agent_id: idx for idx, agent_id in enumerate(_CORE_AGENT_IDS)}
    sorted_agents = sorted(
        _AGENT_MAP.values(),
        key=lambda a: (order_priority.get(a.agent_id, 999), a.agent_id),
    )
    return sorted_agents


def register_customer_service_agents(agent_registry) -> None:
    """
    将所有客服系统 Agent 注册到 Agent 注册表。

    Args:
        agent_registry: Agent 注册表实例
    """
    agents = get_all_customer_service_agents()
    logger.info(
        f"{Fore.BLUE}[客服 Agent 库] 开始注册 Agent，共 {len(agents)} 个{Style.RESET_ALL}"
    )

    for agent in agents:
        agent_registry.register_agent(agent)
        logger.debug(
            f"{Fore.CYAN}[客服 Agent 库] 已注册 Agent: {agent.agent_id} ({agent.name}){Style.RESET_ALL}"
        )

    logger.info(
        f"{Fore.GREEN}[客服 Agent 库] 所有 Agent 注册完成，共 {len(agents)} 个{Style.RESET_ALL}"
    )
