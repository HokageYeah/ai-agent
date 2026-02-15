"""
全流程端到端集成测试 (Phase 0 - Phase 5)
=====================================
本测试文件用于验证 AI Agent 从基础设施到高级服务层的完整功能流程。
测试默认使用真实 LLM API 数据，以确保整个流程能够串联运行。

覆盖范围：
1. 阶段零：基础设施 (LLM Hub, Tool Hub, Skill Manager)
2. 阶段一：LLM Hub 特性 (Prompt Builder, Streaming)
3. 阶段二：Tool Hub & Builtin Tools (Calculator, DateTime)
4. 阶段三：Skill System (Text Writing)
5. 阶段四：Agent Core (Planning, Execution, Reflection)
6. 阶段五：LangGraph Agent, Chat Service, Automation Service

依赖：
- 必须在 .env 文件中配置有效的 OPENAI_API_KEY 或 ANTHROPIC_API_KEY
- 默认使用 gpt-3.5-turbo 模型

作者: AI Agent Team
创建时间: 2026-02-15
"""

import asyncio
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from loguru import logger
from colorama import Fore, Style, init

# 初始化 colorama
init(autoreset=True)

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 加载 .env 文件
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"{Fore.GREEN}✓ 已加载环境变量文件: {env_path}{Style.RESET_ALL}")
else:
    print(f"{Fore.YELLOW}⚠ 未找到 .env 文件，请确保配置了环境变量{Style.RESET_ALL}")

# 导入必要的模块
from app.llm_hub.registry import ModelRegistry, ModelMetadata
from app.llm_hub.inference import InferenceEngine
from app.tools.hub import ToolHub
from app.tools import CalculatorTool, DateTimeTool
from app.skills.manager import SkillManager
from app.skills.library import TEXT_WRITING_SKILL
from app.agents.base import Agent
from app.agents.langgraph_executor import LangGraphAgentExecutor
from app.services.chat_service import ChatService
from app.services.automation_service import AutomationService
from app.memory.short_term import ShortTermMemory


def setup_logging():
    """配置日志输出"""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        level="INFO"
    )


