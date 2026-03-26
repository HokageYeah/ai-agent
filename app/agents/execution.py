"""
执行引擎 (Execution Engine)
================================

本模块负责执行由 Planning Engine 生成的计划。

功能特点：
1. 逐步执行计划中的每个步骤
2. 支持工具调用、技能调用、子 Agent 委派
3. 实现错误处理和恢复机制
4. 收集执行结果

作者: AI Agent Team
创建时间: 2026-02-15
"""

import re
import json as _json
import shlex
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Awaitable
from typing import Dict as DictType
from typing import List as ListType
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.agents.planning import Plan, PlanStep
from app.core.config import get_default_model
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager
from app.utils.prompt_manager import PromptManager


class ExecutionResult:
    """执行结果"""
    
    def __init__(
        self,
        success: bool,
        result: Any,
        step_results: List[Dict[str, Any]] = None,
        error: Optional[str] = None,
        user_rejected_tools: Optional[List[str]] = None
    ):
        """
        初始化执行结果
        
        Args:
            success: 是否成功
            result: 最终结果
            step_results: 每个步骤的执行结果
            error: 错误信息
            user_rejected_tools: 用户已拒绝的工具列表
        """
        self.success = success
        self.result = result
        self.step_results = step_results or []
        self.error = error
        self.user_rejected_tools = user_rejected_tools or []
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "result": self.result,
            "step_results": self.step_results,
            "error": self.error,
            "user_rejected_tools": self.user_rejected_tools
        }


