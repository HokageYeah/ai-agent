"""
Agent 运行记忆系统 (AgentRunMemory)
====================================

本模块实现了 Agent 单次任务执行的完整行为记忆储备系统。

核心设计：
  - 每条记忆以 OpenAI 标准 messages 格式（role/content/tool_calls）存储
  - 支持工具调用以 assistant.tool_calls + tool result 配对的形式呈现
  - 为规划引擎和反思引擎提供「拿来即用」的 messages 数组，无需文字拼接
  - 挂载于 AgentState["run_memory"]，贯穿整个 Plan-Execute-Reflect 生命周期

为什么用 messages 格式而不是文字拼接：
  - LLM 把历史消息数组当作「真实发生过的对话」理解，而非「描述文本」
  - 工具调用的 assistant + tool 消息对完全符合 Function Calling 协议
  - 每次规划/反思时，LLM 可直接感知自己之前做了什么、工具返回了什么

作者: AI Agent Team
创建时间: 2026-03-06
"""

import json
import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional
from loguru import logger
from colorama import Fore, Style


# ─────────────────────────────────────────────────────────────────────────────
# 记忆消息类型别名（对齐 OpenAI messages 合法 role 值）
# ─────────────────────────────────────────────────────────────────────────────
MessageRole = Literal["system", "user", "assistant", "tool"]

# 记忆条目类型（存储在 meta 中，用于过滤/调试，不传给 LLM）
EntryType = Literal[
    "plan",           # 规划产出快照
    "tool_call",      # 工具调用 assistant 发起消息
    "tool_result",    # 工具调用 tool 返回结果
    "skill_call",     # 技能调用 assistant 发起
    "skill_result",   # 技能调用结果
    "delegate",       # 子 Agent 委派说明
    "delegate_result",# 子 Agent 返回摘要
    "user_action",    # 用户确认/拒绝操作
    "reflection",     # 反思结论
    "error",          # 错误记录（注入 tool_result 中体现）
]


@dataclass
class AgentMemoryMessage:
    """
    单条 Agent 记忆消息

    完全对齐 OpenAI messages API 格式，可直接合并到 LLM 调用的 messages 数组。
    内部 meta 字段不会传给 LLM，仅用于按迭代轮次过滤和调试追踪。
    """

    # ── OpenAI 标准字段 ──
    role: MessageRole
    content: Optional[str] = None

    # assistant 角色发起工具调用时填写（Function Calling 输出）
    tool_calls: Optional[list[dict]] = None

    # tool 角色返回结果时填写
    tool_call_id: Optional[str] = None
    name: Optional[str] = None  # tool 角色时为工具/技能名称

    # ── 内部追踪元数据（不暴露给 LLM）──
    meta: dict = field(default_factory=dict)
    # meta 结构示例：
    #   {"iteration": 0, "entry_type": "tool_call", "timestamp": 1741234567.89, "success": True}

    def to_openai_dict(self) -> dict:
        """
        转换为 OpenAI API 兼容格式
        仅包含 LLM 可理解的标准字段，去掉内部 meta。
        """
        msg: dict = {"role": self.role}

        # content 为 None 时不加入（tool_calls 消息 content 可以为 None）
        if self.content is not None:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls

        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id

        if self.name:
            msg["name"] = self.name

        return msg