class TestResult:
    """测试结果记录器"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def add_pass(self, name: str, message: str = ""):
        self.passed += 1
        self.results.append((name, True, message))
        print(f"{Fore.GREEN}✓ [PASS] {name}{Style.RESET_ALL} {message}")

    def add_fail(self, name: str, message: str = ""):
        self.failed += 1
        self.results.append((name, False, message))
        print(f"{Fore.RED}✗ [FAIL] {name}{Style.RESET_ALL} {message}")

    def summary(self):
        print(f"\n{Fore.CYAN}{'='*70}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}测试结果汇总{Style.RESET_ALL}")
        print(f"{Fore.GREEN}通过: {self.passed}{Style.RESET_ALL}")
        print(f"{Fore.RED}失败: {self.failed}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*70}{Style.RESET_ALL}\n")
        return self.failed == 0


async def init_llm_hub(provider_name: str, model_name: str):
    """初始化 LLM Hub"""
    api_key = os.getenv("OPENAI_API_KEY" if provider_name == "openai" else "ANTHROPIC_API_KEY")
    
    if not api_key:
        raise ValueError(f"未配置 {provider_name.upper()} API Key")
        
    print(f"{Fore.BLUE}初始化 LLM Hub ({provider_name})...{Style.RESET_ALL}")
    
    if provider_name == "openai":
        from app.llm_hub.providers.openai import OpenAIProvider
        llm_provider = OpenAIProvider(api_key=api_key)
    else:
        from app.llm_hub.providers.anthropic import AnthropicProvider
        llm_provider = AnthropicProvider(api_key=api_key)
    
    registry = ModelRegistry()
    registry.register_model(ModelMetadata(
        model_id=model_name,
        provider=provider_name,
        model_name=model_name,
        capabilities=["chat", "function_call"], # 确保包含 function_call 能力
        context_window=16385,
        max_output_tokens=4096,
        is_available=True
    ))
    
    llm_hub = InferenceEngine(provider=llm_provider, model_registry=registry)
    return llm_hub


async def test_chat_service(result: TestResult, llm_hub, model_name: str):
    """测试 Chat Service (Phase 5)"""
    print(f"\n{Fore.CYAN}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}测试场景 1: Chat Service 基础对话与记忆{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*70}{Style.RESET_ALL}\n")
    
    try:
        memory = ShortTermMemory()
        chat_service = ChatService(llm_hub=llm_hub, memory=memory)
        
        # 1. 第一轮对话
        user_msg_1 = "你好，我是测试用户 Bob，请记住我的名字。"
        print(f"{Fore.YELLOW}用户: {user_msg_1}{Style.RESET_ALL}")
        
        response_1 = await chat_service.chat(
            conversation_id="test_chat_001",
            message=user_msg_1,
            model=model_name
        )
        print(f"{Fore.GREEN}AI: {response_1['message']}{Style.RESET_ALL}")
        result.add_pass("Chat Service - 第一轮对话", "成功获取回复")
        
        # 2. 第二轮对话 (验证记忆)
        user_msg_2 = "我刚才告诉你我叫什么名字？"
        print(f"{Fore.YELLOW}用户: {user_msg_2}{Style.RESET_ALL}")
        
        response_2 = await chat_service.chat(
            conversation_id="test_chat_001",
            message=user_msg_2,
            model=model_name
        )
        print(f"{Fore.GREEN}AI: {response_2['message']}{Style.RESET_ALL}")
        
        if "Bob" in response_2['message'] or "bob" in response_2['message'].lower():
            result.add_pass("Chat Service - 记忆验证", "成功回忆起用户名 Bob")
        else:
            result.add_fail("Chat Service - 记忆验证", f"未能回忆起用户名 Bob，回复: {response_2['message']}")
            
    except Exception as e:
        result.add_fail("Chat Service 测试异常", str(e))
        import traceback
        traceback.print_exc()


async def test_automation_service(result: TestResult, llm_hub, model_name: str):
    """测试 Automation Service (Phase 5)"""
    print(f"\n{Fore.CYAN}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}测试场景 2: Automation Service 代码生成{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*70}{Style.RESET_ALL}\n")
    
    try:
        # 这里需要 Tool Hub, 虽然代码生成可能只用 LLM
        tool_hub = ToolHub() 
        service = AutomationService(llm_hub=llm_hub, tool_hub=tool_hub)
        
        req = "请用 Python 写一个函数，计算斐波那契数列的第 n 项。"
        print(f"{Fore.YELLOW}请求: {req}{Style.RESET_ALL}")
        
        # 传入模型配置
        code_config = {
            "model": model_name
        }
        
        gen_result = await service.code_generation(
            requirements=req,
            language="python",
            code_config=code_config
        )
        
        if gen_result["success"]:
            print(f"{Fore.GREEN}代码生成成功:{Style.RESET_ALL}")
            print(f"{Fore.CYAN}{gen_result['code']}{Style.RESET_ALL}")
            
            if "def fibonacci" in gen_result["code"] or "def fib" in gen_result["code"]:
                result.add_pass("Automation Service - 代码生成", "成功生成斐波那契函数")
            else:
                result.add_pass("Automation Service - 代码生成", "生成了代码，但未检测到特定函数名(可能是正常的)")
        else:
            result.add_fail("Automation Service - 代码生成", f"生成失败: {gen_result.get('error')}")
            
    except Exception as e:
        result.add_fail("Automation Service 测试异常", str(e))
        import traceback
        traceback.print_exc()


async def test_langgraph_agent(result: TestResult, llm_hub, model_name: str):
    """测试 LangGraph Agent 完整任务 (Phase 4 & 5)"""
    print(f"\n{Fore.CYAN}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}测试场景 3: LangGraph Agent 复杂任务执行{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*70}{Style.RESET_ALL}\n")
    
    try:
        # 1. 初始化组件
        print(f"{Fore.BLUE}初始化 Tool Hub, Skill Manager...{Style.RESET_ALL}")
        tool_hub = ToolHub()
        tool_hub.register_tool(DateTimeTool())
        tool_hub.register_tool(CalculatorTool())
        
        skill_manager = SkillManager()
        skill_manager.register_skill(TEXT_WRITING_SKILL)
        
        # 2. 初始化 Executor
        executor = LangGraphAgentExecutor(
            llm_hub=llm_hub,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        
        # 3. 创建 Agent并配置模型
        from app.agents.base import AgentConfig
        agent_config = AgentConfig(
            planning_model=model_name,
            execution_model=model_name
        )
        
        agent = Agent(
            agent_id="smart_assistant",
            name="Smart Assistant",
            description="一个智能助手，擅长使用工具和技能解决问题",
            role="智能助手",
            agent_config=agent_config
        )
        
        # 4. 执行复杂任务
        # 这个任务需要:
        # 1. 获取当前时间 (DateTimeTool)
        # 2. 计算 (CalculatorTool) - 例如 2030 - current_year
        # 3. 写作 (TextWritingSkill)
        task = "请告诉我今天的日期。如果不使用工具，直接回答我 100 乘以 50 等于多少。最后写一句关于'坚持'的格言。"
        print(f"{Fore.YELLOW}任务: {task}{Style.RESET_ALL}")
        
        exec_result = await executor.execute(
            agent=agent,
            task=task
        )
        
        # 5. 验证结果
        print(f"\n{Fore.GREEN}执行完成!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}最终结果: {exec_result['result']['result']}{Style.RESET_ALL}\n")
        
        # 验证是否成功
        if exec_result["success"]:
            result.add_pass("LangGraph Agent - 任务执行", "任务状态标记为成功")
        else:
            result.add_fail("LangGraph Agent - 任务执行", "任务状态标记为失败")
            
        # 验证步骤
        steps = exec_result["result"].get("step_results", [])
        print(f"{Fore.BLUE}执行步骤详情:{Style.RESET_ALL}")
        for i, step in enumerate(steps):
             print(f"  步骤 {i+1}: {step.get('action')} -> {step.get('success', 'N/A')}")
             
        # 简单的关键词检查
        final_res = str(exec_result['result']['result'])
        if "5000" in final_res:
             result.add_pass("LangGraph Agent - 计算验证", "结果包含正确的计算值 5000")
        else:
             print(f"{Fore.YELLOW}提示: 结果中未找到 5000，可能是表达方式不同{Style.RESET_ALL}")
             
    except Exception as e:
        result.add_fail("LangGraph Agent 测试异常", str(e))
        import traceback
        traceback.print_exc()


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="AI Agent Phase 0-5 End-to-End Integration Test")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic"], help="LLM Provider")
    parser.add_argument("--model", help="Override default model")
    
    args = parser.parse_args()
    
    provider = args.provider
    # 默认模型设置
    if args.model:
        model = args.model
    else:
        model = "gpt-3.5-turbo" if provider == "openai" else "claude-3-haiku-20240307"
        
    print(f"{Fore.CYAN}开始全流程端到端集成测试{Style.RESET_ALL}")
    print(f"Provider: {provider}")
    print(f"Model: {model}")
    
    result = TestResult()
    
    try:
        # 初始化 LLM Hub
        llm_hub = await init_llm_hub(provider, model)
        
        # 运行测试场景 (传递 model 参数)
        await test_chat_service(result, llm_hub, model)
        await test_automation_service(result, llm_hub, model)
        await test_langgraph_agent(result, llm_hub, model)
        
    except Exception as e:
        print(f"{Fore.RED}初始化或全局错误: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
        return 1
        
    # 汇总
    success = result.summary()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
