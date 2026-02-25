"""
Automation Service (自动化服务)
================================

本模块提供自动化任务处理功能。

功能特点：
1. 数据处理自动化
2. 报告生成自动化
3. 代码生成自动化
4. 集成 LLM、Tool Hub 和 Skill Manager

作者: AI Agent Team
创建时间: 2026-02-15
"""

from typing import Dict, List, Any, Optional
from loguru import logger
from colorama import Fore, Style

from app.tools.hub import ToolHub
from app.skills.manager import SkillManager
from app.core.config import settings


class AutomationService:
    """
    自动化服务
    
    提供各种自动化任务处理功能
    """
    
    def __init__(
        self,
        llm_hub,
        tool_hub: Optional[ToolHub] = None,
        skill_manager: Optional[SkillManager] = None
    ):
        """
        初始化自动化服务
        
        Args:
            llm_hub: LLM Hub 实例 (InferenceEngine)
            tool_hub: 工具中心实例（可选）
            skill_manager: 技能管理器实例（可选）
        """
        self.llm_hub = llm_hub
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        
        logger.info(f"{Fore.GREEN}自动化服务初始化完成{Style.RESET_ALL}")
    
    async def data_processing(
        self,
        data: Any,
        processing_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        数据处理自动化
        
        使用 LLM + 工具进行数据处理
        
        Args:
            data: 待处理的数据
            processing_config: 处理配置
                - task: 处理任务描述
                - output_format: 输出格式（可选）
                - tools: 需要使用的工具列表（可选）
                
        Returns:
            Dict[str, Any]: 处理结果
        """
        logger.info(f"{Fore.BLUE}开始数据处理自动化{Style.RESET_ALL}")
        logger.debug(f"{Fore.CYAN}处理配置: {processing_config}{Style.RESET_ALL}")
        
        try:
            # 1. 构建处理 Prompt
            task = processing_config.get("task", "处理以下数据")
            output_format = processing_config.get("output_format", "JSON")
            
            prompt = f"""请{task}：

数据：
{data}

要求：
1. 分析数据结构和内容
2. 执行必要的处理操作
3. 以 {output_format} 格式返回结果

请返回处理后的数据。
"""
            
            logger.debug(f"{Fore.CYAN}构建处理 Prompt{Style.RESET_ALL}")
            
            # 2. 调用 LLM 进行数据处理
            from app.llm_hub.inference import InferenceConfig
            
            config = InferenceConfig(
                model=processing_config.get("model", settings.DEFAULT_MODEL),
                temperature=0.3,  # 数据处理需要更确定性的结果
                max_tokens=processing_config.get("max_tokens", 2048)
            )
            
            logger.info(f"{Fore.BLUE}调用 LLM 进行数据处理...{Style.RESET_ALL}")
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
            )
            
            logger.info(f"{Fore.GREEN}数据处理完成{Style.RESET_ALL}")
            
            return {
                "success": True,
                "result": response.content,
                "model": response.model,
                "usage": response.usage
            }
            
        except Exception as e:
            logger.error(f"{Fore.RED}数据处理失败: {e}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def report_generation(
        self,
        data_source: str,
        template: Optional[str] = None,
        report_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        报告生成自动化
        
        使用 LLM 根据数据源和模板生成报告
        
        Args:
            data_source: 数据源描述或数据内容
            template: 报告模板（可选）
            report_config: 报告配置
                - title: 报告标题
                - sections: 需要包含的部分
                - language: 报告语言
                - format: 报告格式（markdown, html, text）
                
        Returns:
            Dict[str, Any]: 生成的报告
        """
        logger.info(f"{Fore.BLUE}开始报告生成自动化{Style.RESET_ALL}")
        
        try:
            report_config = report_config or {}
            
            # 1. 构建报告生成 Prompt
            title = report_config.get("title", "数据分析报告")
            sections = report_config.get("sections", ["概述", "详细分析", "结论"])
            language = report_config.get("language", "中文")
            report_format = report_config.get("format", "markdown")
            
            prompt = f"""请根据以下信息生成{language}报告：

报告标题：{title}

数据源：
{data_source}
"""
            
            if template:
                prompt += f"""
报告模板：
{template}
"""
            
            prompt += f"""
报告要求：
1. 包含以下部分：{', '.join(sections)}
2. 使用 {report_format} 格式
3. 内容详实、逻辑清晰
4. 包含数据分析和洞察

请生成完整的报告。
"""
            
            logger.debug(f"{Fore.CYAN}构建报告生成 Prompt{Style.RESET_ALL}")
            
            # 2. 调用 LLM 生成报告
            from app.llm_hub.inference import InferenceConfig
            
            config = InferenceConfig(
                model=report_config.get("model", settings.DEFAULT_MODEL),
                temperature=0.7,
                max_tokens=report_config.get("max_tokens", 4096)
            )
            
            logger.info(f"{Fore.BLUE}调用 LLM 生成报告...{Style.RESET_ALL}")
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
            )
            
            logger.info(f"{Fore.GREEN}报告生成完成{Style.RESET_ALL}")
            
            return {
                "success": True,
                "report": response.content,
                "title": title,
                "format": report_format,
                "model": response.model,
                "usage": response.usage
            }
            
        except Exception as e:
            logger.error(f"{Fore.RED}报告生成失败: {e}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def code_generation(
        self,
        requirements: str,
        language: str = "Python",
        framework: Optional[str] = None,
        code_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        代码生成自动化
        
        根据需求生成代码
        
        Args:
            requirements: 代码需求描述
            language: 编程语言
            framework: 使用的框架（可选）
            code_config: 代码配置
                - style: 代码风格
                - include_tests: 是否包含测试
                - include_docs: 是否包含文档
                
        Returns:
            Dict[str, Any]: 生成的代码
        """
        logger.info(f"{Fore.BLUE}开始代码生成自动化{Style.RESET_ALL}")
        logger.info(f"{Fore.CYAN}编程语言: {language}{Style.RESET_ALL}")
        
        try:
            code_config = code_config or {}
            
            # 1. 尝试使用代码生成技能
            if self.skill_manager:
                skill = self.skill_manager.get_skill("code_generation")
                if skill:
                    logger.info(f"{Fore.CYAN}使用代码生成技能{Style.RESET_ALL}")
                    
                    # 使用技能生成代码
                    from app.llm_hub.inference import InferenceConfig
                    
                    config = InferenceConfig(
                        model=code_config.get("model", settings.DEFAULT_MODEL),
                        temperature=0.3,
                        max_tokens=code_config.get("max_tokens", 4096)
                    )
                    
                    # 构建技能参数
                    skill_params = {
                        "requirements": requirements,
                        "language": language,
                        "framework": framework or "无"
                    }
                    
                    # 使用技能的 prompt 模板
                    prompt = skill.prompt_template.format(**skill_params)
                    
                    response = await self.llm_hub.infer(
                        messages=[{"role": "user", "content": prompt}],
                        config=config
                    )
                    
                    logger.info(f"{Fore.GREEN}代码生成完成（使用技能）{Style.RESET_ALL}")
                    
                    return {
                        "success": True,
                        "code": response.content,
                        "language": language,
                        "framework": framework,
                        "model": response.model,
                        "usage": response.usage
                    }
            
            # 2. 如果没有技能，直接使用 LLM 生成
            logger.info(f"{Fore.CYAN}使用直接 LLM 生成{Style.RESET_ALL}")
            
            style = code_config.get("style", "清晰且符合最佳实践")
            include_tests = code_config.get("include_tests", False)
            include_docs = code_config.get("include_docs", True)
            
            prompt = f"""请使用 {language} 生成代码：

需求：
{requirements}
"""
            
            if framework:
                prompt += f"\n框架：{framework}\n"
            
            prompt += f"""
代码要求：
1. 代码风格：{style}
2. 包含必要的注释和文档字符串：{'是' if include_docs else '否'}
3. 包含单元测试：{'是' if include_tests else '否'}
4. 处理边界情况和错误
5. 确保代码可以直接运行

请生成完整的代码。
"""
            
            from app.llm_hub.inference import InferenceConfig
            
            config = InferenceConfig(
                model=code_config.get("model", settings.DEFAULT_MODEL),
                temperature=0.3,
                max_tokens=code_config.get("max_tokens", 4096)
            )
            
            logger.info(f"{Fore.BLUE}调用 LLM 生成代码...{Style.RESET_ALL}")
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
            )
            
            logger.info(f"{Fore.GREEN}代码生成完成{Style.RESET_ALL}")
            
            return {
                "success": True,
                "code": response.content,
                "language": language,
                "framework": framework,
                "model": response.model,
                "usage": response.usage
            }
            
        except Exception as e:
            logger.error(f"{Fore.RED}代码生成失败: {e}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e)
            }


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Automation Service 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试需要异步环境
    print(f"{Fore.YELLOW}请使用 pytest 运行测试{Style.RESET_ALL}")
    
    print(f"\n{Fore.GREEN}模块加载成功!{Style.RESET_ALL}\n")