@dataclass
class AgentRunMemory:
    """
    Agent 单次任务运行的完整记忆仓库

    生命周期：单次 execute() / execute_stream() 调用期间，挂载于 AgentState["run_memory"]。
    每个 Plan-Execute-Reflect 循环节点在「进入前读、退出后写」。

    核心思路：
      - 所有历史行为以 OpenAI messages 格式追加存储
      - build_messages_for_planning()  → 为规划引擎提供携带历史记忆的 messages 数组
      - build_messages_for_reflection() → 为反思引擎提供当前轮完整执行轨迹的 messages 数组
    """

    task: str           # 本次任务目标
    agent_id: str       # 执行的 Agent ID
    agent_name: str     # 执行的 Agent 显示名称
    started_at: float = field(default_factory=time.time)

    # 外部传入的前置上下文记忆（例如：Session Memory, Conversation History）
    context_messages: list[dict] = field(default_factory=list)

    # 按时序追加的记忆消息列表（含 meta，不直接传给 LLM）
    _messages: list[AgentMemoryMessage] = field(default_factory=list)

    # NOTE: 任务内用户输入缓存（user_inputs_cache）
    # 用于在同一任务的不同 iteration 之间保持用户输入（如 SMTP 配置），
    # 防止 python_executor / send_message 反复向用户询问同一配置。
    # 结构：{ "smtp_config": {"smtp_server": ..., "sender_email": ...}, ... }
    # 生命周期：与 AgentRunMemory 同步，任务结束后自动消失，不跨任务保留。
    user_inputs_cache: dict = field(default_factory=dict)

    # ─────────────────────────────────────────────────────────────────────────
    # 用户输入缓存读写接口（防止工具反复询问同一配置）
    # ─────────────────────────────────────────────────────────────────────────

    def write_user_inputs_cache(self, key_group: str, inputs: dict) -> None:
        """
        将用户输入写入任务内缓存

        用于在工具（如 send_message / python_executor）收到用户提供的配置后，
        将其持久化到当前任务的内存缓存，确保同一任务内后续工具调用可直接复用，
        无需再次向用户重复询问。

        Args:
            key_group: 配置分组名称，如 "smtp_config"、"db_config"、"api_config"
            inputs:    用户提供的配置字典，如 {"smtp_server": "smtp.qq.com", ...}
        """
        if not isinstance(inputs, dict) or not inputs:
            logger.debug(f"[用户输入缓存] 写入跳过（inputs 为空）: key_group={key_group}")
            return
        # 合并而非直接覆盖，防止漏掉之前已缓存的同组其他字段
        existing = self.user_inputs_cache.get(key_group, {})
        merged = {**existing, **inputs}
        self.user_inputs_cache[key_group] = merged
        logger.info(
            f"{Fore.GREEN}[用户输入缓存] ✅ 写入 '{key_group}': "
            f"字段={list(inputs.keys())}{Style.RESET_ALL}"
        )

    def read_user_inputs_cache(self, key_group: str) -> Optional[dict]:
        """
        从任务内缓存读取用户输入

        在工具需要某类配置（如 SMTP）时，先通过此方法查询缓存，
        有则直接使用，避免再次弹出用户输入弹窗造成循环。

        Args:
            key_group: 配置分组名称，如 "smtp_config"、"db_config"

        Returns:
            若缓存存在则返回配置字典；否则返回 None
        """
        cached = self.user_inputs_cache.get(key_group)
        if cached:
            logger.info(
                f"{Fore.CYAN}[用户输入缓存] 🎯 命中 '{key_group}': "
                f"字段={list(cached.keys())}{Style.RESET_ALL}"
            )
        else:
            logger.debug(f"[用户输入缓存] 未命中: key_group={key_group}")
        return cached if cached else None

    # ─────────────────────────────────────────────────────────────────────────
    # 写入接口（由 langgraph_executor 各节点在完成操作后调用）
    # ─────────────────────────────────────────────────────────────────────────

    def write_plan(self, iteration: int, reasoning: str, steps: list[dict]) -> None:
        """
        记录规划产出（以 assistant 消息呈现）

        为什么用 assistant 角色：
          规划结论是 Agent 自己的「思考决策」，符合 assistant 角色语义。
          重规划时，LLM 看到之前轮次的规划内容，能直接感知历史决策。
        """
        # 对步骤做简化摘要，控制 token 消耗
        steps_summary = json.dumps(steps, ensure_ascii=False, indent=None, default=str)
        if len(steps_summary) > 800:
            steps_summary = steps_summary[:800] + "...（步骤已截断）"

        content = (
            f"【规划-第{iteration}轮】\n"
            f"推理过程: {reasoning}\n"
            f"执行步骤: {steps_summary}"
        )
        msg = AgentMemoryMessage(
            role="assistant",
            content=content,
            meta={
                "iteration": iteration,
                "entry_type": "plan",
                "timestamp": time.time()
            }
        )
        self._messages.append(msg)
        logger.debug(
            f"{Fore.CYAN}[记忆写入] write_plan iteration={iteration}, "
            f"steps={len(steps)}{Style.RESET_ALL}"
        )

    def write_tool_call(
        self,
        iteration: int,
        tool_name: str,
        tool_args: dict,
        tool_result: Any,
        success: bool,
        error_msg: str = "",
        call_id: Optional[str] = None
    ) -> None:
        """
        记录工具调用（严格遵循 OpenAI Function Calling 格式）

        生成两条配对消息：
          1. assistant.tool_calls  → Agent 发起的工具调用请求
          2. tool result           → 工具返回的结果（失败时前缀 [ERROR]）

        为什么用 assistant.tool_calls + tool 配对：
          这是 OpenAI Function Calling 协议规定的格式。
          LLM 在历史 messages 中看到这种配对时，能精准理解「调用了哪个工具、返回了什么」，
          准确度远高于将工具调用描述成普通文字。
        """
        call_id = call_id or f"call_{uuid.uuid4().hex[:10]}"

        # ── 1. assistant 发起工具调用 ─────────────────────────
        args_str = json.dumps(tool_args, ensure_ascii=False, default=str)
        if len(args_str) > 500:
            # 入参超长时截断，防止 Prompt 爆长
            args_str = args_str[:500] + "...}"

        self._messages.append(AgentMemoryMessage(
            role="assistant",
            content=None,   # Function Calling 发起时 content 可为 None
            tool_calls=[{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": args_str
                }
            }],
            meta={
                "iteration": iteration,
                "entry_type": "tool_call",
                "tool_name": tool_name,
                "success": success,
                "timestamp": time.time()
            }
        ))

        # ── 2. tool 返回结果 ──────────────────────────────────
        if isinstance(tool_result, (dict, list)):
            result_str = json.dumps(tool_result, ensure_ascii=False, default=str)
        else:
            result_str = str(tool_result) if tool_result is not None else ""

        # 失败时不仅保留 error_msg，也尽量保留工具返回详情，
        # 避免后续规划只能看到一句“success=false”而失去真正的报错上下文。
        if not success:
            error_parts: list[str] = []
            display_msg = str(error_msg or "").strip()
            if display_msg:
                error_parts.append(display_msg)

            normalized_result = result_str.strip()
            if normalized_result and normalized_result != display_msg:
                error_parts.append(f"工具返回详情: {normalized_result}")

            combined_error = "\n".join(part for part in error_parts if part).strip()
            result_str = f"[ERROR] {combined_error or '工具执行失败'}"

        # 控制结果长度，避免 Prompt 爆长
        if len(result_str) > 1500:
            result_str = result_str[:1500] + "\n...（结果已截断）"

        self._messages.append(AgentMemoryMessage(
            role="tool",
            tool_call_id=call_id,
            name=tool_name,
            content=result_str,
            meta={
                "iteration": iteration,
                "entry_type": "tool_result",
                "tool_name": tool_name,
                "success": success,
                "timestamp": time.time()
            }
        ))

        status_text = "成功" if success else "失败"
        logger.debug(
            f"{Fore.CYAN}[记忆写入] write_tool_call: tool={tool_name} "
            f"{status_text}, iteration={iteration}{Style.RESET_ALL}"
        )

    def write_skill_call(
        self,
        iteration: int,
        skill_id: str,
        skill_result: Any,
        success: bool
    ) -> None:
        """
        记录技能调用（同样用 assistant.tool_calls + tool 配对格式）

        为什么和工具调用用相同格式：
          技能本质上也是一种「调用外部能力」的行为，保持格式统一
          便于 LLM 在历史记忆中一致理解「用了什么能力、拿到了什么结果」。
        """
        call_id = f"skill_{uuid.uuid4().hex[:10]}"

        # assistant 发起技能调用
        self._messages.append(AgentMemoryMessage(
            role="assistant",
            content=None,
            tool_calls=[{
                "id": call_id,
                "type": "function",
                "function": {"name": skill_id, "arguments": "{}"}
            }],
            meta={
                "iteration": iteration,
                "entry_type": "skill_call",
                "skill_id": skill_id,
                "timestamp": time.time()
            }
        ))

        # tool 返回结果
        if isinstance(skill_result, (dict, list)):
            result_str = json.dumps(skill_result, ensure_ascii=False, default=str)
        else:
            result_str = str(skill_result) if skill_result is not None else ""

        if len(result_str) > 1500:
            result_str = result_str[:1500] + "\n...（结果已截断）"

        if not success:
            result_str = f"[ERROR] {result_str}"

        self._messages.append(AgentMemoryMessage(
            role="tool",
            tool_call_id=call_id,
            name=skill_id,
            content=result_str,
            meta={
                "iteration": iteration,
                "entry_type": "skill_result",
                "skill_id": skill_id,
                "success": success,
                "timestamp": time.time()
            }
        ))

        logger.debug(
            f"{Fore.CYAN}[记忆写入] write_skill_call: skill={skill_id} "
            f"{'成功' if success else '失败'}, iteration={iteration}{Style.RESET_ALL}"
        )

    def write_delegate(
        self,
        iteration: int,
        child_agent_id: str,
        sub_task: str,
        result_summary: str,
        success: bool
    ) -> None:
        """
        记录子 Agent 委派（以 assistant 说明 + user 摘要返回的形式呈现）

        为什么用 user 角色返回子 Agent 结果：
          子 Agent 的执行结果从主 Agent 视角来看是「外部反馈」，
          类似于用户告知结果，用 user 角色语义上最贴近。
          同时避免破坏 assistant.tool_calls 的严格配对要求。
        """
        # assistant 说明委派意图
        self._messages.append(AgentMemoryMessage(
            role="assistant",
            content=f"【委派给子Agent: {child_agent_id}】任务: {sub_task}",
            meta={
                "iteration": iteration,
                "entry_type": "delegate",
                "child_agent_id": child_agent_id,
                "timestamp": time.time()
            }
        ))

        # user 角色返回子 Agent 执行摘要
        prefix = "✅" if success else "❌"
        summary_text = result_summary[:1000] + "...（已截断）" if len(result_summary) > 1000 else result_summary
        self._messages.append(AgentMemoryMessage(
            role="user",
            content=f"{prefix}【子Agent返回 - {child_agent_id}】{summary_text}",
            meta={
                "iteration": iteration,
                "entry_type": "delegate_result",
                "child_agent_id": child_agent_id,
                "success": success,
                "timestamp": time.time()
            }
        ))

        logger.debug(
            f"{Fore.CYAN}[记忆写入] write_delegate: child_agent={child_agent_id} "
            f"{'成功' if success else '失败'}, iteration={iteration}{Style.RESET_ALL}"
        )

    def write_user_action(
        self,
        iteration: int,
        action: str,
        tool_name: str
    ) -> None:
        """
        记录用户确认/拒绝操作（以 user 消息呈现）

        为什么用 user 角色：
          用户操作就是真实的用户输入，用 user 消息最符合语义。
          LLM 在历史 messages 中看到这条消息时，
          能清楚理解「用户在这一步做了什么决定」，
          从而在重规划时不再触发同一操作。
        """
        action_desc = "确认了" if action == "confirm" else "拒绝了"
        self._messages.append(AgentMemoryMessage(
            role="user",
            content=f"【用户操作通知】用户{action_desc} [{tool_name}] 操作的执行请求。",
            meta={
                "iteration": iteration,
                "entry_type": "user_action",
                "action": action,
                "tool_name": tool_name,
                "timestamp": time.time()
            }
        ))

        logger.debug(
            f"{Fore.CYAN}[记忆写入] write_user_action: {action_desc} {tool_name}, "
            f"iteration={iteration}{Style.RESET_ALL}"
        )

    def write_reflection(
        self,
        iteration: int,
        result: dict
    ) -> None:
        """
        记录反思结论（以 assistant 消息呈现）

        为什么用 assistant 角色：
          反思是 Agent 对自己行为的「自我判断」，属于 agent 内部状态，
          用 assistant 消息符合语义，且让 LLM 在下轮规划时
          能清楚看到「上一轮我的判断是什么」。
        """
        success = result.get("success", False)
        needs_replan = result.get("needs_replanning", False)
        feedback = result.get("feedback", "")
        summary = result.get("summary", "")

        status = "✅ 成功" if success else "❌ 失败"
        replan_text = "（需要重规划）" if needs_replan else "（任务完成）"

        content = (
            f"【反思结论-第{iteration}轮】{status} {replan_text}\n"
            f"总结: {summary}\n"
            f"反馈: {feedback}"
        )

        self._messages.append(AgentMemoryMessage(
            role="assistant",
            content=content,
            meta={
                "iteration": iteration,
                "entry_type": "reflection",
                "success": success,
                "needs_replanning": needs_replan,
                "timestamp": time.time()
            }
        ))

        logger.debug(
            f"{Fore.CYAN}[记忆写入] write_reflection iteration={iteration}, "
            f"success={success}, needs_replanning={needs_replan}{Style.RESET_ALL}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 读取接口（由规划/反思引擎调用，返回符合 OpenAI 格式的 messages 数组）
    # ─────────────────────────────────────────────────────────────────────────

    def build_messages_for_planning(
        self,
        system_prompt: str,
        current_iteration: int,
        trigger_prompt: str = "请基于以上历史执行记录，为本轮任务制定全新的执行计划。"
    ) -> list[dict]:
        """
        为规划引擎组装完整的 messages 数组

        结构（按顺序）：
          [0] system  → 规划角色定义 + 工具说明 + 输出格式要求
          [1] user    → 原始任务描述（首次规划仅此两条）
          [...] 历史记忆消息（只含 iteration < current_iteration 的记录）
          [-1] user   → 本轮规划触发指令

        为什么只包含 < current_iteration 的历史：
          规划时当前轮次还没开始执行，不应包含当前轮的工具调用结果。
          只把过去轮次的「计划+执行+反思」作为历史给 LLM 参考。

        Args:
            system_prompt: 角色定义 + 工具清单 + 输出格式（来自规划引擎构建）
            current_iteration: 当前迭代轮次（0-indexed）
            trigger_prompt: 发给 LLM 的本轮规划触发指令

        Returns:
            list[dict]: 符合 OpenAI messages 格式的列表
        """
        # ── 第一步：system 角色定义（固定放最前面）──
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
        ]

        # ── 第二步：注入前置上下文（会话摘要 + 对话历史）──
        # 为什么放在任务描述之前：先给 LLM 历史背景，再告知本轮任务，
        # 语义上更自然（先看背景 → 再理解当前任务 → 再制定计划）
        if self.context_messages:
            messages.extend(self.context_messages)
            # 打印摘要内容摘要，方便调试确认注入是否正确
            for i, ctx_msg in enumerate(self.context_messages):
                preview = str(ctx_msg.get("content", ""))[:80].replace("\n", " ")
                logger.info(
                    f"{Fore.GREEN}[记忆读取] 规划引擎前置上下文 [{i}]: "
                    f"role={ctx_msg.get('role','?')} | 内容摘要: {preview!r}{Style.RESET_ALL}"
                )
            logger.info(
                f"{Fore.GREEN}[记忆读取] 规划引擎共注入 {len(self.context_messages)} 条前置上下文记忆"
                f"（会话摘要+对话历史）{Style.RESET_ALL}"
            )
        else:
            logger.debug(
                f"{Fore.CYAN}[记忆读取] 规划引擎：无前置上下文（首次会话或会话摘要为空）{Style.RESET_ALL}"
            )

        # ── 第三步：当前任务描述 ──
        messages.append({"role": "user", "content": f"任务目标: {self.task}"})

        # ── 第四步：注入历史记忆（当前轮次内的执行记录，仅在重规划时有内容）──
        # 只含当前轮之前的操作记录，不包含当前轮（当前轮还未开始执行）
        history_msgs = [
            m.to_openai_dict()
            for m in self._messages
            if m.meta.get("iteration", 9999) < current_iteration
        ]

        if history_msgs:
            messages.extend(history_msgs)
            logger.info(
                f"{Fore.CYAN}[记忆读取] 规划引擎注入 {len(history_msgs)} 条任务内历史记忆消息 "
                f"(iteration < {current_iteration}，重规划场景){Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.CYAN}[记忆读取] 首次规划（iteration=0），无任务内历史记忆注入{Style.RESET_ALL}"
            )

        # 本轮规划触发指令
        messages.append({"role": "user", "content": trigger_prompt})

        logger.info(
            f"{Fore.GREEN}[记忆读取] 规划 messages 组装完成，共 {len(messages)} 条 "
            f"(其中历史记忆 {len(history_msgs)} 条){Style.RESET_ALL}"
        )

        # ── 打印每条 message 的角色和内容摘要，方便调试查看传给 LLM 的结构 ──
        # 黄色分隔线让日志更易区分规划阶段的 messages 边界
        logger.info(f"{Fore.YELLOW}{'─'*60}{Style.RESET_ALL}")
        logger.info(f"{Fore.YELLOW}[传给LLM的messages结构 - 规划引擎]{Style.RESET_ALL}")
        for i, msg in enumerate(messages):
            role = msg.get("role", "?")
            # 工具调用消息特殊展示（assistant 发起 Function Calling）
            if msg.get("tool_calls"):
                tool_name = msg["tool_calls"][0]["function"]["name"]
                call_id = msg["tool_calls"][0]["id"]
                logger.info(
                    f"{Fore.YELLOW}  [{i}] role=assistant | "
                    f"tool_calls=[{{id:{call_id}, name:{tool_name}}}]{Style.RESET_ALL}"
                )
            elif msg.get("tool_call_id"):
                # tool role 返回工具执行结果
                content_preview = str(msg.get("content", ""))[:120].replace("\n", " ")
                logger.info(
                    f"{Fore.YELLOW}  [{i}] role=tool | "
                    f"name={msg.get('name','?')} | "
                    f"content={content_preview!r}{Style.RESET_ALL}"
                )
            else:
                # system / user / assistant 普通消息
                content_preview = str(msg.get("content", ""))[:120].replace("\n", " ")
                logger.info(
                    f"{Fore.YELLOW}  [{i}] role={role} | "
                    f"content={content_preview!r}{Style.RESET_ALL}"
                )
        logger.info(f"{Fore.YELLOW}{'─'*60}{Style.RESET_ALL}")

        return messages

    def build_messages_for_reflection(
        self,
        system_prompt: str,
        current_iteration: int,
        trigger_prompt: str = "请基于以上本轮的执行过程，对任务完成情况进行反思评估。"
    ) -> list[dict]:
        """
        为反思引擎组装完整的 messages 数组

        结构（按顺序）：
          [0] system  → 反思角色定义
          [1] user    → 原始任务描述
          [...] 本轮及历史记忆消息（含当前轮的工具调用结果，排除当前轮的反思自身）
          [-1] user   → 反思触发指令

        为什么包含 <= current_iteration 的记录，但排除 reflection 类型：
          反思阶段需要看到「本轮刚发生了什么」（工具调用、用户操作等），
          但不应包含「本轮的反思结论」（因为还没有），排除后可防止 LLM 幻觉。

        Args:
            system_prompt: 反思角色定义 + 评估要求（来自反思引擎构建）
            current_iteration: 当前迭代轮次（0-indexed）
            trigger_prompt: 发给 LLM 的本轮反思触发指令

        Returns:
            list[dict]: 符合 OpenAI messages 格式的列表
        """
        # ── 第一步：system 角色定义 ──
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
        ]

        # ── 第二步：注入前置上下文（会话摘要 + 对话历史）──
        # 与规划引擎保持一致：先给 LLM 历史会话背景，再看本轮任务
        if self.context_messages:
            messages.extend(self.context_messages)
            logger.info(
                f"{Fore.GREEN}[记忆读取] 反思引擎注入 {len(self.context_messages)} 条前置上下文记忆"
                f"（会话摘要+对话历史）{Style.RESET_ALL}"
            )
        else:
            logger.debug(
                f"{Fore.CYAN}[记忆读取] 反思引擎：无前置上下文（首次会话或会话摘要为空）{Style.RESET_ALL}"
            )

        # ── 第三步：当前任务描述 ──
        messages.append({"role": "user", "content": f"任务目标: {self.task}"})

        # ── 第四步：注入当前轮的执行记录（含工具调用结果，排除反思自身）──
        # 包含当前轮的执行记录，但排除当前轮的 reflection 消息自身
        # 为什么排除当前轮 reflection：反思评估是这次调用要产出的结果，不能作为输入
        history_msgs = [
            m.to_openai_dict()
            for m in self._messages
            if m.meta.get("iteration", 9999) <= current_iteration
            and not (
                m.meta.get("iteration") == current_iteration
                and m.meta.get("entry_type") == "reflection"
            )
        ]

        if history_msgs:
            messages.extend(history_msgs)
            logger.info(
                f"{Fore.CYAN}[记忆读取] 反思引擎注入 {len(history_msgs)} 条记忆消息 "
                f"(iteration <= {current_iteration}, 排除当前轮 reflection){Style.RESET_ALL}"
            )

        messages.append({"role": "user", "content": trigger_prompt})

        logger.info(
            f"{Fore.GREEN}[记忆读取] 反思 messages 组装完成，共 {len(messages)} 条{Style.RESET_ALL}"
        )

        # ── 打印每条 message 的角色和内容摘要，方便调试查看传给 LLM 的结构 ──
        logger.info(f"{Fore.MAGENTA}{'─'*60}{Style.RESET_ALL}")
        logger.info(f"{Fore.MAGENTA}[传给LLM的messages结构 - 反思引擎]{Style.RESET_ALL}")
        for i, msg in enumerate(messages):
            role = msg.get("role", "?")
            if msg.get("tool_calls"):
                tool_name = msg["tool_calls"][0]["function"]["name"]
                call_id = msg["tool_calls"][0]["id"]
                logger.info(
                    f"{Fore.MAGENTA}  [{i}] role={role} | "
                    f"tool_calls=[{{id:{call_id}, name:{tool_name}}}]{Style.RESET_ALL}"
                )
            elif msg.get("tool_call_id"):
                content_preview = str(msg.get("content", ""))[:120].replace("\n", " ")
                logger.info(
                    f"{Fore.MAGENTA}  [{i}] role={role} | "
                    f"name={msg.get('name','?')} | "
                    f"content_preview={content_preview!r}{Style.RESET_ALL}"
                )
            else:
                content_preview = str(msg.get("content", ""))[:120].replace("\n", " ")
                logger.info(
                    f"{Fore.MAGENTA}  [{i}] role={role} | "
                    f"content_preview={content_preview!r}{Style.RESET_ALL}"
                )
        logger.info(f"{Fore.MAGENTA}{'─'*60}{Style.RESET_ALL}")

        return messages

    def get_timeline(self) -> list[dict]:
        """
        返回完整的时序记忆快照（含 meta 元数据）

        用于：
          - 调试追踪（打印整轮记忆流）
          - 前端可视化（通过 SSE 推送 memory_snapshot）
          - 日志记录
        """
        return [
            {**m.to_openai_dict(), "meta": m.meta}
            for m in self._messages
        ]

    def get_stats(self) -> dict:
        """
        返回记忆统计信息（用于日志监控）
        """
        entry_type_counts: dict[str, int] = {}
        for m in self._messages:
            et = m.meta.get("entry_type", "unknown")
            entry_type_counts[et] = entry_type_counts.get(et, 0) + 1

        return {
            "total_messages": len(self._messages),
            "entry_types": entry_type_counts,
            "iterations_covered": list({
                m.meta.get("iteration", -1)
                for m in self._messages
                if "iteration" in m.meta
            }),
            "started_at": self.started_at,
            "elapsed_seconds": round(time.time() - self.started_at, 2)
        }
