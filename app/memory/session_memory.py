"""
会话级任务摘要记忆系统 (Session Memory)
=====================================

本模块负责管理同一个对话会话（conversation_id）下的跨任务记忆。
每次单轮任务执行完毕后，将从 AgentRunMemory 与最终执行结果中提取一条压缩摘要，
并在下一次属于该会话的任务执行前，将其作为上下文注入，帮助 LLM 了解此前的对话进展、
关键结论，以及可直接复用的精确标识（如安装引用、URL、命令、资源 ID 等）。

作者: AI Agent Team
创建时间: 2026-03-06
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from colorama import Fore, Style
from loguru import logger

from app.memory.agent_run_memory import AgentRunMemory
from app.utils.llm_output_parser import (
    compact_user_visible_text,
    extract_user_visible_result,
    sanitize_model_payload,
)

# 可执行技能引用：owner/repo@skill
PACKAGE_REF_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._-])([A-Za-z0-9._-]+/[A-Za-z0-9._-]+@[A-Za-z0-9._-]+)(?![A-Za-z0-9._-])"
)

# Skills CLI 安装命令（用于跨轮复用历史精确安装命令）
SKILLS_ADD_COMMAND_PATTERN = re.compile(
    r"(npx\s+(?:--yes\s+)?skills\s+(?:add|install)\s+[^\s`]+)",
    flags=re.IGNORECASE,
)

# 通用 URL（如下载地址、详情链接）
URL_PATTERN = re.compile(r"(https?://[^\s)>\]}]+)", flags=re.IGNORECASE)
ACTIONABLE_FACT_LINE_PATTERN = re.compile(
    r"^-\s*(?P<kind>[A-Za-z_][A-Za-z0-9_-]*)\s*:\s*"
    r"(?:(?P<label>.*?)\s*->\s*)?(?P<value>.+?)\s*$"
)

MAX_ACTIONABLE_FACTS = 8
MAX_STEP_SUMMARY_COUNT = 4
MAX_CONTEXT_JSON_LENGTH = 1200


def _normalize_whitespace(text: str) -> str:
    """压缩连续空白，避免历史摘要中出现难读的杂乱空格。"""
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_fact_label(text: str) -> str:
    """
    清洗动作事实的标签文本。

    设计原因：
    - 技能/工具结果里常带 Markdown 粗体、列表前缀、提示词语（推荐/可选择）；
    - 若直接原样写入会话记忆，下一轮规划很难把“标签 -> 精确标识”的对应关系看清楚；
    - 因此这里统一把标签压缩为适合跨轮复用的短语。
    """
    candidate = str(text or "")
    candidate = re.sub(r"^[\-\*\d\.\)\s>]+", "", candidate)
    candidate = candidate.replace("**", "").replace("`", "")

    # 优先截取冒号前的“类别标签”部分，例如：
    # “AI/科技领域新闻：推荐 yyh211/...” -> “AI/科技领域新闻”
    colon_match = re.search(r"[：:]", candidate)
    if colon_match:
        candidate = candidate[: colon_match.start()]

    candidate = re.sub(r"(推荐|可选择|可选|建议|安装命令|依据)\s*$", "", candidate)
    candidate = candidate.rstrip("，,。;；:：- ")
    candidate = _normalize_whitespace(candidate)
    return candidate[:48]


def _extract_line_label(line: str, value_start_index: int) -> str:
    """
    从单行文本中推断“人类标签”。

    例如：
    - “- **AI/科技领域新闻**：推荐 **yyh211/...**” -> “AI/科技领域新闻”
    - “安装命令：npx skills add yyh211/...” -> “安装命令”
    """
    prefix = line[:value_start_index]
    label = _clean_fact_label(prefix)
    return label


def _trim_payload(
    payload: Any,
    *,
    max_depth: int = 2,
    max_items: int = 6,
    max_string_length: int = 220,
) -> Any:
    """
    将结构化载荷裁剪为适合长期会话记忆保存的大小。

    设计原因：
    - 会话记忆需要保留关键事实，但不能把完整 step_results / HTML / 大段 JSON 原样灌回上下文；
    - 这里做统一裁剪，确保记忆既“有用”，又不会导致跨轮上下文失控膨胀。
    """
    sanitized = sanitize_model_payload(payload)

    if isinstance(sanitized, str):
        return compact_user_visible_text(sanitized, limit=max_string_length)
    if isinstance(sanitized, (int, float, bool)) or sanitized is None:
        return sanitized
    if max_depth <= 0:
        return compact_user_visible_text(extract_user_visible_result(sanitized), limit=max_string_length)

    if isinstance(sanitized, list):
        trimmed_items = [
            _trim_payload(
                item,
                max_depth=max_depth - 1,
                max_items=max_items,
                max_string_length=max_string_length,
            )
            for item in sanitized[:max_items]
        ]
        if len(sanitized) > max_items:
            trimmed_items.append(f"...（其余 {len(sanitized) - max_items} 项已省略）")
        return trimmed_items

    if isinstance(sanitized, dict):
        trimmed_dict: Dict[str, Any] = {}
        items = list(sanitized.items())
        for key, value in items[:max_items]:
            trimmed_dict[str(key)] = _trim_payload(
                value,
                max_depth=max_depth - 1,
                max_items=max_items,
                max_string_length=max_string_length,
            )
        if len(items) > max_items:
            trimmed_dict["__truncated__"] = f"...（其余 {len(items) - max_items} 项已省略）"
        return trimmed_dict

    return compact_user_visible_text(str(sanitized), limit=max_string_length)


def _collect_text_blobs(final_result: Dict[str, Any]) -> List[tuple[str, str]]:
    """
    从最终执行结果中提取可分析的文本片段。

    设计目标：
    - 会话摘要不应只依赖 reflection.summary；
    - 对用户真正有价值的“精确引用/命令/URL”往往出现在 final_result.result
      或 step_results.result 中；
    - 因此这里统一收集这些文本，再做结构化事实提取。
    """
    blobs: List[tuple[str, str]] = []
    sanitized_final = sanitize_model_payload(final_result or {})

    def _append(label: str, payload: Any) -> None:
        if payload in (None, "", [], {}):
            return
        text = extract_user_visible_result(payload)
        if not text:
            try:
                text = json.dumps(sanitize_model_payload(payload), ensure_ascii=False, default=str)
            except Exception:
                text = str(payload)
        text = str(text or "").strip()
        if text:
            blobs.append((label, text))

    _append("final_result", sanitized_final.get("result"))

    for idx, step in enumerate(sanitized_final.get("step_results", []) or [], 1):
        if not isinstance(step, dict):
            continue
        action = step.get("action", "unknown")
        name = step.get("tool_name") or step.get("skill_id") or step.get("agent_id") or action
        _append(f"step[{idx}]-{name}-result", step.get("result"))
        _append(f"step[{idx}]-{name}-error", step.get("error"))

    reflection = sanitized_final.get("reflection")
    if isinstance(reflection, dict):
        _append("reflection-summary", reflection.get("summary"))
        _append("reflection-feedback", reflection.get("feedback"))

    return blobs


def _extract_actionable_facts(final_result: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    从最终结果中提取跨轮可直接复用的“动作事实”。

    这是本次修复的关键点：
    - 以前只保留自然语言摘要，导致下一轮知道“查过”，却不知道“具体该用哪个引用”；
    - 现在统一把 package_ref / 安装命令 / URL 这类精确标识抽出来，
      让下一轮规划可以直接复用，而不是再次搜索或猜测。
    """
    facts: List[Dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def _append_fact(kind: str, value: str, *, label: str = "", source: str = "") -> None:
        normalized_value = str(value or "").strip()
        cleaned_label = _clean_fact_label(label)
        if not normalized_value:
            return
        dedupe_key = (kind, cleaned_label.lower(), normalized_value)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        fact: Dict[str, str] = {"kind": kind, "value": normalized_value}
        if cleaned_label:
            fact["label"] = cleaned_label
        if source:
            fact["source"] = source
        facts.append(fact)

    for source, text in _collect_text_blobs(final_result):
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        for line in lines:
            for match in PACKAGE_REF_PATTERN.finditer(line):
                ref = match.group(1).strip()
                label = _extract_line_label(line, match.start())
                _append_fact("package_ref", ref, label=label, source=source)

            for match in SKILLS_ADD_COMMAND_PATTERN.finditer(line):
                command = _normalize_whitespace(match.group(1))
                label = _extract_line_label(line, match.start())
                _append_fact("command", command, label=label, source=source)

            for match in URL_PATTERN.finditer(line):
                url = match.group(1).strip()
                label = _extract_line_label(line, match.start())
                _append_fact("url", url, label=label, source=source)

    # 标签更明确的事实优先展示，避免无标签的通用候选淹没掉“AI/科技领域新闻 -> xxx”这类关键映射
    facts.sort(key=lambda item: (0 if item.get("label") else 1, item.get("kind", ""), item.get("value", "")))
    return facts[:MAX_ACTIONABLE_FACTS]


def _append_actionable_fact(
    facts: List[Dict[str, str]],
    seen: set[tuple[str, str, str]],
    fact: Dict[str, Any],
) -> None:
    """
    归一化并追加一个动作事实。

    设计原因：
    - 会话上下文里的事实可能来自结构化 JSON，也可能来自渲染后的文本行；
    - LangGraph 规划层需要统一读取这些事实，不能假设来源形态一致；
    - 因此在公共记忆层提供统一归一化入口，避免每个调用方重复写解析逻辑。
    """
    if not isinstance(fact, dict):
        return

    kind = str(fact.get("kind", "") or "").strip()
    value = str(fact.get("value", "") or "").strip()
    label = _clean_fact_label(str(fact.get("label", "") or "").strip())
    source = str(fact.get("source", "") or "").strip()
    if not kind or not value:
        return

    dedupe_key = (kind.lower(), label.lower(), value)
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)

    normalized_fact: Dict[str, str] = {
        "kind": kind,
        "value": value,
    }
    if label:
        normalized_fact["label"] = label
    if source:
        normalized_fact["source"] = source
    facts.append(normalized_fact)