class ExecutionEngine:
    """
    执行引擎
    
    执行由 Planning Engine 生成的计划
    """
    
    def __init__(
        self,
        tool_hub: ToolHub,
        skill_manager: SkillManager,
        llm_hub,
        child_agent_manager=None,
        tool_gateway=None
    ):
        """
        初始化执行引擎
        
        Args:
            tool_hub: 工具中心
            skill_manager: 技能管理器
            llm_hub: LLM Hub 实例
            child_agent_manager: 子 Agent 管理器（可选）
            tool_gateway: ToolCallingGateway 实例（可选）
                         当提供时，_execute_tool() 会优先通过网关执行工具调用，
                         统一享受网关的参数校验、日志统计、超时控制等能力；
                         未提供时降级为直接调用 ToolHub 中的工具实例。
        """
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        self.llm_hub = llm_hub
        self.child_agent_manager = child_agent_manager
        # ToolCallingGateway 实例：路由所有工具调用，实现统一管控
        self.tool_gateway = tool_gateway

        # 提示词管理器（execution 专用）
        self.prompt_manager = None
        try:
            self.prompt_manager = PromptManager(prompt_dir="app/prompt/execution")
            self.prompt_manager.load_prompt("answer_synthesis_with_results")
            self.prompt_manager.load_prompt("context_fallback_synthesis")
            self.prompt_manager.load_prompt("generic_skill_fallback")
        except Exception as exc:
            logger.warning(
                f"{Fore.YELLOW}[执行引擎] 初始化/预加载 execution 提示词失败（{exc}），"
                f"运行时将回退内置提示词{Style.RESET_ALL}"
            )

    def _truncate_tool_error_text(self, value: Any, limit: int = 240) -> str:
        """
        截断工具错误文本，避免错误摘要把上下文挤爆。

        这里保留单行预览即可，详细原始结果仍会放在 result 字段中供后续记忆写入。
        """
        text = str(value or "").strip()
        if not text:
            return ""
        compact = re.sub(r"\s+", " ", text)
        if len(compact) <= limit:
            return compact
        return compact[:limit] + "..."

    def _infer_tool_failure_recovery_hint(
        self,
        *,
        tool_name: str,
        result: Dict[str, Any],
    ) -> str:
        """
        根据失败结果推断高置信度恢复建议。

        设计原则：
        - 只输出“高置信度、通用”的建议，避免硬编码单技能逻辑；
        - 当前重点覆盖最常见、可恢复的缺依赖/缺命令场景；
        - 保持为纯文本提示，供反思/重规划或记忆系统继续利用。
        """
        if not isinstance(result, dict):
            return ""

        combined_text = "\n".join(
            str(result.get(key, "") or "")
            for key in ("error", "stderr", "stdout")
        )
        if not combined_text.strip():
            return ""

        npm_missing_match = re.search(
            r"Cannot find module ['\"]([^'\"]+)['\"]",
            combined_text,
            flags=re.IGNORECASE,
        )
        if npm_missing_match:
            package_name = npm_missing_match.group(1).strip()
            return (
                f"检测到缺少 Node 模块 '{package_name}'，"
                f"应优先在当前 working_dir 执行 `npm install --no-save {package_name}` 后重试。"
            )

        python_missing_match = re.search(
            r"(?:ModuleNotFoundError|ImportError): .*?['\"]([^'\"]+)['\"]",
            combined_text,
            flags=re.IGNORECASE,
        )
        if python_missing_match:
            package_name = python_missing_match.group(1).strip()
            return (
                f"检测到缺少 Python 模块 '{package_name}'，"
                f"若属于后端项目依赖应使用 `poetry add {package_name}`，"
                "若属于独立技能目录则需先准备对应运行环境后再重试。"
            )

        command_missing_match = re.search(
            r"(?:^|[\n: ])([a-zA-Z0-9_.-]+):\s+command not found",
            combined_text,
            flags=re.IGNORECASE,
        )
        if command_missing_match:
            command_name = command_missing_match.group(1).strip()
            return (
                f"检测到缺少命令 '{command_name}'，"
                "需先安装该命令，或改用当前环境已存在的替代工具。"
            )

        if re.search(
            r"(unsupported engine|EBADENGINE|requires?\s+node|requires?\s+Node|not compatible with your version of node)",
            combined_text,
            flags=re.IGNORECASE,
        ):
            return "检测到 Node 版本或依赖引擎兼容性问题，需要安装兼容版本的依赖或升级 Node 后重试。"

        return ""

    def _build_tool_business_error(self, tool_name: str, result: Any) -> str:
        """
        构造业务级失败摘要。

        为什么需要单独归一化：
        - 很多工具会返回 `success=false`，但真正的失败线索藏在 stderr/stdout/return_code 中；
        - 若只把 `success=false` 透传给反思/重规划，模型只能盲猜原因；
        - 这里统一提炼关键信息，供日志、记忆和下一轮规划复用。
        """
        if not isinstance(result, dict):
            text = self._truncate_tool_error_text(result)
            return text or f"工具 {tool_name} 返回 success=false"

        base_error = str(result.get("error") or f"工具 {tool_name} 返回 success=false").strip()
        detail_parts: List[str] = []

        return_code = result.get("return_code")
        if return_code not in (None, ""):
            detail_parts.append(f"return_code={return_code}")

        stderr_preview = self._truncate_tool_error_text(result.get("stderr"))
        stdout_preview = self._truncate_tool_error_text(result.get("stdout"))
        if stderr_preview:
            detail_parts.append(f"stderr={stderr_preview}")
        elif stdout_preview and tool_name in {"shell_exec", "python_executor"}:
            detail_parts.append(f"stdout={stdout_preview}")

        working_dir = self._truncate_tool_error_text(result.get("working_dir"), limit=120)
        if working_dir and tool_name in {"shell_exec", "python_executor"}:
            detail_parts.append(f"working_dir={working_dir}")

        recovery_hint = self._infer_tool_failure_recovery_hint(
            tool_name=tool_name,
            result=result,
        )
        if recovery_hint:
            detail_parts.append(f"恢复建议={recovery_hint}")

        if not detail_parts:
            return base_error

        return f"{base_error} | " + " | ".join(detail_parts)
        
        if tool_gateway:
            logger.info(
                f"{Fore.GREEN}执行引擎初始化完成 "
                f"[工具网关: 已启用]{Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.GREEN}执行引擎初始化完成 "
                f"[工具网关: 未配置，使用直接调用模式]{Style.RESET_ALL}"
            )
    
    def _build_answer_synthesis_prompt(self, agent: Agent, task: str, results_text: str) -> str:
        """构建基于工具结果的最终答案合成提示词。"""
        try:
            if self.prompt_manager is None:
                raise RuntimeError("prompt_manager 不可用")
            return self.prompt_manager.render_prompt(
                "answer_synthesis_with_results",
                agent_name=agent.name,
                agent_description=agent.description,
                task=task,
                results_text=results_text,
            )
        except Exception as exc:
            logger.warning(
                f"{Fore.YELLOW}[执行引擎] 渲染 answer_synthesis_with_results 失败（{exc}），"
                f"回退内置提示词{Style.RESET_ALL}"
            )
            return f"""你是 {agent.name}，{agent.description}

用户任务：{task}

以下是执行过程中获取到的数据：

{results_text}

请根据以上数据，用清晰、友好的自然语言回答用户的任务需求。
要求：
1. 直接给出具体数据，不要使用 [xxx] 这样的占位符
2. 信息完整，涵盖用户关心的所有字段
3. 格式清晰，必要时使用列表或分段展示
4. 如果数据中有错误或空值，如实告知
5. 【重要防幻觉】如果任务包含“写入本地文件/保存到文件”等需求，你必须**严格检查上方数据中是否有 `file_write` 工具的执行成功结果**。
   - 如果**有** `file_write` 工具且执行成功：说明写入成功、写入路径与写入内容来源。
   - 如果**没有** `file_write` 工具的结果：你**绝对不能**说"已入写本地文件"或"已保存到文件"。对于只有 `text_writing` 技能的结果，请只返回生成的文本内容，不要编造任何本地文件路径。
6. **若执行结果来自 python_executor 且为“替用户生成写文件的脚本”**（例如因用户拒绝了 file_write）：若工具返回中有 output 且为一段 Python 代码/脚本，最终回答必须**完整贴出**该 output 的全文（即可运行的脚本），并说明「因您拒绝了由系统直接写入文件，已为您生成以下可本地运行的 Python 脚本。请将下方代码保存为 .py 文件（如 save_content.py）后在本地执行，即可在当前目录生成文件。」禁止只做概括或省略脚本内容。

请直接输出最终回答，不要包含任何前缀说明。"""

    def _build_context_fallback_prompt(self, agent: Agent, task: str, context_text: str) -> str:
        """构建基于会话上下文的兜底答案合成提示词。"""
        try:
            if self.prompt_manager is None:
                raise RuntimeError("prompt_manager 不可用")
            return self.prompt_manager.render_prompt(
                "context_fallback_synthesis",
                agent_name=agent.name,
                agent_description=agent.description,
                task=task,
                context_text=context_text,
            )
        except Exception as exc:
            logger.warning(
                f"{Fore.YELLOW}[执行引擎] 渲染 context_fallback_synthesis 失败（{exc}），"
                f"回退内置提示词{Style.RESET_ALL}"
            )
            return f"""你是 {agent.name}，{agent.description}

用户当前的问题（任务）：{task}

以下是本次会话的历史上下文信息（包含之前各轮任务的摘要）：

{context_text}

请根据以上历史上下文，直接、准确地回答用户的问题。
要求：
1. 基于历史信息给出具体、完整的回答，不要模糊或含糊其辞
2. 如果历史上下文中有明确的信息，直接陈述（如"您第一次的提问是'xxx'，任务是yyy"）
3. 语言简洁友好，格式清晰
4. 如果历史记录中确实没有相关信息，如实告知

请直接输出最终回答，不要包含任何前缀说明。"""

    def _build_generic_skill_fallback_prompt(
        self,
        skill_name: str,
        skill_description: str,
        prompt_params_str: str,
    ) -> str:
        """构建技能通用兜底提示词。"""
        try:
            if self.prompt_manager is None:
                raise RuntimeError("prompt_manager 不可用")
            return self.prompt_manager.render_prompt(
                "generic_skill_fallback",
                skill_name=skill_name,
                skill_description=skill_description,
                prompt_params_str=prompt_params_str,
            )
        except Exception as exc:
            logger.warning(
                f"{Fore.YELLOW}[执行引擎] 渲染 generic_skill_fallback 失败（{exc}），"
                f"回退内置提示词{Style.RESET_ALL}"
            )
            return f"""请执行技能"{skill_name}"的任务。
                
任务描述:
{skill_description}

输入参数:
{prompt_params_str}

请直接输出执行结果。
"""

    def _safe_format_skill_prompt(
        self,
        *,
        template: str,
        values: Dict[str, Any],
        skill_id: str
    ) -> str:
        """
        安全渲染技能 Prompt：
        - 已提供的变量正常替换
        - 未提供的变量保持 {var} 原样，不抛异常
        - 避免因示例中的占位符（如 {lat}/{lon}）导致整个技能退化到通用 Prompt
        """

        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:
                return "{" + key + "}"

        try:
            rendered = template.format_map(_SafeDict(values))
        except Exception as exc:
            logger.warning(
                f"{Fore.YELLOW}[执行引擎] 技能 Prompt 安全格式化异常，保留原模板继续执行 | "
                f"skill={skill_id} | error={exc}{Style.RESET_ALL}"
            )
            return template

        # 记录未替换占位符，方便排查技能参数定义是否缺失
        unresolved = sorted(
            set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", rendered))
        )
        if unresolved:
            logger.debug(
                f"{Fore.CYAN}[执行引擎] 技能 Prompt 存在未替换占位符（将保留原样） | "
                f"skill={skill_id} | placeholders={unresolved}{Style.RESET_ALL}"
            )

        return rendered

    def _extract_tool_name_from_schema(self, schema: Dict[str, Any]) -> Optional[str]:
        """
        从工具 Schema 中提取工具名。

        兼容两类结构：
        1) {"name": "tool_name", ...}
        2) {"type": "function", "function": {"name": "tool_name", ...}}
        """
        if not isinstance(schema, dict):
            return None

        direct_name = schema.get("name")
        if isinstance(direct_name, str) and direct_name.strip():
            return direct_name.strip()

        fn = schema.get("function")
        if isinstance(fn, dict):
            fn_name = fn.get("name")
            if isinstance(fn_name, str) and fn_name.strip():
                return fn_name.strip()

        return None

    def _validate_skill_output(
        self,
        *,
        skill_id: str,
        output_text: str,
        params: Dict[str, Any],
        validators: Optional[List[Dict[str, Any]]] = None
    ) -> tuple[bool, str]:
        """
        对技能输出做轻量质量校验，避免“空泛话术”被误判为执行成功。
        """
        text = (output_text or "").strip()
        if not text:
            return False, f"{skill_id} 技能返回空内容"

        # 通用拦截：避免“流程汇报口吻”冒充技能结果，污染后续 file_write/final_answer。
        # 说明：这里使用“多信号命中”而非单关键词，尽量降低误杀。
        process_report_exempt_skills = {"dynamic_probe", "skill-creator"}
        if skill_id not in process_report_exempt_skills:
            head_text = text[:420]
            process_markers = [
                "任务已完成",
                "已成功完成",
                "已为您完成",
                "我已经成功",
                "本次执行了",
                "文件路径为",
                "已保存到",
            ]
            marker_hits = sum(1 for marker in process_markers if marker in head_text)
            has_action_list = bool(
                re.search(r"^\s*\d+\.\s+\*\*?.{0,40}\*\*?[：:]", head_text, flags=re.MULTILINE)
            )
            if marker_hits >= 2 and has_action_list:
                return False, f"{skill_id} 输出为执行过程说明，不是最终结果正文"

        # 声明式校验：遍历 SKILL.md 中定义的 output_validators 规则
        # 每条规则包含 type（校验类型）、markers（标记词列表）、error（失败提示）
        for rule in (validators or []):
            rule_type = str(rule.get("type", "")).strip()
            markers = rule.get("markers", [])
            error_msg = str(rule.get("error", f"{skill_id} 声明式校验失败"))

            if rule_type == "must_contain_any":
                # 输出必须包含至少一个标记词（如天气技能要求含"温度"等关键词）
                if not any(m in text for m in markers):
                    return False, error_msg

            elif rule_type == "must_not_contain_any":
                # 输出不得包含任何标记词（如拦截"引导话术"式回复）
                if any(m in text for m in markers):
                    return False, error_msg

            else:
                # 未知校验类型仅记录日志，不阻断执行，确保向前兼容
                logger.warning(
                    f"{Fore.YELLOW}[执行引擎] 未知 output_validator 类型: {rule_type} | "
                    f"skill={skill_id}{Style.RESET_ALL}"
                )

        return True, ""

    def _extract_original_user_request(self, task_text: str) -> str:
        """
        从委派任务文本中提取“用户原始请求”。

        背景：
        - 委派链路会把原始请求追加到 task 中（用于防遗漏）。
        - 受限技能门禁应优先依据“原始请求意图”判断，而不是被子任务改写后的措辞误导。
        """
        text = str(task_text or "").strip()
        if not text:
            return ""

        match = re.search(r"用户原始请求[:：]\s*(.+?)(?:\n|$)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return text

    def _is_explicit_skill_creator_request(self, text: str) -> bool:
        """
        判断文本是否“明确要求创建/修改技能能力包”。
        """
        text_l = str(text or "").lower().strip()
        if not text_l:
            return False
        patterns = [
            r"(创建|新建|生成|开发|编写|改造|修改|更新|定制|做).{0,10}(技能|skill|能力包|skill包)",
            r"(skill[-_ ]?creator)",
            r"\b(create|build|generate|update|modify)\b.{0,24}\b(skill|skills)\b",
        ]
        return any(re.search(p, text_l) for p in patterns)

    def _is_explicit_dynamic_probe_request(self, text: str) -> bool:
        """
        判断文本是否“明确要求 dynamic_probe 探针验证”。
        """
        text_l = str(text or "").lower().strip()
        if not text_l:
            return False
        patterns = [
            r"dynamic[_-]?probe",
            r"探针自检",
            r"可用性验证",
            r"链路验证",
            r"技能验证",
        ]
        return any(re.search(p, text_l) for p in patterns)

    def _check_restricted_skill_invocation(
        self,
        *,
        skill_id: Optional[str],
        context: Optional[Dict[str, Any]],
        params: Dict[str, Any],
    ) -> tuple[bool, str]:
        """
        受限技能调用门禁（执行阶段兜底）。

        目标：
        - 即使规划阶段误选了受限技能，也在执行前阻断，避免副作用。
        """
        sid = str(skill_id or "").strip()
        if sid not in {"skill-creator", "dynamic_probe"}:
            return True, ""

        task_text = str((context or {}).get("task", "") or "")
        primary_task = self._extract_original_user_request(task_text)
        brief_text = str((params or {}).get("brief", "") or "")

        if sid == "skill-creator":
            allow = (
                self._is_explicit_skill_creator_request(primary_task)
                or self._is_explicit_skill_creator_request(task_text)
                or self._is_explicit_skill_creator_request(brief_text)
            )
            if not allow:
                return (
                    False,
                    "skill-creator 仅在用户明确要求“创建/新建/修改技能或能力包”时允许调用；"
                    "当前任务属于普通业务处理，应改用现有技能或工具完成。",
                )

        if sid == "dynamic_probe":
            allow = (
                self._is_explicit_dynamic_probe_request(primary_task)
                or self._is_explicit_dynamic_probe_request(task_text)
            )
            if not allow:
                return (
                    False,
                    "dynamic_probe 仅在用户明确要求“探针自检/可用性验证”时允许调用；"
                    "当前任务不应触发该探针技能。",
                )

        return True, ""

    async def execute_plan(
        self,
        agent: Agent,
        plan: Plan,
        context: Optional[Dict[str, Any]] = None,
        on_step_start: Optional[Callable[["PlanStep", int, int], Awaitable[None]]] = None,
        on_step_complete: Optional[Callable[[Dict[str, Any], int, int], Awaitable[None]]] = None
    ) -> ExecutionResult:
        """
        执行计划

        Args:
            agent: Agent 实例
            plan: 执行计划
            context: 执行上下文
            on_step_start: 【新增】步骤开始实时回调，签名为 async (step, step_idx, step_total) -> None。
                用于在工具/委派执行**前**立即推送 tool_start 类似事件，解决需要前端交互输入的工具顺序错乱问题。
            on_step_complete: 【新增】步骤完成实时回调，签名为 async (step_result, step_idx, step_total) -> None。
                用于在每个步骤完成后立即推送 SSE 事件，解决以下问题：
                - 若在 execute_plan 外部（如 _execute_node）遍历 step_results 后批量推送事件，
                  会造成 sub_agent_start/end 事件（委派期间内部推送）早于 tool_complete 事件出现，
                  导致前端看到「先委派后查询」的错误顺序。
                - 通过在每步完成后立即回调，保证 tool_complete 紧跟在 sub_agent_start 之前推送。
            
        Returns:
            ExecutionResult: 执行结果
        """
        logger.info(
            f"{Fore.BLUE}开始执行计划，共 {len(plan.steps)} 个步骤{Style.RESET_ALL}"
        )
        
        step_results = []
        final_result = None
        step_total = len(plan.steps)
        # ── 新增: 初始化用户已拒绝工具黑名单 ──────────────────────────────
        # 继承父级传来的 user_rejected_tools，防止重复尝试已被拒绝的工具。
        user_rejected_tools = list(context.get("user_rejected_tools", [])) if context else []
        
        try:
            for i, step in enumerate(plan.steps, 1):
                logger.info(
                    f"{Fore.CYAN}执行步骤 {i}/{step_total}: "
                    f"action={step.action}{Style.RESET_ALL}"
                )
                
                # ═══════════════════════════════════════════════════════════════
                # 【步骤参数占位符替换】
                # LLM 规划时可能使用占位符如 {{first_search_result_url}}，
                # 需要根据已执行步骤的结果动态替换为真实数据
                # ═══════════════════════════════════════════════════════════════
                step = self._resolve_step_placeholders(step, step_results)
                
                # 【新增】执行步骤开始前触发实时事件回调，保障前端能先看到「正在调用工具」的UI状态，然后再出表单弹窗
                if on_step_start and step.action != "final_answer":
                    logger.debug(
                        f"{Fore.CYAN}[执行引擎] 步骤 {i}/{step_total} 开始，触发实时事件回调 "
                        f"(action={step.action}){Style.RESET_ALL}"
                    )
                    await on_step_start(step, i, step_total)
                
                # ===============================================================
                # 【执行步骤】传入当前步骤所在计划及索引
                # NOTE: plan 和 step_index 用于让 _delegate_to_agent 感知父计划的
                #       后续步骤，避免需求检查盲目注入已被后续步骤覆盖的需求。
                #       step_index 为 0-based 索引（i 为 1-based 展示用）。
                # ===============================================================
                step_result = await self._execute_step(
                    agent, step, context, step_results,
                    parent_plan=plan, step_index=i - 1
                )
                
                # NOTE: 防御性保护 ── _execute_step 理论上始终返回 dict，
                #   但在极端情况（如工具内部未处理的异常）下可能返回 None，
                #   直接访问 None['key'] 会引发 'NoneType' is not subscriptable 崩溃。
                #   此处统一兜底，将 None 转为标准错误结构，保证主循环不中断。
                if step_result is None:
                    logger.error(
                        f"{Fore.RED}[执行引擎] _execute_step 返回了 None（步骤 {i}/{step_total}: "
                        f"action={step.action}），已升级为错误结构以防崩溃{Style.RESET_ALL}"
                    )
                    step_result = {
                        "success": False,
                        "action": step.action,
                        "result": None,
                        "error": "_execute_step 返回了 None（内部错误）",
                        "user_rejected_tools": [],
                    }
                
                # ── 新增: 合并子层级返回的 user_rejected_tools ────────────────
                # 不论是本层直接调用工具被拒，还是嵌套的子 Agent 中工具被拒，
                # 都需不断向父层冒泡累积，防止不同层级的重新规划尝试同一条死路。
                if "user_rejected_tools" in step_result:
                    for t in step_result["user_rejected_tools"]:
                        if t not in user_rejected_tools:
                            user_rejected_tools.append(t)
                            
                step_results.append(step_result)

                # ═══════════════════════════════════════════════════════════════
                # 【实时 SSE 事件推送】步骤完成后立即回调，保证事件顺序正确。
                #
                # 设计动机：
                #   子Agent委派（delegate）期间，child_agent_manager 内部会直接通过
                #   stream_callback 推送 sub_agent_start/end 及子Agent全部内部事件。
                #   若等到 execute_plan 返回后才在 _execute_node 中遍历批量推送
                #   tool_complete/delegate_complete，则这些事件会晚于 sub_agent_end 到达，
                #   造成前端看到「先委派后查询」的假象。
                #
                #   通过在此处调用 on_step_complete，保证：
                #   Step1(tool)完成 → 立即推送 tool_complete
                #   Step2(delegate)期间 → 推送 sub_agent_start/内部事件/sub_agent_end
                #   Step2(delegate)完成 → 立即推送 delegate_complete
                #   顺序完全还原为规划设计的真实执行顺序。
                # ═══════════════════════════════════════════════════════════════
                if on_step_complete and step.action != "final_answer":
                    # final_answer 步骤的合成在下方进行，等合成完毕再回调
                    logger.debug(
                        f"{Fore.CYAN}[执行引擎] 步骤 {i}/{step_total} 完成，触发实时事件回调 "
                        f"(action={step.action}){Style.RESET_ALL}"
                    )
                    await on_step_complete(step_result, i, step_total)
                
                # 如果是 final_answer，先合成再返回
                if step.action == "final_answer":
                    template = step.params.get("content", "")
                    
                    # 收集本轮所有成功的工具/技能/委派结果（排除 final_answer 步骤本身）
                    tool_results = [
                        r for r in step_results
                        if r.get("success") and r.get("result")
                        and r.get("action") != "final_answer"
                    ]
                    
                    # ══════════════════════════════════════════════════════════
                    # 【合成策略判断】LLM 规划的 final_answer.content 有两种情况：
                    # - 情况A（有工具前置）：content 只是意图描述 → 用工具结果 LLM 合成
                    # - 情况B（纯记忆问答）：LLM 理应在 content 写出真实答案，
                    #   但有时仍会写意图描述（如"根据历史记录回答..."）→ 需要兜底合成
                    # ══════════════════════════════════════════════════════════
                    
                    # 判断 content 是否是"意图描述"而非真实自然语言答案
                    # 意图描述的特征：包含"根据"/"历史"/"回答用户"/"以上"等指令性词汇，
                    # 且不包含具体信息（通常较短）
                    def _is_intent_description(content: str) -> bool:
                        """判断 content 是否是意图/占位符描述，而非真实答案"""
                        if not content:
                            return True
                        intent_keywords = [
                            "根据历史", "根据以上", "根据上面", "根据前面",
                            "回答用户", "回答关于", "回答该", "回答此",
                            "结合历史", "参考历史", "基于历史",
                            "用户关于", "告知用户",
                            "查询结果回答", "执行结果回答",
                        ]
                        # 短内容（<30字）且包含意图关键词 → 判断为意图描述
                        if len(content) < 80:
                            for kw in intent_keywords:
                                if kw in content:
                                    return True
                        return False
                    
                    # 获取会话历史上下文（用于兜底合成）
                    context_messages = (context or {}).get("context_messages", [])
                    
                    if bool(tool_results):
                        # 情况A：有前置工具结果 → 用工具结果驱动 LLM 合成
                        logger.info(
                            f"{Fore.BLUE}[执行引擎] 存在工具/委派执行结果，"
                            f"调用 LLM 合成真实答案...{Style.RESET_ALL}"
                        )
                        final_result = await self._synthesize_answer(
                            agent=agent,
                            task=context.get("task", "") if context else "",
                            tool_results=tool_results,
                            template=template
                        )
                    elif context_messages and _is_intent_description(template):
                        # ══════════════════════════════════════════════════════
                        # 【兜底安全网】情况B：计划只有 final_answer 一步，
                        # 且 LLM 仍然写了意图描述而非真实答案。
                        # 此时用会话历史 context_messages 重新触发 LLM 直接合成真实答案，
                        # 防止把意图描述文本（如"根据历史记录回答..."）直接返回给用户。
                        # ══════════════════════════════════════════════════════
                        logger.warning(
                            f"{Fore.YELLOW}[执行引擎] 检测到纯 final_answer 场景，"
                            f"且 content 为意图描述（'{template[:50]}'）。"
                            f"存在会话历史上下文（{len(context_messages)} 条），"
                            f"触发兜底 LLM 合成真实答案...{Style.RESET_ALL}"
                        )
                        final_result = await self._synthesize_from_context(
                            agent=agent,
                            task=context.get("task", "") if context else "",
                            context_messages=context_messages,
                        )
                    elif template:
                        logger.info(
                            f"{Fore.CYAN}[执行引擎] 直接使用 final_answer.content 作为最终结果"
                            f"（长度={len(template)}）{Style.RESET_ALL}"
                        )
                        final_result = template
                    else:
                        final_result = "执行完成，但没有产生具体结果。"

                    logger.info(
                        f"{Fore.GREEN}执行完成，获得最终答案{Style.RESET_ALL}"
                    )
                    
                    # final_answer 步骤也触发实时回调（合成完成后再推送，保证数据完整性）
                    if on_step_complete:
                        logger.debug(
                            f"{Fore.CYAN}[执行引擎] final_answer 步骤合成完毕，触发实时事件回调 "
                            f"(step={i}/{step_total}){Style.RESET_ALL}"
                        )
                        await on_step_complete(step_result, i, step_total)
                    break
                
                # 检查步骤是否成功
                if not step_result.get("success", True):
                    logger.warning(
                        f"{Fore.YELLOW}步骤 {i} 执行失败: "
                        f"{step_result.get('error', 'Unknown error')}{Style.RESET_ALL}"
                    )
                    # 继续执行后续步骤（也可以选择中断）
            
            # 如果没有 final_answer，使用最后一个步骤的结果
            if final_result is None and step_results:
                final_result = step_results[-1].get("result", "")
            
            logger.info(f"{Fore.GREEN}计划执行成功{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=True,
                result=final_result,
                step_results=step_results,
                user_rejected_tools=user_rejected_tools
            )
            
        except Exception as e:
            logger.error(f"{Fore.RED}执行计划时发生错误: {e}{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=False,
                result=None,
                step_results=step_results,
                error=str(e),
                user_rejected_tools=user_rejected_tools
            )
    
    async def _synthesize_answer(
        self,
        agent: Agent,
        task: str,
        tool_results: List[Dict[str, Any]],
        template: str = ""
    ) -> str:
        """
        调用 LLM 将工具/技能返回的原始数据合成为自然语言的最终答案。

        在 final_answer 的 content 包含占位符（如 [status]、[customer_name]）
        或为空时触发，避免把模板字符串作为最终结果返回给用户。

        Args:
            agent: 当前执行的 Agent 实例（用于取角色名）
            task: 原始用户任务描述
            tool_results: 本轮所有成功的工具/技能/委派结果列表
            template: LLM 规划时写的 final_answer 模板（可能含占位符）

        Returns:
            str: 基于真实数据合成的自然语言答案
        """
        # ── 格式化工具结果，供 LLM 阅读 ──────────────────────
        result_parts = []
        for idx, r in enumerate(tool_results, 1):
            label = r.get("tool_name") or r.get("agent_id") or r.get("action", f"步骤{idx}")
            # 对 delegate 结果保留子 Agent 的详细执行轨迹，避免上层合成时丢失关键信息
            # （如子 Agent 内 file_write 的真实写入结果）
            if r.get("action") == "delegate":
                val = {
                    "agent_id": r.get("agent_id"),
                    "success": r.get("success"),
                    "result": r.get("result"),
                    "step_results": r.get("step_results", []),
                    "error": r.get("error"),
                }
            elif r.get("tool_name") == "python_executor" and isinstance(r.get("result"), dict):
                res = r.get("result") or {}
                val = {
                    "success": res.get("success"),
                    "result": res.get("result"),
                    "output": res.get("output"),
                    "error": res.get("error"),
                }
                if res.get("output"):
                    val["_hint"] = "以上 output 为 python_executor 的输出。若为一段可运行的 Python 脚本（替用户生成写文件用），请在最终回答中完整贴出脚本并说明用户保存为 .py 后运行即可；若为普通文本则完整包含即可。"
            else:
                val = r.get("result", "")
            if isinstance(val, dict):
                val_str = _json.dumps(val, ensure_ascii=False, indent=2, default=str)
            else:
                val_str = str(val)
            # 截断超长输出，防止 token 超限
            if len(val_str) > 3000:
                val_str = val_str[:3000] + "\n...（内容已截断）"
            result_parts.append(f"[来源: {label}]\n{val_str}")

        results_text = "\n\n".join(result_parts)

        synthesis_prompt = self._build_answer_synthesis_prompt(
            agent=agent,
            task=task,
            results_text=results_text,
        )

        try:
            from app.llm_hub.inference import InferenceConfig
            # 答案合成阶段只基于已有执行结果组织自然语言，不再开放额外工具调用，
            # 避免模型在“总结阶段”继续发起无关工具循环，导致耗时和不稳定性上升。
            logger.debug(
                f"{Fore.CYAN}[执行引擎] 答案合成阶段禁用工具调用，"
                f"仅根据已收集结果生成最终回答{Style.RESET_ALL}"
            )
            
            config = InferenceConfig(
                model=agent.agent_config.execution_model,
                stream=False,
                temperature=0.3,   # 答案合成用低温度，减少幻觉
            )
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": synthesis_prompt}],
                config=config
            )
            answer = response.content.strip()
            logger.info(
                f"{Fore.GREEN}[执行引擎] LLM 答案合成完成，"
                f"长度: {len(answer)} 字符{Style.RESET_ALL}"
            )
            return answer

        except Exception as e:
            logger.error(
                f"{Fore.RED}[执行引擎] LLM 答案合成失败，回退到原始数据拼接: {e}{Style.RESET_ALL}"
            )
            # 合成失败时降级：把原始工具结果直接拼接返回
            return "\n\n".join(
                f"【{r.get('tool_name') or r.get('action', '')}】\n"
                + (_json.dumps(r["result"], ensure_ascii=False, indent=2, default=str)
                   if isinstance(r["result"], dict) else str(r["result"]))
                for r in tool_results
                if r.get("result")
            ) or template or "执行完成，但未能生成最终答案。"

    async def _synthesize_from_context(
        self,
        agent: Agent,
        task: str,
        context_messages: List[Dict[str, Any]],
    ) -> str:
        """
        【兜底合成】基于会话历史上下文（context_messages）用 LLM 直接生成答案。

        当计划只有 final_answer 一步（纯记忆问答场景），且 LLM 写了意图描述而非真实答案时，
        此方法作为兜底安全网被调用，利用注入的历史会话摘要让 LLM 给出真正的自然语言回答。

        设计原因：
        - 规划 Prompt 已要求 LLM 在情况A（无工具）时把 final_answer.content 写成真实答案
        - 但由于 LLM 惯性，仍可能写出意图描述（"根据历史记录回答..."）
        - 此方法作为最后防线，确保最终用户收到的是具体答案而非意图描述

        Args:
            agent: 当前执行的 Agent 实例
            task: 原始用户任务描述
            context_messages: 会话历史消息列表（含历史任务摘要等上下文）

        Returns:
            str: 基于历史上下文合成的自然语言答案
        """
        logger.info(
            f"{Fore.BLUE}[执行引擎] 开始基于会话历史上下文兜底合成答案，"
            f"上下文消息数量: {len(context_messages)}{Style.RESET_ALL}"
        )

        # 将历史上下文消息格式化为文本，供 LLM 参考
        context_text_parts = []
        for msg in context_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content:
                continue
            # 截断超长消息，防止 token 超限
            if len(str(content)) > 1500:
                content = str(content)[:1500] + "...(已截断)"
            if role == "system":
                context_text_parts.append(f"[系统上下文]\n{content}")
            elif role == "user":
                context_text_parts.append(f"[用户]\n{content}")
            elif role == "assistant":
                context_text_parts.append(f"[助手]\n{content}")

        context_text = "\n\n---\n\n".join(context_text_parts) if context_text_parts else "（无可用上下文）"

        synthesis_prompt = self._build_context_fallback_prompt(
            agent=agent,
            task=task,
            context_text=context_text,
        )

        try:
            from app.llm_hub.inference import InferenceConfig

            config = InferenceConfig(
                model=agent.agent_config.execution_model,
                stream=False,
                temperature=0.2,   # 记忆召回用极低温度，确保精准引用历史信息
            )
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": synthesis_prompt}],
                config=config
            )
            answer = response.content.strip()
            logger.info(
                f"{Fore.GREEN}[执行引擎] 兜底上下文合成完成，"
                f"答案长度: {len(answer)} 字符，"
                f"预览: {answer[:100]}{Style.RESET_ALL}"
            )
            return answer

        except Exception as e:
            logger.error(
                f"{Fore.RED}[执行引擎] 兜底上下文合成失败: {e}，"
                f"返回空结果{Style.RESET_ALL}"
            )
            return "抱歉，我无法根据历史记录找到相关信息，请重新描述您的问题。"

    def _extract_value_by_path(self, data: Any, path_expr: str) -> Any:
        """
        按点路径提取嵌套值（如 "content.url"、"results.0.title"）。

        设计目的：
        - 兼容 LLM 在计划中生成 `{{last_tool_result.content}}` 这类占位符；
        - 避免仅支持扁平 key，导致占位符无法替换而把字面量传给工具。
        """
        if data is None:
            return None
        if not path_expr:
            return data

        current = data
        for segment in str(path_expr).split("."):
            seg = segment.strip()
            if not seg:
                return None

            if isinstance(current, dict):
                if seg not in current:
                    return None
                current = current.get(seg)
                continue

            if isinstance(current, list):
                if not seg.isdigit():
                    return None
                idx = int(seg)
                if idx < 0 or idx >= len(current):
                    return None
                current = current[idx]
                continue

            if hasattr(current, seg):
                current = getattr(current, seg)
                continue

            return None

        return current

    def _resolve_placeholder_value(
        self,
        expression: str,
        placeholder_context: Dict[str, Any],
    ) -> tuple[bool, Any]:
        """
        解析单个占位符表达式。

        返回 (found, value)：
        - found=False: 表达式不在已知上下文中，保持原占位符不变
        - found=True: 识别到表达式，value 允许为 None（会替换为空字符串）
        """
        expr = str(expression or "").strip()
        if not expr:
            return False, None

        if expr in placeholder_context:
            return True, placeholder_context.get(expr)

        if "." in expr:
            root, nested = expr.split(".", 1)
            if root in placeholder_context:
                base_value = placeholder_context.get(root)
                return True, self._extract_value_by_path(base_value, nested)

        return False, None

    def _replace_placeholders_in_text(
        self,
        text: str,
        placeholder_context: Dict[str, Any],
    ) -> str:
        """
        替换文本中的占位符，支持以下格式：
        - {{last_tool_result}}
        - {{last_tool_result.content}}
        - {last_tool_result}
        - {last_tool_result.content}
        """
        if not isinstance(text, str) or not text:
            return text

        pattern = re.compile(
            r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\}\}"
            r"|\{([a-zA-Z_][a-zA-Z0-9_\.]*)\}"
        )

        def _replace(match: re.Match) -> str:
            expr = match.group(1) or match.group(2) or ""
            found, value = self._resolve_placeholder_value(expr, placeholder_context)
            if not found:
                return match.group(0)
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                try:
                    return _json.dumps(value, ensure_ascii=False, default=str)
                except Exception:
                    return str(value)
            return str(value)

        return pattern.sub(_replace, text)

    def _resolve_step_placeholders(
        self,
        step: PlanStep,
        prev_results: List[Dict[str, Any]]
    ) -> PlanStep:
        """
        解析并替换步骤参数中的占位符
        
        LLM 在规划阶段可能使用占位符（如 {{first_search_result_url}}）来引用前序步骤的结果。
        本方法在执行前将这些占位符替换为真实数据。
        
        支持的占位符格式：
        - {{first_search_result_url}} - 第一个搜索结果的 URL
        - {{first_search_result_title}} - 第一个搜索结果的标题
        - {{first_search_result}} - 第一个搜索结果的完整信息
        - {{last_tool_result}} - 最后一个工具的执行结果
        - {{last_tool_result_url}} - 最后一个工具结果中的 URL（如果存在）
        
        Args:
            step: 当前执行的计划步骤
            prev_results: 已完成步骤的结果列表
            
        Returns:
            PlanStep: 替换占位符后的步骤（副本）
        """
        import copy
        
        # 创建步骤的深拷贝，避免修改原始计划
        resolved_step = copy.deepcopy(step)
        
        # 获取前序步骤中有用的数据
        search_result_url = None
        search_result_title = None
        search_result_snippet = None
        last_tool_result = None
        
        for result in prev_results:
            if not result.get("success"):
                continue
            
            # 提取搜索结果信息
            if result.get("action") == "tool" and result.get("tool_name") == "search":
                tool_result = result.get("result", {})
                if isinstance(tool_result, dict):
                    results_list = tool_result.get("results", [])
                    if results_list:
                        first_result = results_list[0]
                        search_result_url = first_result.get("url")
                        search_result_title = first_result.get("title")
                        search_result_snippet = first_result.get("snippet")
            
            # 记录最后一个工具/技能结果，作为 {{last_tool_result}} 的替换来源
            # NOTE: 同时覆盖 skill 类型，是因为 LLM 经常规划 text_writing(skill) → file_write(tool) 的两步链。
            # 若只记录 action=="tool"，则 text_writing 的输出永远不会成为 last_tool_result，
            # 导致 file_write 步骤的 content 参数占位符被替换为空字符串，触发"文件内容不能为 None"错误。
            if result.get("action") in ("tool", "skill"):
                last_tool_result = result.get("result")
        
        # 如果没有搜索结果，检查是否可以从任何工具结果中提取 URL
        if not search_result_url and last_tool_result:
            if isinstance(last_tool_result, dict):
                search_result_url = last_tool_result.get("url") or last_tool_result.get("first_url")
        
        first_search_result = {
            "url": search_result_url,
            "title": search_result_title,
            "snippet": search_result_snippet
        } if search_result_url else None

        # 占位符上下文（支持扁平 key + 点路径扩展）
        placeholder_context = {
            "first_search_result_url": search_result_url or "",
            "first_search_result_title": search_result_title or "",
            "first_search_result_snippet": search_result_snippet or "",
            "first_search_result": first_search_result,
            "last_tool_result": last_tool_result,
            "last_tool_result_url": search_result_url or "",
        }
        
        # 对 params 中的每个参数进行占位符替换
        if hasattr(resolved_step, 'params') and resolved_step.params:
            for key, value in resolved_step.params.items():
                if isinstance(value, str):
                    original_value = value
                    value = self._replace_placeholders_in_text(value, placeholder_context)
                    
                    # 只有值发生变化时才记录日志
                    if original_value != value:
                        logger.info(
                            f"{Fore.GREEN}[占位符替换] 参数 '{key}': "
                            f"'{original_value[:80]}' -> '{value[:80]}'{Style.RESET_ALL}"
                        )
                    
                    resolved_step.params[key] = value
                elif isinstance(value, dict):
                    # 递归处理字典类型的参数值
                    resolved_step.params[key] = self._resolve_dict_placeholders(
                        value,
                        placeholder_context
                    )
        
        return resolved_step

    def _resolve_dict_placeholders(
        self,
        data: Any,
        replacements
    ) -> Any:
        """
        递归解析字典中的占位符
        
        Args:
            data: 需要处理的数据（可能是 dict, list, str 等）
            replacements: 占位符上下文（dict）或旧版替换对（list of tuples）
            
        Returns:
            处理后的数据
        """
        # 兼容旧参数格式：[( "{{last_tool_result}}", "xxx"), ...]
        if isinstance(replacements, dict):
            placeholder_context = dict(replacements)
        else:
            placeholder_context = {}
            for item in replacements or []:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    continue
                raw_key, raw_value = item[0], item[1]
                key = str(raw_key or "").strip()
                m = re.fullmatch(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\}\}", key)
                if not m:
                    m = re.fullmatch(r"\{([a-zA-Z_][a-zA-Z0-9_\.]*)\}", key)
                if m:
                    placeholder_context[m.group(1)] = raw_value
        
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                result[key] = self._resolve_dict_placeholders(value, placeholder_context)
            return result
        elif isinstance(data, list):
            return [self._resolve_dict_placeholders(item, placeholder_context) for item in data]
        elif isinstance(data, str):
            return self._replace_placeholders_in_text(data, placeholder_context)
        else:
            return data

    async def _execute_step(
        self,
        agent: Agent,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None,
        parent_plan: Optional[Any] = None,
        step_index: int = 0
    ) -> Dict[str, Any]:
        """
        执行单个步骤

        Args:
            agent: Agent 实例
            step: 计划步骤
            context: 执行上下文
            prev_results: 本轮已完成步骤的结果列表，供 skill 等引用真实数据
            parent_plan: 当前步骤所属的父计划对象（含 steps 列表），
                         用于让 delegate 步骤感知后续步骤以实现「计划感知」需求检查。
                         设计上以 Optional[Any] 类型接收，兼容不同 Plan 实现。
            step_index: 当前步骤在 parent_plan.steps 中的 0-based 索引，
                        用于计算剩余步骤列表 (remaining_steps = plan.steps[step_index+1:])

        Returns:
            Dict[str, Any]: 步骤执行结果
        """
        try:
            if step.action == "tool":
                # NOTE: 必须传入 context，否则 SpawnAgentTool / MessageAgentTool 等
                #       需要运行时注入 stream_callback 的工具将以 None 回调执行，
                #       导致子 Agent 事件无法推入 SSE 流、用户确认弹窗无法展示。
                return await self._execute_tool(step, agent, context)
            elif step.action == "skill":
                return await self._execute_skill(step, context, agent, prev_results)
            elif step.action == "delegate":
                # ── 计算当前步骤之后的剩余步骤（不含当前步骤） ────────────────
                # 目的：让 _delegate_to_agent 的需求完整性检查能「感知」父计划
                #       后续步骤已覆盖的能力，避免越权注入导致子 Agent 执行范围膨胀。
                # 通用设计：remaining_steps 携带的是完整 PlanStep 对象列表，
                #          _delegate_to_agent 内部的检查方法可以自由访问 action/params。
                remaining_steps = []
                if parent_plan and hasattr(parent_plan, 'steps'):
                    remaining_steps = parent_plan.steps[step_index + 1:]
                    if remaining_steps:
                        logger.debug(
                            f"{Fore.BLUE}[执行引擎] delegate 步骤后还有 {len(remaining_steps)} "
                            f"个后续步骤，将传递给需求完整性检查以避免越权注入{Style.RESET_ALL}"
                        )
                return await self._delegate_to_agent(step, context, prev_results, remaining_steps)
            elif step.action == "final_answer":
                return {
                    "success": True,
                    "result": step.params.get("content", ""),
                    "action": "final_answer"
                }
            else:
                # ── 兜底兼容：LLM 有时把工具名直接写成 action（如 "database_query"）
                # 检查 action 值是否是已注册的工具名，若是则自动修正为 action="tool"
                if self.tool_hub and self.tool_hub.get_tool(step.action):
                    original_action = step.action
                    logger.warning(
                        f"{Fore.YELLOW}[兼容] LLM 将工具名 '{original_action}' "
                        f"误用为 action 类型，自动修正为 action='tool'{Style.RESET_ALL}"
                    )
                    # 若 params 中没有 tool_name 则补充（有的话直接用）
                    if "tool_name" not in step.params:
                        step.params["tool_name"] = original_action
                    step.action = "tool"
                    # 同样传入 context，保证兜底路径下工具也能获得运行时上下文
                    return await self._execute_tool(step, agent, context)
                
                logger.warning(
                    f"{Fore.YELLOW}未知的 action 类型: {step.action}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": f"未知的 action 类型: {step.action}"
                }
                
        except Exception as e:
            logger.error(
                f"{Fore.RED}执行步骤时发生错误 (action={step.action}): {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error": str(e),
                "action": step.action
            }
    
    async def _execute_tool(
        self,
        step: PlanStep,
        agent: Optional[Agent] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行工具调用

        Args:
            step:    计划步骤
            agent:   当前 Agent 实例（用于授权校验）
            context: 执行上下文（含 stream_callback / pending_confirmations 等运行时依赖）
                     对于 SpawnAgentTool、MessageAgentTool 等需要运行时注入的工具，
                     必须传入此参数，否则这类工具无法正确推送 SSE 事件。

        Returns:
            Dict[str, Any]: 执行结果

        NOTE 运行时上下文注入机制：
             部分工具（如 spawn_agent、send_message）在注册到 ToolHub 时尚无 stream_callback，
             需要在每次调用前通过 update_context() 注入当前执行上下文。
             本方法通过鸭子类型检测工具是否有 update_context 方法：
               - 有 → 在调用 execute() 前先注入 stream_callback / pending_confirmations
               - 无 → 普通工具，直接调用即可
        """
        tool_name = step.params.get("tool_name")
        params = step.params.get("params", {})

        logger.info(
            f"{Fore.CYAN}[执行工具] 准备调用工具: {tool_name} "
            f"| context={'已传入' if context else '未传入'}"
            f" | pending_user_inputs={'已传入' if context and context.get('pending_user_inputs') is not None else '未传入'}"
            f"{Style.RESET_ALL}"
        )

        # ── 工具授权校验 ──────────────────────────────────────────
        # 若 agent 声明了 available_tools（非空），则只允许使用授权内的工具
        if agent and agent.available_tools and tool_name not in agent.available_tools:
            error_msg = (
                f"Agent '{agent.name}' 无权使用工具 '{tool_name}'。"
                f"该 Agent 仅授权以下工具: {agent.available_tools}。"
                f"如需使用 '{tool_name}'，请委派给有该工具权限的子 Agent。"
            )
            logger.warning(f"{Fore.YELLOW}[权限拦截] {error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name
            }
        
        # 检查工具是否存在（无论走网关还是直接调用都需要先验证）
        tool = self.tool_hub.get_tool(tool_name)
        if not tool:
            error_msg = f"工具不存在: {tool_name}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name
            }

        # ── 运行时上下文注入（context-aware 工具专用）────────────────────────
        # 工具如 spawn_agent / send_message 在注册时没有 stream_callback，
        # 每次调用前需要通过 update_context() 注入当前执行环境的运行时依赖：
        #   - stream_callback:      SSE 事件推送回调（子 Agent 事件透传给前端）
        #   - pending_confirmations: 挂起确认映射表（/agents/confirm 接口能找到对应确认）
        #   - pending_user_inputs:   挂起用户输入映射表（/agents/input 接口能找到对应输入）
        #   - user_rejected_tools:  已拒绝工具黑名单（子 Agent 回避重复尝试）
        # 通过鸭子类型检测 update_context，避免对工具类名硬编码（扩展性更强）
        # 注意：使用 `is not None` 判断，避免空字典被误判为未传入
        if context and hasattr(tool, "update_context") and callable(tool.update_context):
            _stream_cb       = context.get("stream_callback")
            _pending_confs  = context.get("pending_confirmations")
            _pending_inputs = context.get("pending_user_inputs")
            _rejected_tools = context.get("user_rejected_tools")
            # NOTE: 注入任务内用户输入缓存引用，供工具实现独立的缓存读写，
            # 防止同一任务内反复向用户询问 SMTP 等配置。
            # 从 run_memory 获取 user_inputs_cache 引用（共享内存，不复制）
            _run_memory = context.get("run_memory")
            _user_inputs_cache = _run_memory.user_inputs_cache if _run_memory is not None else None
            tool.update_context(
                stream_callback       = _stream_cb,
                pending_confirmations = _pending_confs,
                pending_user_inputs   = _pending_inputs,
                user_rejected_tools   = _rejected_tools,
                user_inputs_cache     = _user_inputs_cache,
            )
            logger.info(
                f"{Fore.GREEN}[执行工具] 已为工具 '{tool_name}' 注入运行时上下文 "
                f"| stream_callback={'✅ 已注入' if _stream_cb else '❌ 未传入，子Agent事件将无法推流'} "
                f"| pending_confirmations={'✅ 已注入' if _pending_confs is not None else '⚠️ 未传入'} "
                f"| pending_user_inputs={'✅ 已注入' if _pending_inputs is not None else '⚠️ 未传入'} "
                f"| user_inputs_cache={'✅ 已注入' if _user_inputs_cache is not None else '⚠️ 未传入'}{Style.RESET_ALL}"
            )
        elif tool_name in ("spawn_agent", "send_message") and not context:
            # 对已知需要上下文的工具，发出明确警告
            logger.warning(
                f"{Fore.YELLOW}[执行工具⚠️] 工具 '{tool_name}' 需要运行时上下文（stream_callback 等），"
                f"但调用时未传入 context！子 Agent 的 SSE 事件将无法推入当前流。"
                f"请确保 _execute_step 正确传入 context 参数。{Style.RESET_ALL}"
            )

        # ── 路径一：通过 ToolCallingGateway 执行（推荐路径）─────────────────
        # 当网关已配置时，所有工具调用统一走网关，享受：
        #   - 参数 JSON Schema 校验（防止非法参数进入工具）
        #   - 超时控制（避免工具阻塞整个 Agent 流程）
        #   - 执行统计（call_count / success_rate / avg_time 等）
        #   - 统一错误处理和日志追踪
        if self.tool_gateway:
            try:
                logger.info(
                    f"{Fore.BLUE}[执行引擎→网关] 通过 ToolCallingGateway 执行工具: "
                    f"{tool_name}{Style.RESET_ALL}"
                )
                # 调用网关的直接执行方法（规划执行模式专用，无需构造 LLM 格式响应）
                from app.llm_hub.tool_gateway import ToolCallStatus
                gateway_result = await self.tool_gateway.execute_direct_tool_call(
                    tool_name=tool_name,
                    arguments=params,
                    context=context
                )
                
                if gateway_result.status == ToolCallStatus.SUCCESS:
                    logger.info(
                        f"{Fore.GREEN}[执行引擎←网关] 工具 {tool_name} 执行成功，"
                        f"耗时: {gateway_result.execution_time_ms:.2f}ms{Style.RESET_ALL}"
                    )
                    
                    # ── 检测工具是否需要用户输入 ────────────────────────────────
                    # 检查工具返回结果中是否包含 "needs_user_input" 标记
                    result = gateway_result.result
                    # 业务级失败透传：工具正常返回，但 payload 标记 success=false（如 file_write/base64 失败）
                    if isinstance(result, dict) and result.get("success") is False:
                        business_error = self._build_tool_business_error(tool_name, result)
                        logger.warning(
                            f"{Fore.YELLOW}[执行工具-网关路径] 工具 {tool_name} 业务失败: "
                            f"{business_error}{Style.RESET_ALL}"
                        )
                        return {
                            "success": False,
                            "error": business_error,
                            "result": result,
                            "action": "tool",
                            "tool_name": tool_name,
                            "execution_time_ms": gateway_result.execution_time_ms
                        }
                    if result and isinstance(result, dict) and result.get("needs_user_input"):
                        logger.info(
                            f"{Fore.CYAN}[执行工具-网关路径] 工具 {tool_name} 需要用户额外输入，"
                            f"准备请求用户输入{Style.RESET_ALL}"
                        )
                        # 获取用户输入请求的详细信息
                        user_input_request = result.get("user_input_request", {})
                        required_fields = user_input_request.get("required_fields", [])
                        prompt_message = user_input_request.get("message", "请提供以下信息")
                        
                        # 优先从工具返回结果中获取 _pending_user_inputs（这是工具实际持有的引用）
                        tool_pending_user_inputs = result.get("_pending_user_inputs")
                        
                        # 调用等待用户输入（会暂停执行直到用户输入）
                        user_inputs = await self._wait_for_user_input(
                            tool_name=tool_name,
                            required_fields=required_fields,
                            prompt_message=prompt_message,
                            context=context,
                            pending_user_inputs=tool_pending_user_inputs,
                            iteration=context.get("iteration", 0) if context else 0
                        )
                        
                        # 用户输入已获取，将用户输入注入到工具参数中，重新执行
                        if user_inputs:
                            logger.info(
                                f"{Fore.GREEN}[执行工具-网关路径] 已获取用户输入，"
                                f"重新执行工具 {tool_name}{Style.RESET_ALL}"
                            )
                            # 合并用户输入到原始参数
                            merged_params = {**params, **user_inputs}
                            
                            # 合并 context，确保重试执行时也能访问 pending_user_inputs
                            retry_context = {**context} if context else {}
                            if tool_pending_user_inputs:
                                retry_context["pending_user_inputs"] = tool_pending_user_inputs

                            # 重新通过网关执行工具
                            retry_result = await self.tool_gateway.execute_direct_tool_call(
                                tool_name=tool_name,
                                arguments=merged_params,
                                context=retry_context
                            )
                            
                            if retry_result.status == ToolCallStatus.SUCCESS:
                                retry_payload = retry_result.result
                                if isinstance(retry_payload, dict) and retry_payload.get("success") is False:
                                    business_error = self._build_tool_business_error(tool_name, retry_payload)
                                    return {
                                        "success": False,
                                        "error": business_error,
                                        "result": retry_payload,
                                        "action": "tool",
                                        "tool_name": tool_name,
                                        "execution_time_ms": retry_result.execution_time_ms
                                    }
                                return {
                                    "success": True,
                                    "result": retry_payload,
                                    "action": "tool",
                                    "tool_name": tool_name,
                                    "user_inputs_provided": user_inputs,
                                    "execution_time_ms": retry_result.execution_time_ms
                                }
                            else:
                                error_msg = f"工具 {tool_name} 重新执行失败: {retry_result.error}"
                                return {
                                    "success": False,
                                    "error": error_msg,
                                    "action": "tool",
                                    "tool_name": tool_name
                                }
                        else:
                            # 用户取消输入或超时
                            return {
                                "success": False,
                                "error": "用户取消输入或输入超时",
                                "action": "tool",
                                "tool_name": tool_name,
                                "user_input_cancelled": True
                            }
                    
                    return {
                        "success": True,
                        "result": result,
                        "action": "tool",
                        "tool_name": tool_name,
                        # 附加网关统计信息，供调试和监控使用
                        "execution_time_ms": gateway_result.execution_time_ms
                    }
                else:
                    error_msg = (
                        f"工具 {tool_name} 通过网关执行失败 "
                        f"(status={gateway_result.status.value}): {gateway_result.error}"
                    )
                    logger.warning(f"{Fore.YELLOW}{error_msg}{Style.RESET_ALL}")
                    return {
                        "success": False,
                        "error": error_msg,
                        "action": "tool",
                        "tool_name": tool_name
                    }
            except Exception as e:
                # 网关执行出现意外异常时，降级到直接调用，保证 Agent 流程不中断
                logger.warning(
                    f"{Fore.YELLOW}[执行引擎] 网关执行异常，降级为直接调用: {e}{Style.RESET_ALL}"
                )
                # 降级执行（fall-through 到下面的直接调用代码）
                try:
                    result = await tool.execute(params)
                    logger.info(
                        f"{Fore.GREEN}[执行引擎] 工具 {tool_name} 降级直接调用成功{Style.RESET_ALL}"
                    )
                    return {
                        "success": True,
                        "result": result,
                        "action": "tool",
                        "tool_name": tool_name
                    }
                except Exception as fallback_e:
                    error_msg = f"工具 {tool_name} 降级执行也失败: {fallback_e}"
                    logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
                    return {
                        "success": False,
                        "error": str(fallback_e),
                        "action": "tool",
                        "tool_name": tool_name
                    }
        
        # ── 路径二：直接调用（未配置网关时的降级路径）────────────────────────
        try:
            result = await tool.execute(params)
            logger.info(f"{Fore.GREEN}工具 {tool_name} 执行成功{Style.RESET_ALL}")
            # 业务级失败透传：避免“调用成功”掩盖工具真实失败
            if isinstance(result, dict) and result.get("success") is False:
                business_error = self._build_tool_business_error(tool_name, result)
                logger.warning(
                    f"{Fore.YELLOW}[执行工具] 工具 {tool_name} 业务失败: "
                    f"{business_error}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": business_error,
                    "result": result,
                    "action": "tool",
                    "tool_name": tool_name
                }
            
            # ── 检测工具是否需要用户输入 ────────────────────────────────
            # 检查工具返回结果中是否包含 "needs_user_input" 标记
            # 如果是，暂停执行并向用户请求额外信息
            if result and isinstance(result, dict) and result.get("needs_user_input"):
                logger.info(
                    f"{Fore.CYAN}[执行工具] 工具 {tool_name} 需要用户额外输入，"
                    f"准备请求用户输入{Style.RESET_ALL}"
                )
                # 获取用户输入请求的详细信息
                user_input_request = result.get("user_input_request", {})
                required_fields = user_input_request.get("required_fields", [])
                prompt_message = user_input_request.get("message", "请提供以下信息")
                
                # 优先从工具返回结果中获取 _pending_user_inputs（这是工具实际持有的引用）
                tool_pending_user_inputs = result.get("_pending_user_inputs")
                
                # 调用等待用户输入（会暂停执行直到用户输入）
                user_inputs = await self._wait_for_user_input(
                    tool_name=tool_name,
                    required_fields=required_fields,
                    prompt_message=prompt_message,
                    context=context,
                    pending_user_inputs=tool_pending_user_inputs,
                    iteration=context.get("iteration", 0) if context else 0
                )
                
                # 用户输入已获取，将用户输入注入到工具参数中，重新执行
                if user_inputs:
                    logger.info(
                        f"{Fore.GREEN}[执行工具] 已获取用户输入，"
                        f"重新执行工具 {tool_name}{Style.RESET_ALL}"
                    )
                    # 合并用户输入到原始参数
                    merged_params = {**params, **user_inputs}
                    
                    # 重新执行工具
                    try:
                        result = await tool.execute(merged_params)
                        logger.info(
                            f"{Fore.GREEN}工具 {tool_name} 重新执行成功{Style.RESET_ALL}"
                        )
                        if isinstance(result, dict) and result.get("success") is False:
                            business_error = self._build_tool_business_error(tool_name, result)
                            return {
                                "success": False,
                                "error": business_error,
                                "result": result,
                                "action": "tool",
                                "tool_name": tool_name
                            }
                        return {
                            "success": True,
                            "result": result,
                            "action": "tool",
                            "tool_name": tool_name,
                            "user_inputs_provided": user_inputs  # 记录用户提供的输入
                        }
                    except Exception as retry_e:
                        error_msg = f"工具 {tool_name} 重新执行失败: {retry_e}"
                        logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
                        return {
                            "success": False,
                            "error": error_msg,
                            "action": "tool",
                            "tool_name": tool_name
                        }
                else:
                    # 用户取消输入或超时
                    return {
                        "success": False,
                        "error": "用户取消输入或输入超时",
                        "action": "tool",
                        "tool_name": tool_name,
                        "user_input_cancelled": True
                    }
            
            return {
                "success": True,
                "result": result,
                "action": "tool",
                "tool_name": tool_name
            }
        except Exception as e:
            error_msg = f"工具 {tool_name} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "tool",
                "tool_name": tool_name
            }

    async def _wait_for_user_input(
        self,
        tool_name: str,
        required_fields: List[Dict[str, Any]],
        prompt_message: str,
        context: Optional[Dict[str, Any]],
        pending_user_inputs: Optional[Dict[str, Any]] = None,
        iteration: int = 0
    ) -> Optional[Dict[str, Any]]:
        """
        暂停执行，等待用户输入额外信息

        Args:
            tool_name: 需要用户输入的工具名称
            required_fields: 需要用户提供的字段列表
            prompt_message: 提示用户的信息
            context: 执行上下文
            iteration: 当前迭代次数

        Returns:
            用户输入的字典，如果用户取消或超时则返回 None
        """
        import uuid
        import asyncio

        # 获取 stream_callback
        stream_callback = context.get("stream_callback") if context else None
        
        # 优先使用传入的 pending_user_inputs，否则从 context 获取
        actual_pending_user_inputs = pending_user_inputs
        if actual_pending_user_inputs is None:
            actual_pending_user_inputs = context.get("pending_user_inputs") if context else None

        # 使用 is not None 判断，避免空字典被误判
        if not stream_callback or actual_pending_user_inputs is None:
            logger.warning(
                f"{Fore.YELLOW}[等待用户输入] 缺少 stream_callback 或 pending_user_inputs，"
                f"stream_callback={'已传入' if stream_callback else '未传入'}, "
                f"pending_user_inputs={'已传入' if actual_pending_user_inputs is not None else '未传入'}，"
                f"无法请求用户输入{Style.RESET_ALL}"
            )
            return None
        
        # 生成唯一的输入请求 ID
        input_request_id = str(uuid.uuid4())
        
        # 推送 await_user_input 事件到前端
        await self._emit_stream_event(
            stream_callback,
            event_type="await_user_input",
            iteration=iteration,
            data={
                "input_request_id": input_request_id,
                "tool_name": tool_name,
                "required_fields": required_fields,
                "message": prompt_message
            }
        )
        
        # 创建 asyncio.Event 等待用户输入
        input_event = asyncio.Event()
        actual_pending_user_inputs[input_request_id] = {
            "event": input_event,
            "inputs": None  # 用户输入的字典
        }
        
        logger.info(
            f"{Fore.CYAN}[等待用户输入] 已发送输入请求，"
            f"input_request_id={input_request_id}，等待用户输入...{Style.RESET_ALL}"
        )
        
        try:
            # 等待用户输入，最多 300 秒超时
            await asyncio.wait_for(input_event.wait(), timeout=300)
            user_inputs = actual_pending_user_inputs[input_request_id].get("inputs")
        except asyncio.TimeoutError:
            logger.warning(
                f"{Fore.YELLOW}[等待用户输入] 用户输入超时 "
                f"(input_request_id={input_request_id}){Style.RESET_ALL}"
            )
            user_inputs = None
        finally:
            # 清理挂起的输入请求
            actual_pending_user_inputs.pop(input_request_id, None)

        # NOTE: 关键逻辑：将用户输入写入任务内缓存
        # 当用户通过 await_user_input 弹窗提交 SMTP/DB 配置后，
        # 这里负责将配置写入 AgentRunMemory.user_inputs_cache，
        # 同一任务内后续的 python_executor 调用可直接从缓存读取配置，不再弹窗。
        if user_inputs and isinstance(user_inputs, dict) and context:
            run_memory = context.get("run_memory")
            if run_memory is not None and hasattr(run_memory, "write_user_inputs_cache"):
                # 识别 SMTP 相关字段
                smtp_fields = {
                    k: v for k, v in user_inputs.items()
                    if k in ("smtp_server", "smtp_port", "sender_email", "sender_password")
                    and v is not None and str(v).strip()
                }
                if smtp_fields:
                    run_memory.write_user_inputs_cache("smtp_config", smtp_fields)
                    logger.info(
                        f"{Fore.GREEN}[待用户输入] ✅ 已将 SMTP 配置写入任务内缓存，"
                        f"字段={list(smtp_fields.keys())}{Style.RESET_ALL}"
                    )
                # 识别数据库相关字段
                db_fields = {
                    k: v for k, v in user_inputs.items()
                    if k in ("db_host", "db_port", "db_name", "db_user", "db_password")
                    and v is not None and str(v).strip()
                }
                if db_fields:
                    run_memory.write_user_inputs_cache("db_config", db_fields)
                    logger.info(
                        f"{Fore.GREEN}[待用户输入] ✅ 已将 DB 配置写入任务内缓存，"
                        f"字段={list(db_fields.keys())}{Style.RESET_ALL}"
                    )
        
        # 推送用户输入已接收事件
        await self._emit_stream_event(
            stream_callback,
            event_type="user_input_received",
            iteration=iteration,
            data={
                "input_request_id": input_request_id,
                "tool_name": tool_name,
                "has_inputs": user_inputs is not None
            }
        )
        
        return user_inputs
    
    async def _emit_stream_event(
        self,
        stream_callback: Optional[Callable],
        event_type: str,
        iteration: int = 0,
        data: Optional[Dict[str, Any]] = None
    ):
        """发送流式事件的辅助方法"""
        import time
        if stream_callback is None:
            return
        
        event = {
            "event": event_type,
            "iteration": iteration,
            "timestamp": time.time() * 1000,
        }
        if data is not None:
            event["data"] = data
        
        try:
            import asyncio
            if asyncio.iscoroutinefunction(stream_callback):
                await stream_callback(event)
            else:
                stream_callback(event)
        except Exception as e:
            logger.warning(f"{Fore.YELLOW}[流式事件] 发送事件失败: {e}{Style.RESET_ALL}")

    def _resolve_skill_working_dir(self, skill) -> Optional[Path]:
        """
        解析技能目录绝对路径。
        """
        source_path = getattr(skill, "source_path", None)
        if not source_path:
            return None
        try:
            return Path(source_path).resolve().parent
        except Exception as exc:
            logger.warning(
                f"{Fore.YELLOW}[执行引擎] 解析技能目录失败 | "
                f"source_path={source_path} | error={exc}{Style.RESET_ALL}"
            )
            return None

    async def _invoke_skill_internal_tool(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any],
        agent: Optional[Agent],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        在技能前置流程中直接调用工具。

        设计说明：
        - 技能运行时依赖的预检/安装属于执行引擎职责，不应再让 LLM 自己“先想出一条安装命令”；
        - 但仍要复用统一的工具授权、网关、日志和上下文注入逻辑；
        - 因此这里构造一个轻量的 tool step，走现有 _execute_tool 通道。
        """
        user_rejected_tools = {
            str(item).strip()
            for item in ((context or {}).get("user_rejected_tools") or [])
            if isinstance(item, str) and str(item).strip()
        }
        if tool_name in user_rejected_tools:
            error_msg = (
                f"用户已拒绝工具 '{tool_name}'，执行引擎不会在技能前置依赖处理中再次调用它。"
            )
            logger.warning(
                f"{Fore.YELLOW}[执行引擎] 技能前置工具调用被拒绝 | "
                f"tool={tool_name}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name,
            }

        synthetic_step = PlanStep(
            action="tool",
            tool_name=tool_name,
            params=params,
        )
        return await self._execute_tool(
            step=synthetic_step,
            agent=agent,
            context=context,
        )

    def _build_dependency_check_command(
        self,
        *,
        dependency,
    ) -> Optional[str]:
        """
        生成运行时依赖的检查命令。
        """
        if dependency.check_command:
            return dependency.check_command

        dep_type = str(getattr(dependency, "type", "") or "").strip().lower()
        packages = [
            str(pkg).strip()
            for pkg in (getattr(dependency, "packages", []) or [])
            if str(pkg).strip()
        ]
        if dep_type == "npm" and packages:
            js_statements = ";".join(
                f"require.resolve({_json.dumps(pkg, ensure_ascii=False)})"
                for pkg in packages
            )
            return f"node -e {shlex.quote(js_statements)}"

        return None

    def _build_dependency_install_command(
        self,
        *,
        dependency,
    ) -> Optional[str]:
        """
        生成运行时依赖的安装命令。
        """
        if dependency.install_command:
            return dependency.install_command

        dep_type = str(getattr(dependency, "type", "") or "").strip().lower()
        packages = [
            str(pkg).strip()
            for pkg in (getattr(dependency, "packages", []) or [])
            if str(pkg).strip()
        ]
        if dep_type == "npm" and packages:
            quoted_packages = " ".join(shlex.quote(pkg) for pkg in packages)
            return f"npm install --no-save {quoted_packages}"

        return None

    async def _ensure_skill_runtime_dependencies(
        self,
        *,
        skill,
        skill_id: str,
        agent: Optional[Agent],
        context: Optional[Dict[str, Any]],
    ) -> tuple[bool, List[str], Optional[str]]:
        """
        技能执行前的依赖预检与自动安装。

        返回：
        - success: 是否全部就绪
        - messages: 依赖处理摘要（会追加到技能 Prompt，帮助模型理解当前环境）
        - error: 失败原因（仅 success=False 时有值）
        """
        runtime_dependencies = list(getattr(skill, "runtime_dependencies", []) or [])
        if not runtime_dependencies:
            return True, [], None

        skill_dir = self._resolve_skill_working_dir(skill)
        if skill_dir is None:
            error_msg = (
                f"技能 {skill_id} 声明了 runtime_dependencies，但 source_path 缺失，"
                "无法确定依赖安装目录。"
            )
            return False, [], error_msg

        summaries: List[str] = []
        for dependency in runtime_dependencies:
            dep_type = str(getattr(dependency, "type", "") or "").strip().lower()
            tool_name = (
                str(getattr(dependency, "tool_name", "") or "").strip()
                or "shell_exec"
            )
            dep_label = (
                getattr(dependency, "description", "") or
                (", ".join(getattr(dependency, "packages", []) or [])) or
                dep_type or
                "未命名依赖"
            )

            raw_working_dir = str(getattr(dependency, "working_dir", ".") or ".").strip() or "."
            working_dir = (
                Path(raw_working_dir).expanduser()
                if Path(raw_working_dir).is_absolute()
                else (skill_dir / raw_working_dir).resolve()
            )
            timeout = int(getattr(dependency, "timeout_seconds", 180) or 180)
            env = dict(getattr(dependency, "env", {}) or {})

            logger.info(
                f"{Fore.CYAN}[技能依赖] 开始预检运行时依赖 | "
                f"skill={skill_id} | type={dep_type} | tool={tool_name} | "
                f"working_dir={working_dir}{Style.RESET_ALL}"
            )

            if dep_type not in {"npm", "shell"}:
                error_msg = (
                    f"技能 {skill_id} 声明了暂不支持的 runtime_dependency.type='{dep_type}'。"
                    "当前仅支持 npm / shell。"
                )
                logger.warning(
                    f"{Fore.YELLOW}[技能依赖] {error_msg}{Style.RESET_ALL}"
                )
                return False, summaries, error_msg

            check_command = self._build_dependency_check_command(dependency=dependency)
            install_command = self._build_dependency_install_command(dependency=dependency)
            if not check_command:
                error_msg = (
                    f"技能 {skill_id} 的依赖 '{dep_label}' 缺少可执行的检查命令。"
                )
                return False, summaries, error_msg
            if not install_command:
                error_msg = (
                    f"技能 {skill_id} 的依赖 '{dep_label}' 缺少可执行的安装命令。"
                )
                return False, summaries, error_msg

            check_params = {
                "command": check_command,
                "working_dir": str(working_dir),
                "timeout": timeout,
                "env": env,
            }
            check_result = await self._invoke_skill_internal_tool(
                tool_name=tool_name,
                params=check_params,
                agent=agent,
                context=context,
            )
            if check_result.get("success"):
                summaries.append(f"- 依赖已就绪：{dep_label}")
                logger.info(
                    f"{Fore.GREEN}[技能依赖] 依赖已存在，无需安装 | "
                    f"skill={skill_id} | dep={dep_label}{Style.RESET_ALL}"
                )
                continue

            logger.warning(
                f"{Fore.YELLOW}[技能依赖] 检查发现依赖缺失，准备自动安装 | "
                f"skill={skill_id} | dep={dep_label} | reason={check_result.get('error')}{Style.RESET_ALL}"
            )

            install_params = {
                "command": install_command,
                "working_dir": str(working_dir),
                "timeout": timeout,
                "env": env,
            }
            install_result = await self._invoke_skill_internal_tool(
                tool_name=tool_name,
                params=install_params,
                agent=agent,
                context=context,
            )
            if not install_result.get("success"):
                error_msg = (
                    f"技能 {skill_id} 自动安装运行时依赖失败: {dep_label}。"
                    f"检查命令={check_command}；安装命令={install_command}；"
                    f"原因={install_result.get('error')}"
                )
                logger.error(
                    f"{Fore.RED}[技能依赖] {error_msg}{Style.RESET_ALL}"
                )
                return False, summaries, error_msg

            recheck_result = await self._invoke_skill_internal_tool(
                tool_name=tool_name,
                params=check_params,
                agent=agent,
                context=context,
            )
            if not recheck_result.get("success"):
                error_msg = (
                    f"技能 {skill_id} 已尝试自动安装依赖 '{dep_label}'，"
                    "但安装后复检仍未通过。"
                    f"检查命令={check_command}；安装命令={install_command}；"
                    f"原因={recheck_result.get('error')}"
                )
                logger.error(
                    f"{Fore.RED}[技能依赖] {error_msg}{Style.RESET_ALL}"
                )
                return False, summaries, error_msg

            summaries.append(f"- 已自动安装并校验通过：{dep_label}")
            logger.info(
                f"{Fore.GREEN}[技能依赖] 自动安装成功 | "
                f"skill={skill_id} | dep={dep_label}{Style.RESET_ALL}"
            )

        return True, summaries, None
    
    async def _execute_skill(
        self,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        agent: Optional[Agent] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行技能调用

        Args:
            step: 计划步骤
            context: 执行上下文
            agent: 当前 Agent 实例
            prev_results: 本轮已完成步骤的结果列表，用于向 skill 注入真实数据

        Returns:
            Dict[str, Any]: 执行结果
        """
        skill_id = step.params.get("skill_id")
        params = step.params.get("params", {})
        
        # ====== 【调试日志】显示技能调用前的参数 ======
        logger.info(f"{Fore.CYAN}调用技能: {skill_id}, 原始参数: {params}{Style.RESET_ALL}")

        # 受限技能调用门禁（执行阶段兜底，防止误调用高影响技能）
        allowed, denied_reason = self._check_restricted_skill_invocation(
            skill_id=skill_id,
            context=context,
            params=params,
        )
        if not allowed:
            logger.warning(
                f"{Fore.YELLOW}[执行引擎] 已拦截受限技能调用 | skill={skill_id} | "
                f"reason={denied_reason}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error": denied_reason,
                "action": "skill",
                "skill_id": skill_id
            }
        
        # 获取技能
        skill = self.skill_manager.get_skill(skill_id)
        if not skill:
            error_msg = f"技能不存在: {skill_id}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "skill",
                "skill_id": skill_id
            }
        
        # 执行技能（通过 LLM）
        try:
            # 1. 准备参数，添加默认值以增强鲁棒性
            safe_params = params.copy()
            
            # ── 将前序步骤的真实数据注入 skill 参数 ────────────────
            # LLM 在规划阶段无法知道工具结果，skill 的 data/content 往往是描述文字。
            # 如果存在真实的工具/委派执行结果，用它们替换或补充 skill 的数据输入。
            if prev_results:
                real_data_parts = []
                for r in prev_results:
                    if not (r.get("success") and r.get("result")):
                        continue
                    label = r.get("tool_name") or r.get("agent_id") or r.get("action", "")
                    val = r["result"]
                    if isinstance(val, dict):
                        val_str = _json.dumps(val, ensure_ascii=False, indent=2, default=str)
                    else:
                        val_str = str(val)
                    if len(val_str) > 2000:
                        val_str = val_str[:2000] + "\n...（已截断）"
                    real_data_parts.append(f"[{label}]\n{val_str}")
                
                if real_data_parts:
                    injected_data = "\n\n".join(real_data_parts)
                    
                    # ====== 【关键修复】先进行占位符替换 ======
                    # 将 params 中的所有占位符替换为真实数据
                    for key in safe_params:
                        if isinstance(safe_params[key], str):
                            original = safe_params[key]
                            # 先替换占位符（支持双花括号和单花括号格式）
                            for placeholder, replacement in [
                                ("{{last_tool_result}}", injected_data),
                                ("{last_tool_result}", injected_data),
                                ("{{first_search_result}}", injected_data),
                                ("{first_search_result}", injected_data),
                            ]:
                                if placeholder in safe_params[key]:
                                    safe_params[key] = safe_params[key].replace(placeholder, replacement)
                                    logger.info(
                                        f"{Fore.GREEN}[技能数据注入] 参数 '{key}': "
                                        f"'{original[:50]}...' 已替换为真实数据{Style.RESET_ALL}"
                                    )
                                    break  # 找到一个匹配就退出，避免重复替换
                    
                    # 对于需要数据输入的技能（data_analysis 等），用真实数据替换描述
                    if skill_id in ("data_analysis",):
                        safe_params["data"] = injected_data
                        logger.info(
                            f"{Fore.BLUE}[执行引擎] 向技能 {skill_id} 注入前序步骤真实数据"
                            f"（{len(real_data_parts)} 条）{Style.RESET_ALL}"
                        )
                    # 通用：若参数里有 content/topic/input/text 是简短描述，也追加真实数据
                    for key in ("content", "topic", "input", "text", "task", "source_text"):
                        if key in safe_params and isinstance(safe_params[key], str):
                            # 如果包含换行符，说明已经是长文本（可能是已替换的数据），不再追加
                            if "\n" not in safe_params[key] and len(safe_params[key]) < 200:
                                safe_params[key] = safe_params[key] + "\n\n" + injected_data
                                logger.info(
                                    f"{Fore.BLUE}[执行引擎] 向技能 {skill_id} 的参数 '{key}' "
                                    f"追加前序步骤真实数据{Style.RESET_ALL}"
                                )
                                break
            
            # 通用回退逻辑：如果缺 topic 用 content，反之亦然
            if "topic" not in safe_params and "content" in safe_params:
                safe_params["topic"] = safe_params["content"]
            if "content" not in safe_params and "topic" in safe_params:
                safe_params["content"] = safe_params["topic"]
                
            # 针对 text_writing 技能的特定默认值
            if skill_id == "text_writing":
                if "topic" not in safe_params:
                    safe_params["topic"] = "未指定主题"
                if "content_type" not in safe_params:
                    safe_params["content_type"] = "一般文本"
                if "style" not in safe_params:
                    safe_params["style"] = "清晰自然"
                if "word_count" not in safe_params:
                    safe_params["word_count"] = "适中"

            skill_dir = self._resolve_skill_working_dir(skill)
            dependency_ok, dependency_messages, dependency_error = (
                await self._ensure_skill_runtime_dependencies(
                    skill=skill,
                    skill_id=skill_id,
                    agent=agent,
                    context=context,
                )
            )
            if not dependency_ok:
                logger.warning(
                    f"{Fore.YELLOW}[执行引擎] 技能前置依赖未满足 | "
                    f"skill={skill_id} | error={dependency_error}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": dependency_error,
                    "action": "skill",
                    "skill_id": skill_id,
                }

            # 2. 构建 Prompt（安全格式化：缺失变量不再导致整段技能降级）
            prompt = self._safe_format_skill_prompt(
                template=skill.prompt_template,
                values=safe_params,
                skill_id=skill_id,
            )

            # 空模板兜底：仍走通用 Prompt，防止向 LLM 发送空内容
            if not prompt.strip():
                logger.warning(
                    f"{Fore.YELLOW}技能 Prompt 为空，使用通用 Prompt 兜底 | skill={skill_id}{Style.RESET_ALL}"
                )
                prompt_params_str = "\n".join([f"{k}: {v}" for k, v in params.items()])
                prompt = self._build_generic_skill_fallback_prompt(
                    skill_name=skill.name,
                    skill_description=skill.description,
                    prompt_params_str=prompt_params_str,
                )

            # 对技能执行统一注入“当前任务 + 参数 + 执行约束”，减少模型反问和跑题
            current_task = context.get("task", "") if context else ""
            params_json = _json.dumps(safe_params, ensure_ascii=False, indent=2, default=str)
            dependency_summary = (
                "\n".join(dependency_messages)
                if dependency_messages else "（无额外运行时依赖，或无需安装）"
            )
            prompt = (
                f"【当前用户任务】\n{current_task or '（未提供）'}\n\n"
                f"【技能参数（JSON）】\n{params_json}\n\n"
                f"【技能工作目录】\n{str(skill_dir) if skill_dir else '（未知）'}\n\n"
                f"【运行时依赖预检结果】\n{dependency_summary}\n\n"
                "【执行硬约束】\n"
                "1. 若技能参数已包含完成任务所需信息（例如 location），必须直接执行，不要向用户重复询问同一参数。\n"
                "2. 优先使用可用工具获取真实结果，再给出结论。\n"
                "3. 若工具调用失败，明确说明失败原因与下一步建议，不要编造结果。\n\n"
                "4. 若 shell_exec / python_executor / 其他工具报出“缺少命令、缺少模块、缺少包、command not found、Cannot find module”等依赖错误，"
                "应优先在当前技能工作目录内自动补齐依赖并重试一次，而不是直接放弃。\n"
                "5. 若调用 shell_exec 执行技能脚本或依赖命令，必须把 working_dir 设为上方“技能工作目录”。\n\n"
                f"{prompt}"
            )
            
            from app.llm_hub.inference import InferenceConfig
            
            # 优先使用 agent 配置的模型，否则回退到默认
            model = get_default_model("openai")
            if agent and agent.agent_config:
                model = agent.agent_config.execution_model
            
            # 获取工具定义（用于 LLM function calling）
            all_tools_schemas = self.tool_hub.get_schemas() if self.tool_hub else []
            tools = []
            
            # 敏感工具列表：禁止在技能内部隐式调用，必须由外层 Agent 在计划中显式调用以触发二次确认
            SENSITIVE_TOOLS = {"file_write"}
            
            # 过滤：只允许被授权的工具，排除敏感工具、用户已拒绝工具，
            # 并优先按技能声明(required_tools/optional_tools)收紧工具白名单。
            user_rejected = context.get("user_rejected_tools", []) if context else []
            user_rejected_set = {
                str(x).strip() for x in user_rejected
                if isinstance(x, str) and str(x).strip()
            }
            agent_allowed_tools = (
                {
                    str(x).strip() for x in (agent.available_tools or [])
                    if isinstance(x, str) and str(x).strip()
                }
                if agent and agent.available_tools
                else set()
            )
            skill_required_tools = {
                str(x).strip() for x in (skill.required_tools or [])
                if isinstance(x, str) and str(x).strip()
            }
            skill_optional_tools = {
                str(x).strip() for x in (skill.optional_tools or [])
                if isinstance(x, str) and str(x).strip()
            }

            # 设计说明：
            # - file_write 等敏感工具在技能内部被强制禁用（需由外层计划显式调用并触发确认）。
            # - 因此，若技能在 required_tools 中声明了敏感工具，不应再按“缺失必需工具”报错，
            #   否则会出现“明明是安全策略剔除，却提示 SKILL.md 配置错误”的误导性失败。
            sensitive_required_tools = {
                x for x in skill_required_tools if x in SENSITIVE_TOOLS
            }
            effective_required_tools = {
                x for x in skill_required_tools if x not in SENSITIVE_TOOLS
            }
            if sensitive_required_tools:
                logger.warning(
                    f"{Fore.YELLOW}[执行引擎] 技能 {skill_id} 在 required_tools 中声明了敏感工具: "
                    f"{sorted(sensitive_required_tools)}。这些工具按安全策略不能在技能内部调用，"
                    "将从必需校验中忽略；如确需执行，请在外层计划中显式规划该工具步骤。"
                    f"{Style.RESET_ALL}"
                )

            declared_skill_tools = effective_required_tools | skill_optional_tools
            has_declared_skill_tools = bool(declared_skill_tools)
            if has_declared_skill_tools:
                logger.info(
                    f"{Fore.CYAN}[执行引擎] 技能 {skill_id} 声明工具白名单: "
                    f"required={sorted(effective_required_tools)} | "
                    f"optional={sorted(skill_optional_tools)}{Style.RESET_ALL}"
                )
            else:
                logger.info(
                    f"{Fore.CYAN}[执行引擎] 技能 {skill_id} 未声明 required_tools/optional_tools，"
                    "已启用兼容模式：开放当前 Agent 已授权的全部非敏感工具。"
                    f"{Style.RESET_ALL}"
                )

            registered_tool_names = set()
            for t_schema in all_tools_schemas:
                t_name = self._extract_tool_name_from_schema(t_schema)
                if not t_name:
                    logger.debug(
                        f"{Fore.YELLOW}[执行引擎] 跳过无法识别名称的工具 Schema: {t_schema}{Style.RESET_ALL}"
                    )
                    continue
                registered_tool_names.add(t_name)
                if agent_allowed_tools and t_name not in agent_allowed_tools:
                    continue
                if t_name in SENSITIVE_TOOLS:
                    continue
                if t_name in user_rejected_set:
                    continue
                # 兼容策略：
                # - 声明了工具：仅允许声明工具（与 Agent 白名单/敏感工具策略求交集）
                # - 未声明工具：开放当前 Agent 已授权的全部非敏感工具，兼容外部下载技能
                if has_declared_skill_tools and t_name not in declared_skill_tools:
                    continue
                tools.append(t_schema)
            
            tool_names_for_skill = [
                n for n in (self._extract_tool_name_from_schema(s) for s in tools) if n
            ]
            tool_names_for_skill_set = set(tool_names_for_skill)
            missing_required_tools = sorted(
                x for x in effective_required_tools if x not in tool_names_for_skill_set
            )
            if missing_required_tools:
                missing_detail = (
                    "技能声明的 required_tools 未在当前运行时工具集中满足: "
                    f"{missing_required_tools}。"
                    f"可用工具={sorted(registered_tool_names)}，"
                    f"Agent授权工具={sorted(agent_allowed_tools) if agent_allowed_tools else 'ALL'}。"
                    f"按安全策略剔除的敏感工具={sorted(SENSITIVE_TOOLS)}。"
                    "请检查 SKILL.md 的 required_tools 是否与工具注册名一致。"
                )
                logger.warning(
                    f"{Fore.YELLOW}[执行引擎] 技能 {skill_id} 缺失必需工具: "
                    f"{missing_required_tools}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": missing_detail,
                    "action": "skill",
                    "skill_id": skill_id
                }

            logger.debug(
                f"{Fore.CYAN}[执行引擎] 技能执行 - 过滤后提供 {len(tools)} 个工具定义"
                f"（排除拒绝工具: {sorted(user_rejected_set)}，排除敏感工具: {SENSITIVE_TOOLS}）"
                f" | tools={tool_names_for_skill}{Style.RESET_ALL}"
            )

            # 为技能执行追加可解释的工具预算，降低模型在同一任务上的重复循环概率。
            # 预算值作为“软约束”写入 prompt，不会阻断正常任务。
            tool_budget = max(2, min(6, len(tool_names_for_skill) + 1))
            prompt += (
                "\n\n【工具调用预算】\n"
                f"- 本次可用工具: {tool_names_for_skill or ['（无）']}\n"
                f"- 建议工具调用上限: {tool_budget} 次\n"
                "- 每次调用前先说明目标，禁止为同一统计目标重复调用多条等价命令。\n"
                "- 工具结果足够时必须停止调用并直接给出结论。"
            )
            # 全技能通用输出约束：返回“结果本体”，不是“执行过程口播”。
            prompt += (
                "\n\n【输出格式硬约束】\n"
                "1. 只输出最终结果内容本体，不要输出执行过程说明。\n"
                "2. 禁止以“任务已完成/我已经成功/已保存到”等流程汇报开头。\n"
                "3. 若任务需要落盘，当前步骤仅提供可写入内容，由后续 file_write 步骤处理。\n"
            )
            
            config = InferenceConfig(
                model=model,
                temperature=0.7,
                tools=tools
            )
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
            )

            # 技能输出质量校验（避免无效话术污染后续 file_write / final_answer）
            # NOTE: validators 来自 SKILL.md 的 output_validators 声明，实现声明式校验，
            #       新增技能时只需编辑 SKILL.md 即可自定义校验逻辑，无需修改执行引擎代码。
            is_valid, invalid_reason = self._validate_skill_output(
                skill_id=skill_id,
                output_text=response.content or "",
                params=safe_params,
                validators=getattr(skill, "output_validators", None),
            )
            if not is_valid:
                logger.warning(
                    f"{Fore.YELLOW}技能 {skill_id} 输出校验未通过: {invalid_reason}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": f"技能 {skill_id} 输出无效: {invalid_reason}",
                    "action": "skill",
                    "skill_id": skill_id
                }

            logger.info(f"{Fore.GREEN}技能 {skill_id} 执行成功{Style.RESET_ALL}")
            
            return {
                "success": True,
                "result": response.content,
                "action": "skill",
                "skill_id": skill_id
            }
            
        except Exception as e:
            error_msg = f"技能 {skill_id} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "skill",
                "skill_id": skill_id
            }
    
    async def _delegate_to_agent(
        self,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None,
        remaining_steps: Optional[List] = None
    ) -> Dict[str, Any]:
        """
        委派给子 Agent

        Args:
            step: 计划步骤
            context: 执行上下文（透传 stream_callback / pending_confirmations 以便
                     子 Agent 也能推送 user_confirm_required 事件并共享确认映射表）
            prev_results: 本轮已完成步骤结果，用于把上游真实数据注入子 Agent 任务
            remaining_steps: 父计划中当前 delegate 步骤之后的剩余步骤列表（PlanStep 对象）。
                             用于「计划感知」需求完整性检查——当后续步骤已覆盖某项能力时，
                             跳过对该能力关键词的注入，避免子 Agent 越权执行。
                             设计上支持任意 action 类型和关键词规则的扩展。

        Returns:
            Dict[str, Any]: 执行结果

        NOTE: 此方法包含防御性"需求完整性检查"，采用「计划感知」模式：
              1. 检查规划阶段 LLM 生成的 delegate task 是否遗漏了原始用户需求；
              2. 但在注入前，先扫描父计划的 remaining_steps，
                 如果后续步骤已覆盖该需求（如后续有 text_writing 或 file_write），
                 则跳过注入，避免子 Agent 越权执行本应由父计划处理的任务。
              3. CAPABILITY_KEYWORDS 映射表是通用扩展点，新场景只需添加条目。
        """
        agent_id = step.params.get("agent_id")
        task = step.params.get("task")
        if not isinstance(task, str):
            task = str(task or "")

        # ── 从 context 中提取原始用户任务（用于后续完整性诊断） ────────────────
        # NOTE: 原始任务是顶层用户输入，从 execution context 中传入；
        #       若 LLM 规划时截断了某些需求（如"写入本地"），可通过对比检测并补救
        original_task: str = context.get("task", "") if context else ""

        logger.info(
            f"{Fore.CYAN}[委派] 准备委派任务给子 Agent: {agent_id} "
            f"| 委派任务长度={len(task)}字符 "
            f"| 原始用户任务长度={len(original_task)}字符{Style.RESET_ALL}"
        )
        logger.debug(
            f"{Fore.BLUE}[委派] 委派任务摘要: {task[:150]}...{Style.RESET_ALL}"
        )
        if original_task:
            logger.debug(
                f"{Fore.BLUE}[委派] 原始用户任务摘要: {original_task[:150]}...{Style.RESET_ALL}"
            )

        # ═══════════════════════════════════════════════════════════════════
        # 【计划感知的需求完整性检查】
        #
        # 设计动机：
        #   当父 Agent（如 cs_master）规划了多步策略时，每一步只负责一部分需求。
        #   例如：step1=delegate(查数据) → step2=text_writing(写报告) → step3=final_answer
        #   此时 step1 的 delegate task 中自然不含"保存到"关键词，
        #   但这不代表需求被遗漏——step2 已经负责了。
        #
        #   旧逻辑：只比对 delegate task 与原始用户需求的关键词差异，盲目注入缺失需求。
        #   新逻辑：先扫描 remaining_steps，若后续步骤已覆盖某关键词对应的能力，
        #          则跳过该关键词的注入，避免子 Agent 越权执行本应由父计划的后续步骤处理的任务。
        #
        # 通用性设计：
        #   - CAPABILITY_KEYWORDS 定义了「关键词 → 覆盖该关键词的工具/技能/action」映射
        #   - 新增场景只需向 CAPABILITY_KEYWORDS 添加条目即可，不需改动检查逻辑
        #   - _is_keyword_covered_by_remaining_steps 方法可被其他模块复用
        # ═══════════════════════════════════════════════════════════════════

        # ── 能力关键词映射表（通用扩展点） ─────────────────────────────────
        # 格式: 关键词 → {
        #   "tools":   [可覆盖该需求的工具名],
        #   "skills":  [可覆盖该需求的技能 ID],
        #   "actions": [可覆盖该需求的 action 类型（如 delegate）]
        # }
        # 后续新增场景（如搜索、发邮件、数据导出等）只需在此处追加条目
        CAPABILITY_KEYWORDS: Dict[str, Dict[str, list]] = {
            "写入本地": {"tools": ["file_write", "file_manager"], "skills": ["text_writing"], "actions": ["delegate"]},
            "保存文件": {"tools": ["file_write", "file_manager"], "skills": ["text_writing"], "actions": ["delegate"]},
            "写入文件": {"tools": ["file_write", "file_manager"], "skills": ["text_writing"], "actions": ["delegate"]},
            "保存到":   {"tools": ["file_write", "file_manager"], "skills": ["text_writing"], "actions": ["delegate"]},
            "写到":     {"tools": ["file_write", "file_manager"], "skills": ["text_writing"], "actions": ["delegate"]},
            "file_write": {"tools": ["file_write"], "skills": [], "actions": []},
            # ── 可扩展：后续新增场景在此添加 ──
            # "搜索":    {"tools": ["web_search", "search"], "skills": ["web_browsing"], "actions": ["delegate"]},
            # "发邮件":  {"tools": ["send_email"], "skills": ["email_sending"], "actions": ["delegate"]},
            # "导出":    {"tools": ["data_export"], "skills": ["report_export"], "actions": ["delegate"]},
        }

        if original_task:
            missing_keywords = []
            covered_keywords = []

            for kw, coverage_config in CAPABILITY_KEYWORDS.items():
                # 原始任务中包含该关键词，但规划的委派 task 中没有
                if kw in original_task and kw not in task:
                    # ════ 计划感知检查 ════
                    # 扫描父计划后续步骤，判断是否已覆盖该关键词对应的能力
                    if remaining_steps and self._is_keyword_covered_by_remaining_steps(
                        kw, coverage_config, remaining_steps
                    ):
                        # 后续步骤已覆盖，跳过注入
                        covered_keywords.append(kw)
                        continue
                    missing_keywords.append(kw)

            # ── 打印计划感知检查结果的详细日志 ────────────────────────────
            if covered_keywords:
                logger.info(
                    f"{Fore.GREEN}[委派✅ 计划感知] 以下关键词虽不在委派 task 中，"
                    f"但父计划后续步骤已覆盖，跳过注入: {covered_keywords}{Style.RESET_ALL}"
                )

            if missing_keywords:
                # 检测到需求确实被遗漏（后续步骤也未覆盖），发出警告并补充原始任务上下文
                logger.warning(
                    f"{Fore.YELLOW}[委派⚠️] 检测到委派任务可能遗漏了原始用户需求！"
                    f"\n  原始用户任务: '{original_task[:120]}'"
                    f"\n  委派的 task : '{task[:120]}'"
                    f"\n  疑似遗漏关键词: {missing_keywords}"
                    f"\n  已被后续步骤覆盖（无需注入）: {covered_keywords}"
                    f"\n  🔧 已自动追加原始用户完整需求到委派 task 末尾，防止信息丢失。{Style.RESET_ALL}"
                )
                # 自动修复：将原始用户任务作为"完整需求上下文"补充到委派 task 末尾，
                # 让子 Agent 知道用户的完整意图，避免因 LLM 规划截断导致需求遗漏
                task = (
                    f"{task}\n\n"
                    "【⚠️ 完整用户需求（请务必全部完成，不要遗漏）】\n"
                    f"用户原始请求：{original_task}\n"
                    "注意：如任务包含文件写入、搜索等操作而你的工具不支持，"
                    "必须通过 spawn_agent 将任务连同已查到的数据转交给 general_agent 完成。"
                )
                logger.info(
                    f"{Fore.GREEN}[委派🔧] 已向子 Agent '{agent_id}' 补充原始需求上下文，"
                    f"修复后 task 长度={len(task)}字符{Style.RESET_ALL}"
                )
            else:
                logger.debug(
                    f"{Fore.GREEN}[委派✅] 委派任务完整性检查通过，"
                    f"未发现需求遗漏（已覆盖: {covered_keywords}）{Style.RESET_ALL}"
                )

        if not self.child_agent_manager:
            error_msg = "子 Agent 管理器未初始化"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "delegate",
                "agent_id": agent_id
            }

        # ── 向子 Agent 任务注入上游真实结果，避免“根据查询结果”却拿不到查询数据 ─────────
        # 典型场景：先 order_agent 查订单，再 general_agent 写文件。
        # 若不注入，general_agent 只能基于空上下文臆造价格内容。
        if prev_results:
            successful_prev = [
                r for r in prev_results
                if r.get("success") and (r.get("result") is not None)
            ]
            if successful_prev:
                def _to_text(value: Any, max_len: int = 2200) -> str:
                    if isinstance(value, (dict, list)):
                        s = _json.dumps(value, ensure_ascii=False, indent=2, default=str)
                    else:
                        s = str(value)
                    if len(s) > max_len:
                        s = s[:max_len] + "\n...（内容已截断）"
                    return s

                # 仅注入最近几条成功结果，控制上下文体积
                recent = successful_prev[-3:]
                blocks = []
                for r in recent:
                    label = r.get("tool_name") or r.get("skill_id") or r.get("agent_id") or r.get("action", "上游步骤")
                    payload = r.get("result")
                    # 委派结果携带子 Agent 轨迹，供下游精准复用（如提取价格后写文件）
                    if r.get("action") == "delegate":
                        payload = {
                            "agent_id": r.get("agent_id"),
                            "result": r.get("result"),
                            "step_results": r.get("step_results", []),
                            "error": r.get("error"),
                        }
                    blocks.append(f"[{label}]\n{_to_text(payload)}")
                upstream_context = "\n\n".join(blocks)

                # 若任务模板中已使用占位符则替换；否则直接追加显式上下文
                last_payload = successful_prev[-1].get("result")
                last_payload_text = _to_text(last_payload)
                replacements = [
                    ("{{last_tool_result}}", last_payload_text),
                    ("{last_tool_result}", last_payload_text),
                    ("{{upstream_results}}", upstream_context),
                    ("{upstream_results}", upstream_context),
                ]
                replaced = False
                for placeholder, value in replacements:
                    if placeholder in task:
                        task = task.replace(placeholder, value)
                        replaced = True

                if not replaced:
                    task = (
                        f"{task}\n\n"
                        "【上游已执行结果（必须基于真实结果继续执行，禁止臆造）】\n"
                        f"{upstream_context}"
                    )

                logger.info(
                    f"{Fore.BLUE}[委派] 已向子 Agent {agent_id} 注入上游结果，"
                    f"条数={len(recent)}{Style.RESET_ALL}"
                )

        # 从 context 中提取父级流式回调和挂起确认映射表
        # 这两个对象需要透传给子 Agent，使子 Agent：
        #   1. 也能向同一条 SSE 流推送 user_confirm_required 等事件
        #   2. 注册到父级的 pending_confirmations / pending_user_inputs 字典，
        #      使 /agents/confirm、/agents/input 接口能够找到
        stream_callback = context.get("stream_callback") if context else None
        pending_confirmations = context.get("pending_confirmations") if context else None
        pending_user_inputs = context.get("pending_user_inputs") if context else None
        user_rejected_tools_in = context.get("user_rejected_tools") if context else None

        if stream_callback:
            logger.info(
                f"{Fore.BLUE}[委派] 检测到父级 stream_callback，"
                f"子 Agent {agent_id} 将共享 SSE 流、pending_confirmations 和 pending_user_inputs{Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.YELLOW}[委派] 无父级 stream_callback，"
                f"子 Agent {agent_id} 将以静默模式执行（无用户确认交互）{Style.RESET_ALL}"
            )

        # ═══════════════════════════════════════════════════════════════════
        # 【统一委派路径：优先通过已注册的 SpawnAgentTool 执行委派】
        #
        # 设计动机：
        #   系统中已在 ToolHub 注册了 SpawnAgentTool（spawn_agent 工具），
        #   所有子 Agent 委派应统一经过该工具，以便享受：
        #     - SpawnAgentTool 自身的参数校验和日志
        #     - 工具网关的统一统计和超时管理
        #     - 将来可在 SpawnAgentTool 层面扩展拦截/修改逻辑
        #
        #   当 LLM 生成 action="delegate" 计划步骤时，执行引擎也应走同一路径，
        #   而不是直接绕过 SpawnAgentTool 调用 ChildAgentManager。
        #
        # 备用路径：
        #   若 SpawnAgentTool 未注册（如测试环境）或调用失败，
        #   回退到直接调用 ChildAgentManager.delegate_task（保证向后兼容）。
        # ═══════════════════════════════════════════════════════════════════
        spawn_tool = self.tool_hub.get_tool("spawn_agent") if self.tool_hub else None

        if spawn_tool and hasattr(spawn_tool, "update_context") and callable(spawn_tool.update_context):
            # ── 路径一（推荐）：通过 SpawnAgentTool 委派 ──────────────────────
            # 先更新工具的运行时上下文（stream_callback / pending_confirmations / pending_user_inputs）
            spawn_tool.update_context(
                stream_callback       = stream_callback,
                pending_confirmations = pending_confirmations,
                pending_user_inputs   = pending_user_inputs,
                user_rejected_tools   = user_rejected_tools_in,
            )
            logger.info(
                f"{Fore.GREEN}[委派→SpawnAgentTool] 通过已注册的 spawn_agent 工具委派任务 "
                f"→ {agent_id} | stream_callback={'✅ 已注入' if stream_callback else '❌ 未传入'}"
                f"{Style.RESET_ALL}"
            )
            try:
                result = await spawn_tool.execute({
                    "agent_id": agent_id,
                    "task":     task,   # 已包含上游结果注入 + 原始需求补充
                })

                _sub_success = result.get("success", False)
                # NOTE: result 来自 execute_with_callback，结构为
                #   {"success": bool, "result": ExecutionResult.to_dict(), "error": str|None, ...}
                # 这里需要从内层 result 里提取真实的错误信息，供父 Agent 错误收集使用
                _sub_error = result.get("error") or (
                    # 内层 result 也可能有 error 字段（ExecutionResult.to_dict()）
                    result.get("result", {}).get("error") if isinstance(result.get("result"), dict) else None
                )
                if (not _sub_success) and (_sub_error is None or str(_sub_error).strip() == ""):
                    _sub_error = (
                        f"子 Agent '{agent_id}' 执行失败（未返回具体错误信息），"
                        "可能由用户拒绝关键操作导致。"
                    )
                logger.info(
                    f"{Fore.GREEN if _sub_success else Fore.YELLOW}"
                    f"[委派←SpawnAgentTool] 子 Agent '{agent_id}' 通过 spawn_agent 工具执行完毕 "
                    f"| success={_sub_success} | error={_sub_error or '无'}"
                    f"{Style.RESET_ALL}"
                )
                return {
                    "success": _sub_success,
                    "result":  result,
                    "error":   _sub_error,          # 失败时传递真实错误，避免 "Unknown error"
                    "action":  "delegate",
                    "agent_id": agent_id,
                    "user_rejected_tools": result.get("user_rejected_tools", []),
                }

            except Exception as e:
                # SpawnAgentTool 调用失败时降级到直接委派，不中断流程
                logger.warning(
                    f"{Fore.YELLOW}[委派⚠️] SpawnAgentTool 调用异常，回退直接委派: {e}{Style.RESET_ALL}"
                )
                # fall-through to direct delegation

        # ── 路径二（兜底）：直接通过 ChildAgentManager 委派 ──────────────────
        # 当 SpawnAgentTool 未注册（如测试环境）或上方调用失败时走此路径
        # NOTE: child_agent_manager 在此处一定非 None，因为函数顶部已做早期返回保护
        logger.info(
            f"{Fore.BLUE}[委派→ChildAgentManager] 通过 ChildAgentManager 直接委派任务 "
            f"→ {agent_id}（SpawnAgentTool 不可用，使用兜底路径）{Style.RESET_ALL}"
        )
        try:
            result = await self.child_agent_manager.delegate_task(
                parent_agent_id       = None,
                child_agent_id       = agent_id,
                task                 = task,
                stream_callback      = stream_callback,
                pending_confirmations = pending_confirmations,
                pending_user_inputs   = pending_user_inputs,
                user_rejected_tools  = user_rejected_tools_in,
            )

            _sub_success = result.get("success", False)
            _sub_error   = result.get("error")
            if (not _sub_success) and (_sub_error is None or str(_sub_error).strip() == ""):
                _sub_error = (
                    f"子 Agent '{agent_id}' 执行失败（未返回具体错误信息），"
                    "可能由用户拒绝关键操作导致。"
                )
            logger.info(
                f"{Fore.GREEN if _sub_success else Fore.YELLOW}"
                f"[委派←ChildAgentManager] 子 Agent '{agent_id}' 执行完成 "
                f"| success={_sub_success}{Style.RESET_ALL}"
            )
            return {
                "success": _sub_success,   # 根据子 Agent 实际成功状态，不再硬编码 True
                "result":  result,
                "error":   _sub_error,     # 传递子 Agent 的错误信息
                "action":  "delegate",
                "agent_id": agent_id,
                "user_rejected_tools": result.get("user_rejected_tools", []),
            }

        except Exception as e:
            error_msg = f"委派给 Agent {agent_id} 失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error":   str(e),
                "action":  "delegate",
                "agent_id": agent_id,
            }

    def _is_keyword_covered_by_remaining_steps(
        self,
        keyword: str,
        coverage_config: Dict[str, list],
        remaining_steps: List
    ) -> bool:
        """
        【通用辅助方法】判断某个关键词对应的能力是否已被父计划的后续步骤覆盖

        设计思路：
            对于每个后续步骤 (PlanStep)，按以下维度依次检查：
            1. action 匹配  — 步骤的 action 是否在 coverage_config["actions"] 中
            2. 工具名匹配   — 步骤参数中的 tool_name 是否在 coverage_config["tools"] 中
            3. 技能 ID 匹配 — 步骤参数中的 skill_id 是否在 coverage_config["skills"] 中
            4. 关键词出现    — keyword 本身是否出现在步骤参数的值中（文本模糊匹配兜底）

            任一维度匹配即视为「已覆盖」。

        Args:
            keyword: 被检查的关键词（如 "保存到"）
            coverage_config: CAPABILITY_KEYWORDS 映射表中该关键词的配置
                             格式: {"tools": [...], "skills": [...], "actions": [...]}
            remaining_steps: 父计划中 delegate 步骤之后的所有剩余步骤

        Returns:
            bool: True 表示至少有一个后续步骤可以覆盖该关键词能力

        NOTE: 此方法为纯逻辑判断，不修改任何状态，可安全地被其他模块复用。
        """
        tools_can_cover   = coverage_config.get("tools", [])
        skills_can_cover  = coverage_config.get("skills", [])
        actions_can_cover = coverage_config.get("actions", [])

        for step in remaining_steps:
            step_action = getattr(step, "action", "")
            step_params = getattr(step, "params", {}) or {}

            # ── 维度 1：action 类型匹配（如 delegate） ─────────────────
            if step_action in actions_can_cover:
                logger.debug(
                    f"{Fore.BLUE}[计划感知] 关键词 '{keyword}' 被后续步骤的 "
                    f"action='{step_action}' 覆盖{Style.RESET_ALL}"
                )
                return True

            # ── 维度 2：工具名匹配 ─────────────────────────────────────
            step_tool = step_params.get("tool_name", "")
            if step_tool and step_tool in tools_can_cover:
                logger.debug(
                    f"{Fore.BLUE}[计划感知] 关键词 '{keyword}' 被后续步骤的 "
                    f"tool='{step_tool}' 覆盖{Style.RESET_ALL}"
                )
                return True

            # ── 维度 3：技能 ID 匹配 ───────────────────────────────────
            step_skill = step_params.get("skill_id", "")
            if step_skill and step_skill in skills_can_cover:
                logger.debug(
                    f"{Fore.BLUE}[计划感知] 关键词 '{keyword}' 被后续步骤的 "
                    f"skill='{step_skill}' 覆盖{Style.RESET_ALL}"
                )
                return True

            # ── 维度 4：关键词文本出现在参数值中（兜底模糊匹配） ────────
            # 扫描所有参数值，判断关键词是否出现在描述/task/其他文本字段中
            for param_key, param_val in step_params.items():
                if isinstance(param_val, str) and keyword in param_val:
                    logger.debug(
                        f"{Fore.BLUE}[计划感知] 关键词 '{keyword}' 出现在后续步骤的 "
                        f"params['{param_key}'] 中，视为已覆盖{Style.RESET_ALL}"
                    )
                    return True

        # 所有后续步骤都未覆盖该关键词
        return False
# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Execution Engine 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试执行结果
    result = ExecutionResult(
        success=True,
        result="测试成功",
        step_results=[{"action": "tool", "result": "ok"}]
    )
    print(f"创建执行结果: {result.to_dict()}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