def extract_actionable_facts_from_context_messages(
    context_messages: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """
    从会话上下文消息中反向提取动作事实。

    设计原因：
    - Session Memory 在跨任务传递时会把结构化事实渲染成自然语言消息；
    - 规划层若仅依赖模型“自己读懂”这些消息，安装类任务仍可能忽略已知 package_ref；
    - 因此这里提供公共解析器，把消息里的事实重新抽回结构化数据，供框架级规则直连复用。
    """
    facts: List[Dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for message in context_messages or []:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content", "") or "")
        if not content:
            continue

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("关键数据:"):
                payload_text = stripped.split("关键数据:", 1)[-1].strip()
                try:
                    payload = json.loads(payload_text)
                except Exception:
                    payload = None
                if isinstance(payload, dict):
                    for fact in payload.get("actionable_facts", []) or []:
                        _append_actionable_fact(facts, seen, fact)

            match = ACTIONABLE_FACT_LINE_PATTERN.match(stripped)
            if not match:
                continue
            _append_actionable_fact(
                facts,
                seen,
                {
                    "kind": match.group("kind"),
                    "label": match.group("label") or "",
                    "value": match.group("value") or "",
                },
            )

    return facts[:MAX_ACTIONABLE_FACTS]


def _summarize_step_results(final_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """提炼 step_results，保留下一轮最有价值的步骤级结论。"""
    summaries: List[Dict[str, Any]] = []
    for step in (sanitize_model_payload(final_result or {}).get("step_results", []) or [])[:MAX_STEP_SUMMARY_COUNT]:
        if not isinstance(step, dict):
            continue

        action = str(step.get("action", "unknown") or "unknown")
        name = step.get("tool_name") or step.get("skill_id") or step.get("agent_id") or ""
        summary: Dict[str, Any] = {
            "action": action,
            "success": bool(step.get("success", False)),
        }
        if name:
            summary["name"] = str(name)

        if step.get("result") not in (None, ""):
            summary["result_preview"] = compact_user_visible_text(
                extract_user_visible_result(step.get("result")),
                limit=280,
            )
        if step.get("error") not in (None, ""):
            summary["error_preview"] = compact_user_visible_text(
                extract_user_visible_result(step.get("error")),
                limit=220,
            )
        summaries.append(summary)

    total_count = len((sanitize_model_payload(final_result or {}).get("step_results", []) or []))
    if total_count > MAX_STEP_SUMMARY_COUNT:
        summaries.append({"truncated": True, "omitted_count": total_count - MAX_STEP_SUMMARY_COUNT})
    return summaries


def _extract_structured_result(final_result: Dict[str, Any]) -> Optional[Any]:
    """
    提取适合跨轮保留的结构化结果。

    兼容场景：
    - 工具直接返回 JSON / dict（订单号、状态、价格等）
    - 结果已被顶层封装，但 step_results 中仍保留结构化原始结果
    """
    sanitized_final = sanitize_model_payload(final_result or {})
    direct_result = sanitized_final.get("result")
    if isinstance(direct_result, (dict, list)):
        return _trim_payload(direct_result)

    step_results = sanitized_final.get("step_results", []) or []
    structured_candidates: List[Dict[str, Any]] = []
    for step in step_results[:MAX_STEP_SUMMARY_COUNT]:
        if not isinstance(step, dict):
            continue
        result = step.get("result")
        if isinstance(result, (dict, list)):
            structured_candidates.append(
                {
                    "action": step.get("action", "unknown"),
                    "name": step.get("tool_name") or step.get("skill_id") or step.get("agent_id") or "",
                    "result": _trim_payload(result),
                }
            )

    if structured_candidates:
        return structured_candidates
    return None


def _extract_key_data(final_result: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    """
    从最终执行结果中提炼适合跨轮复用的关键数据。

    返回：
    - key_data：结构化关键数据
    - result_preview：最终用户可见结果的短摘要（供 summary 回退使用）
    """
    sanitized_final = sanitize_model_payload(final_result or {})
    key_data: Dict[str, Any] = {}

    result_preview = ""
    if sanitized_final.get("result") not in (None, ""):
        result_preview = compact_user_visible_text(
            extract_user_visible_result(sanitized_final.get("result")),
            limit=320,
        )

    structured_result = _extract_structured_result(sanitized_final)
    if structured_result not in (None, {}, []):
        key_data["structured_result"] = structured_result

    step_results_summary = _summarize_step_results(sanitized_final)
    if step_results_summary:
        key_data["step_results_summary"] = step_results_summary

    actionable_facts = _extract_actionable_facts(sanitized_final)
    if actionable_facts:
        key_data["actionable_facts"] = actionable_facts

    if result_preview:
        key_data["result_preview"] = result_preview

    return key_data, result_preview


@dataclass
class TaskSummaryEntry:
    """一次 Agent 任务执行的压缩摘要条目"""

    task_id: str
    agent_id: str
    agent_name: str
    task: str
    success: bool
    summary: str
    key_data: dict
    tools_used: list[str]
    iterations: int
    started_at: float
    ended_at: float
    # 记录本次任务中用户的操作行为（如确认或拒绝某个工具）
    user_actions: list[dict] = field(default_factory=list)

    def _build_actionable_fact_lines(self) -> List[str]:
        """
        将结构化动作事实格式化为更容易被下一轮规划直接消费的文本行。

        为什么不只塞一段 JSON：
        - JSON 对调试友好，但 LLM 在规划时对“AI/科技领域新闻 -> package_ref”这种
          一眼可见的映射更敏感；
        - 因此这里同时保留“精确映射文本 + 紧凑 JSON”，兼顾模型可读性与可观测性。
        """
        facts = self.key_data.get("actionable_facts") or []
        if not isinstance(facts, list):
            return []

        lines: List[str] = []
        for fact in facts[:MAX_ACTIONABLE_FACTS]:
            if not isinstance(fact, dict):
                continue
            kind = fact.get("kind", "fact")
            value = str(fact.get("value", "") or "").strip()
            label = str(fact.get("label", "") or "").strip()
            if not value:
                continue

            if label:
                lines.append(f"- {kind}: {label} -> {value}")
            else:
                lines.append(f"- {kind}: {value}")

        return lines

    def _build_compact_key_data_json(self) -> str:
        """构建适合注入上下文的紧凑 key_data JSON。"""
        if not self.key_data:
            return ""

        compact_key_data = {
            "structured_result": self.key_data.get("structured_result"),
            "step_results_summary": self.key_data.get("step_results_summary"),
            "actionable_facts": (self.key_data.get("actionable_facts") or [])[:4],
        }
        compact_key_data = {k: v for k, v in compact_key_data.items() if v not in (None, "", [], {})}
        if not compact_key_data:
            return ""

        payload = json.dumps(compact_key_data, ensure_ascii=False, default=str)
        if len(payload) > MAX_CONTEXT_JSON_LENGTH:
            payload = payload[:MAX_CONTEXT_JSON_LENGTH] + "...（关键数据已截断）"
        return payload

    def to_context_message(self) -> dict:
        """
        将摘要转换为发给 LLM 的 user 消息对象。

        作为后续任务启动时的前置上下文信息，不仅保留结论，
        也保留下一轮可直接复用的关键标识，减少重复搜索与重复试错。
        """
        status = "✅ 成功" if self.success else "❌ 失败"
        lines = [
            "【历史任务摘要】",
            f"任务: {self.task}",
            f"结果: {status}",
            f"结论: {self.summary}",
        ]

        actionable_fact_lines = self._build_actionable_fact_lines()
        if actionable_fact_lines:
            lines.append("可直接复用事实:")
            lines.extend(actionable_fact_lines)

        compact_key_data_json = self._build_compact_key_data_json()
        if compact_key_data_json:
            lines.append(f"关键数据: {compact_key_data_json}")

        if self.tools_used:
            lines.append(f"使用工具: {', '.join(self.tools_used)}")

        if self.user_actions:
            action_desc = []
            for act in self.user_actions:
                tool = act.get("tool", "")
                action = act.get("action", "")
                if action == "reject":
                    action_desc.append(f"拒绝了 [{tool}] 操作")
                elif action == "confirm":
                    action_desc.append(f"确认了 [{tool}] 操作")
            if action_desc:
                lines.append(f"用户操作行为: {'; '.join(action_desc)}")

        lines.append(f"执行轮次: {self.iterations} 轮")
        return {"role": "user", "content": "\n".join(lines)}


class AgentSessionMemory:
    """会话级任务摘要仓库"""

    def __init__(self, conversation_id: str, max_entries: int = 10):
        self.conversation_id = conversation_id
        self.max_entries = max_entries
        self._entries: list[TaskSummaryEntry] = []

    def append_task_summary(self, entry: TaskSummaryEntry) -> None:
        """追加一条任务摘要，并维持最大数量限制"""
        self._entries.append(entry)
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

        logger.debug(
            f"{Fore.CYAN}[会话记忆] 会话 {self.conversation_id} 新增任务摘要, "
            f"当前共 {len(self._entries)} 条{Style.RESET_ALL}"
        )

    def build_context_messages(self) -> list[dict]:
        """构建待注入到 messages 前置的列表"""
        return [entry.to_context_message() for entry in self._entries]

    def get_summary_list(self) -> list[dict]:
        """返回供调试或展示的条目列表"""
        return [asdict(e) for e in self._entries]


def extract_summary_from_run_memory(
    run_memory: AgentRunMemory,
    final_result: Dict[str, Any],
) -> TaskSummaryEntry:
    """
    通过解析 AgentRunMemory 与最终执行结果，提取会话级摘要。

    当前规则重点：
    1. 仍保留 reflection.summary 作为“人类可读结论”；
    2. 额外从 final_result / step_results 中抽出结构化关键数据；
    3. 特别保留可直接复用的精确标识（package_ref / 命令 / URL 等），
       解决“上一轮查到了，但下一轮只记得摘要、忘了具体引用”的问题。
    """
    iterations = 0
    tools_used = set()
    user_actions = []

    for msg in run_memory._messages:
        meta = msg.meta
        it = meta.get("iteration", 0)
        entry_type = meta.get("entry_type")

        if it > iterations:
            iterations = it

        if entry_type == "tool_call" and "tool_name" in meta:
            tools_used.add(meta["tool_name"])
        if entry_type == "skill_call" and "skill_id" in meta:
            tools_used.add(meta["skill_id"])
        if entry_type == "user_action":
            user_actions.append(
                {
                    "action": meta.get("action", ""),
                    "tool": meta.get("tool_name", ""),
                    "iteration": it,
                }
            )

    summary_text = ""
    for msg in reversed(run_memory._messages):
        if msg.meta.get("entry_type") != "reflection":
            continue
        content = msg.content or ""
        if "总结: " in content:
            summary_text = content.split("总结: ", 1)[-1].split("\n", 1)[0].strip()
        else:
            summary_text = _normalize_whitespace(content)
        if summary_text:
            break

    key_data, result_preview = _extract_key_data(final_result or {})

    if not summary_text:
        fallback_text = extract_user_visible_result(
            (final_result or {}).get("error") or (final_result or {}).get("result") or "任务执行完毕"
        )
        summary_text = compact_user_visible_text(fallback_text or result_preview or "任务执行完毕", limit=300)

    success = bool((final_result or {}).get("success", False))

    return TaskSummaryEntry(
        task_id=uuid.uuid4().hex,
        agent_id=run_memory.agent_id,
        agent_name=run_memory.agent_name,
        task=run_memory.task,
        success=success,
        summary=summary_text,
        key_data=key_data,
        tools_used=list(tools_used),
        user_actions=user_actions,
        iterations=iterations + 1,  # iteration 从 0 开始计数，展示时转为实际轮次
        started_at=run_memory.started_at,
        ended_at=time.time(),
    )


# =============================================================================
# 全局注册表（原型单例实现）
# =============================================================================

_session_registry: Dict[str, AgentSessionMemory] = {}


def get_session_memory(conversation_id: str) -> AgentSessionMemory:
    """获取或新建会话记忆仓库"""
    if conversation_id not in _session_registry:
        _session_registry[conversation_id] = AgentSessionMemory(conversation_id)
    return _session_registry[conversation_id]


def clear_session_memory(conversation_id: str) -> None:
    """清空指定的会话记忆"""
    if conversation_id in _session_registry:
        del _session_registry[conversation_id]
        logger.info(f"{Fore.YELLOW}[会话记忆] 已清空 conversation_id={conversation_id}{Style.RESET_ALL}")
