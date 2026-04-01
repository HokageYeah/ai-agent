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
    build_balanced_text_preview,
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
MAX_RELEVANT_SESSION_ENTRIES = 4
MAX_RELEVANT_CONVERSATION_MESSAGES = 6
MAX_RECENT_CONVERSATION_WINDOW = 4
MAX_CONTEXT_MESSAGE_LENGTH = 1000
MAX_FOLLOW_UP_CAPABILITY_MESSAGES = 1
MAX_HISTORY_ANSWER_CANDIDATES = 3
MAX_CONVERSATION_RECALL_TURNS = 6
MAX_CONVERSATION_RECALL_JSON_LENGTH = 1800

FOLLOW_UP_TASK_HINTS = (
    "继续",
    "刚才",
    "刚刚",
    "上一个",
    "上次",
    "前面",
    "上一轮",
    "上一条",
    "那个",
    "这些",
    "其中",
    "它",
    "同一个",
)

CAPABILITY_INVOCATION_HINT_PATTERN = re.compile(
    r"(?:^|[，,。；;\s])(?:使用|用|调用|通过|借助|让|请使用|请用)\s*"
    r"([\u4e00-\u9fffA-Za-z0-9._/@-]{2,32})"
    r"(?=(?:相关)?(?:技能|工具|助手|智能体|agent|Agent))"
)

TASK_TOPIC_HINT_PATTERN = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9._/@-]{2,24})(?=(?:相关)?(?:技能|工具|订单|状态|结果|记录|命令|列表|价格|天气|物流|文件|链接|地址))"
)
TASK_DOMAIN_HINT_PATTERN = re.compile(
    r"(技能|skill|skills|工具|tool|tools|订单|order|orders|天气|weather|物流|logistics|文件|file|files|价格|price|prices|链接|link|links|地址|url)",
    flags=re.IGNORECASE,
)
QUOTED_HINT_PATTERN = re.compile(r"[\"“'‘](.+?)[\"”'’]")
ALNUM_HINT_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._/@-]{2,}")
NUMERIC_HINT_PATTERN = re.compile(r"(?<!\d)\d{2,}(?!\d)")
HISTORY_TASK_SUMMARY_HEADER = "【历史任务摘要】"
HISTORY_TASK_PREFIX = "任务:"
HISTORY_SOURCE_USER_TASK_PREFIX = "主线任务:"
HISTORY_RESULT_PREFIX = "结果:"
HISTORY_SUMMARY_PREFIX = "结论:"
HISTORY_KEY_DATA_PREFIX = "关键数据:"
HISTORY_ENTRY_SCOPE_PREFIX = "记录来源:"
FOLLOW_UP_CAPABILITY_CONTEXT_HEADER = "【历史能力轨迹】"
FOLLOW_UP_CAPABILITY_JSON_PREFIX = "能力轨迹数据:"
CONVERSATION_RECALL_CONTEXT_HEADER = "【会话主线回顾】"
CONVERSATION_RECALL_JSON_PREFIX = "会话主线数据:"


def _normalize_whitespace(text: str) -> str:
    """压缩连续空白，避免历史摘要中出现难读的杂乱空格。"""
    return re.sub(r"\s+", " ", text or "").strip()


def _append_unique_text(items: List[str], raw_value: str) -> None:
    """
    以去重保序方式追加文本项。

    设计原因：
    - 能力轨迹会同时从 run_memory 与嵌套 step_results 中抽取；
    - 若不统一去重，同一个 `find-skills / general_agent / shell_exec` 会在摘要里重复多次。
    """
    value = _normalize_whitespace(str(raw_value or ""))
    if not value or value in items:
        return
    items.append(value)


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


def _contains_follow_up_task_hint(task: str) -> bool:
    """检测当前任务是否包含“继续/指代上一轮结果”的表述。"""
    normalized_task = _normalize_whitespace(task).lower()
    return any(hint in normalized_task for hint in FOLLOW_UP_TASK_HINTS)


def _is_conversation_recall_request(task: str) -> bool:
    """
    判断当前任务是否属于“回顾/追问会话历史”的元记忆请求。

    设计原因：
    - 历史回顾类任务的主题不一定是订单号、技能名这类实体词，
      常见形式反而是“我的第一个问题是什么”“上一轮你做了什么”；
    - 若仍沿用普通主题匹配，这类任务往往拿不到任何上下文，LLM 只能自指回答；
    - 因此需要在会话记忆公共层识别“用户在问对话本身”，统一注入主线时间线。
    """
    normalized_task = _normalize_whitespace(task or "").lower()
    if not normalized_task:
        return False

    recall_patterns = (
        r"第一个(?:问题|提问|请求|任务)",
        r"第一轮(?:问题|提问|任务|请求|说了什么|聊了什么|做了什么)?",
        r"最开始(?:的问题|提问|请求|任务|说过什么|聊过什么)?",
        r"(?:之前|前面|刚才|上一轮|上一个|上次).{0,12}(?:问题|提问|任务|请求|说过|聊过|做过|结果|答案|回答)",
        r"(?:我们|你|我).{0,10}(?:聊到哪|聊过什么|说过什么|问过什么|做过什么)",
        r"(?:历史记录|对话历史|会话历史|聊天记录)",
        r"(?:回顾|总结一下).{0,12}(?:对话|会话|刚才|之前|前面)",
        r"what was my first question",
        r"what did i ask",
        r"previous question",
        r"conversation history",
        r"history of (?:our )?conversation",
    )
    return any(
        re.search(pattern, normalized_task, flags=re.IGNORECASE)
        for pattern in recall_patterns
    )


def _normalize_relevance_hint(text: str) -> str:
    """
    清洗任务相关性线索，尽量提取适合跨轮匹配的主题词。

    设计原因：
    - 用户任务里常有“查询/继续/相关/哪个”这类过程词；
    - 直接拿整句做匹配容易把所有历史都打成高分；
    - 因此这里尽量压缩出“浏览器 / 新闻 / mcp / 1002”这类真正可判别的线索。
    """
    candidate = _normalize_whitespace(text or "").lower()
    candidate = re.sub(
        r"^(?:使用|查询|查找|继续|请|帮我|帮忙|告诉我|告诉|给我|把|将|对于|关于|我想知道|想知道)+",
        "",
        candidate,
    )
    candidate = re.sub(
        r"^(?:刚才那个|刚才这些|刚才这些个|刚才|那个|这个|这些|前面那个|前面这些|前面|上次那个|上次|上一轮那个|上一轮)+",
        "",
        candidate,
    )
    candidate = re.sub(
        r"(?:相关|技能|工具|订单|状态|结果|记录|命令|列表|价格|天气|物流|文件|链接|地址|下载安装量|安装量|下载量)+$",
        "",
        candidate,
    )
    candidate = candidate.strip(" 的里中这个那个这些前面上次刚才")
    return candidate[:48]


def _extract_task_relevance_hints(task: str) -> List[str]:
    """
    从任务文本中提炼高价值线索。

    线索优先级：
    1. package_ref / URL / 命令等精确标识；
    2. 英文技术词、数字 ID；
    3. “浏览器相关技能”里的“浏览器”这类主题词；
    4. 引号中的显式目标词。
    """
    normalized_task = _normalize_whitespace(task or "")
    if not normalized_task:
        return []

    hints: List[str] = []
    seen: set[str] = set()

    def _append_hint(raw_hint: str) -> None:
        hint = _normalize_relevance_hint(raw_hint)
        if len(hint) < 2:
            return
        if hint in seen:
            return
        seen.add(hint)
        hints.append(hint)

    for pattern in (PACKAGE_REF_PATTERN, URL_PATTERN, SKILLS_ADD_COMMAND_PATTERN):
        for match in pattern.finditer(normalized_task):
            _append_hint(match.group(1))

    for match in QUOTED_HINT_PATTERN.finditer(normalized_task):
        _append_hint(match.group(1))

    for match in TASK_TOPIC_HINT_PATTERN.finditer(normalized_task):
        _append_hint(match.group(1))

    for match in ALNUM_HINT_PATTERN.finditer(normalized_task):
        _append_hint(match.group(0))

    for match in NUMERIC_HINT_PATTERN.finditer(normalized_task):
        _append_hint(match.group(0))

    return hints


def _extract_task_carrier_hints(task: str) -> List[str]:
    """
    提取“调用载体”线索，例如“使用 find-skills 技能”里的 `find-skills`。

    设计原因：
    - 在多轮任务里，用户常会重复指定“使用某个 skill / tool / agent”；
    - 这类线索能说明“执行载体相同”，但并不代表“业务主题相同”；
    - 若把它和主题词等价看待，就会出现“同样都用 find-skills，所以把新闻结果带到 mcp 查询里”的污染。
    """
    normalized_task = _normalize_whitespace(task or "")
    if not normalized_task:
        return []

    carrier_hints: List[str] = []
    seen: set[str] = set()
    for match in CAPABILITY_INVOCATION_HINT_PATTERN.finditer(normalized_task):
        hint = _normalize_relevance_hint(match.group(1))
        if len(hint) < 2 or hint in seen:
            continue
        seen.add(hint)
        carrier_hints.append(hint)
    return carrier_hints


def _extract_task_subject_hints(task: str) -> List[str]:
    """
    提取“业务主题 / 实体”线索，并排除掉调用载体线索。

    示例：
    - `使用find-skills技能查询 mcp技能` -> 主题线索应为 `mcp`，而不是 `find-skills`
    - `使用database_query工具查询 1002 订单` -> 主题线索应为 `1002`

    设计原因：
    - 历史记忆应优先围绕“用户真正问的对象”做检索，而不是围绕“用了哪个工具”做检索；
    - 这样同一个技能/工具处理多个不同主题时，才不会把旧主题错误注入到新任务。
    """
    carrier_hints = set(_extract_task_carrier_hints(task))
    return [
        hint
        for hint in _extract_task_relevance_hints(task)
        if hint not in carrier_hints
    ]


def _extract_task_domain_hints(task: str) -> List[str]:
    """
    提取任务所属的“能力域/对象域”线索。

    示例：
    - `继续查询 mcp技能` -> `技能`
    - `继续查订单 1002` -> `订单`

    设计原因：
    - 续问场景下，主题词常会变化（新闻 -> mcp -> 浏览器），但任务仍可能属于同一能力域；
    - 这里单独提炼“技能 / 订单 / 天气”等域线索，帮助框架在不复用旧主题结果的前提下，
      继续沿用正确的执行链路。
    """
    normalized_task = _normalize_whitespace(task or "")
    if not normalized_task:
        return []

    domain_hints: List[str] = []
    seen: set[str] = set()
    for match in TASK_DOMAIN_HINT_PATTERN.finditer(normalized_task):
        hint = str(match.group(1) or "").strip().lower()
        if not hint or hint in seen:
            continue
        seen.add(hint)
        domain_hints.append(hint)
    return domain_hints


def _extract_relevance_match_detail(task: str, candidate_text: str) -> Dict[str, List[str]]:
    """
    区分候选上下文中命中的“主题线索”和“调用载体线索”。

    设计原因：
    - 后续筛选时，“主题线索命中”应优先于“仅命中载体线索”；
    - 例如上一轮是“新闻技能”，本轮是“mcp技能”，两轮都用 find-skills，
      不能因为都命中 `find-skills` 就认为它们属于同一主题上下文。
    """
    normalized_candidate = _normalize_whitespace(candidate_text or "").lower()
    if not normalized_candidate:
        return {
            "subject_hints": [],
            "carrier_hints": [],
        }

    matched_subject_hints = [
        hint
        for hint in _extract_task_subject_hints(task)
        if hint in normalized_candidate
    ]
    matched_carrier_hints = [
        hint
        for hint in _extract_task_carrier_hints(task)
        if hint in normalized_candidate
    ]
    return {
        "subject_hints": matched_subject_hints,
        "carrier_hints": matched_carrier_hints,
    }


def _score_context_relevance(
    *,
    task: str,
    candidate_text: str,
    recency_rank: int,
    has_user_actions: bool = False,
    source_task: str = "",
) -> tuple[int, List[str]]:
    """
    对候选上下文进行任务相关性打分。

    设计目标：
    - 优先保留与当前任务同主题、同标识、同实体的历史；
    - 对“继续/那个/刚才”这类显式续问场景，提升最近上下文权重；
    - 若历史里记录了用户确认/拒绝行为，则即使主题不完全一致，也保留一定优先级，
      避免跨轮丢失用户约束。
    """
    normalized_candidate = _normalize_whitespace(candidate_text or "").lower()
    if not normalized_candidate:
        return 0, []

    score = 0
    reasons: List[str] = []

    follow_up_task = _contains_follow_up_task_hint(task)
    if follow_up_task:
        recency_bonus = max(0, 6 - recency_rank * 2)
        if recency_bonus:
            score += recency_bonus
            reasons.append("续问任务提升最近上下文权重")

    if has_user_actions:
        score += 2
        reasons.append("保留用户确认/拒绝约束")

    normalized_task = _normalize_whitespace(task or "")
    normalized_source_task = _normalize_whitespace(source_task or "")
    if normalized_task and normalized_source_task and normalized_task == normalized_source_task:
        score += 12
        reasons.append("命中相同任务")

    match_detail = _extract_relevance_match_detail(task, normalized_candidate)

    for hint in match_detail["subject_hints"]:
        if "/" in hint or "@" in hint or hint.startswith("http"):
            hint_score = 8
        elif hint.isdigit():
            hint_score = 7
        elif re.search(r"[a-z]", hint):
            hint_score = 6
        else:
            hint_score = 5
        score += hint_score
        reasons.append(f"命中任务线索:{hint}")

    if not _extract_task_subject_hints(task):
        for hint in match_detail["carrier_hints"]:
            score += 2
            reasons.append(f"命中调用载体:{hint}")

    return score, reasons


def _expand_conversation_pair_indexes(
    *,
    conversation_history: List[Dict[str, Any]],
    ranked_indexes: List[int],
    max_messages: int,
) -> set[int]:
    """
    为命中的历史消息补齐最小配对上下文。

    规则说明：
    - 命中 assistant 回复时，优先补前一条 user 提问；
    - 命中 user 提问时，优先补后一条 assistant 回复；
    - 只补最小必要配对，不再像旧逻辑那样整段保留最近窗口，减少主题污染。
    """
    selected_indexes: List[int] = []
    seen_indexes: set[int] = set()
    total_messages = len(conversation_history)

    def _append_index(index: Optional[int]) -> None:
        if index is None or index < 0 or index >= total_messages:
            return
        if index in seen_indexes:
            return
        if len(selected_indexes) >= max_messages:
            return
        seen_indexes.add(index)
        selected_indexes.append(index)

    for index in ranked_indexes:
        _append_index(index)
        role = ""
        if isinstance(conversation_history[index], dict):
            role = str(conversation_history[index].get("role", "") or "").lower()

        if role == "assistant":
            _append_index(index - 1)
        elif role == "user":
            _append_index(index + 1)

        if len(selected_indexes) >= max_messages:
            break

    return set(selected_indexes)


def _trim_context_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """
    压缩上下文消息，避免单条历史消息过长。

    设计原因：
    - 即使做了相关性筛选，某条被选中的历史消息也可能很长；
    - 因此这里再做一次长度裁剪，保证“选中后仍可控”。
    """
    trimmed = dict(message or {})
    content = trimmed.get("content", "")
    if isinstance(content, str):
        rendered = content
    else:
        rendered = extract_user_visible_result(content)
        if not rendered:
            rendered = json.dumps(sanitize_model_payload(content), ensure_ascii=False, default=str)

    trimmed["content"] = build_balanced_text_preview(
        rendered,
        limit=MAX_CONTEXT_MESSAGE_LENGTH,
        note="以下为历史上下文的首尾节选，中间内容仅因控制提示词长度而省略，不代表原始历史缺失。",
    )
    return trimmed


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


def _parse_history_summary_context_message(
    message: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    将历史摘要上下文消息还原为结构化候选。

    设计原因：
    - 主 Agent / 子 Agent / 执行兜底都只能拿到统一的 context_messages；
    - 若每层都各自解析“任务/结论/关键数据”文本，规则会继续散落；
    - 因此在会话记忆公共层集中提供解析器，后续框架能力统一复用。
    """
    if not isinstance(message, dict):
        return None

    content = str(message.get("content", "") or "")
    if HISTORY_TASK_SUMMARY_HEADER not in content:
        return None

    agent_task = ""
    source_user_task = ""
    summary = ""
    success = False
    key_data: Dict[str, Any] = {}
    entry_scope = "primary"

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(HISTORY_TASK_PREFIX):
            agent_task = stripped.split(HISTORY_TASK_PREFIX, 1)[-1].strip()
            continue
        if stripped.startswith(HISTORY_SOURCE_USER_TASK_PREFIX):
            source_user_task = stripped.split(HISTORY_SOURCE_USER_TASK_PREFIX, 1)[-1].strip()
            continue
        if stripped.startswith(HISTORY_RESULT_PREFIX):
            status_text = stripped.split(HISTORY_RESULT_PREFIX, 1)[-1].strip()
            success = ("✅" in status_text) or ("成功" in status_text and "失败" not in status_text)
            continue
        if stripped.startswith(HISTORY_SUMMARY_PREFIX):
            summary = stripped.split(HISTORY_SUMMARY_PREFIX, 1)[-1].strip()
            continue
        if stripped.startswith(HISTORY_KEY_DATA_PREFIX):
            payload_text = stripped.split(HISTORY_KEY_DATA_PREFIX, 1)[-1].strip()
            try:
                payload = json.loads(payload_text)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                key_data = payload
            continue
        if stripped.startswith(HISTORY_ENTRY_SCOPE_PREFIX):
            entry_scope = stripped.split(HISTORY_ENTRY_SCOPE_PREFIX, 1)[-1].strip() or "primary"

    source_task = source_user_task or agent_task

    if not source_task and not summary and not key_data:
        return None

    answer_preview = str(key_data.get("result_preview") or summary or "").strip()

    relevance_parts: List[str] = [source_task, agent_task, summary, answer_preview]
    for field_name in ("structured_result", "step_results_summary", "actionable_facts"):
        payload = key_data.get(field_name)
        if payload in (None, "", [], {}):
            continue
        try:
            relevance_parts.append(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            relevance_parts.append(str(payload))

    return {
        "source_task": source_task,
        "agent_task": agent_task,
        "source_user_task": source_user_task,
        "summary": summary,
        "success": success,
        "key_data": key_data,
        "answer_preview": answer_preview,
        "entry_scope": entry_scope,
        "relevance_text": _normalize_whitespace(" ".join(part for part in relevance_parts if part)),
    }


def rank_history_answer_candidates(
    task: str,
    context_messages: List[Dict[str, Any]],
    *,
    max_candidates: int = MAX_HISTORY_ANSWER_CANDIDATES,
) -> List[Dict[str, Any]]:
    """
    从上下文消息中提炼“可用于直接回答或少执行”的历史答案候选。

    设计目标：
    - 不绑定订单/技能等单一业务，而是统一从历史摘要里找“已知事实 + 可见答案”；
    - 供规划层做两类决策：
      1. 高置信命中时，直接走纯 final_answer；
      2. 否则把候选注入 planning_context，辅助 LLM 减少重复执行。
    """
    parsed_candidates: List[Dict[str, Any]] = []
    for message in context_messages or []:
        candidate = _parse_history_summary_context_message(message)
        if candidate and candidate.get("success"):
            parsed_candidates.append(candidate)

    if not parsed_candidates:
        return []

    ranked_candidates: List[Dict[str, Any]] = []
    total_candidates = len(parsed_candidates)
    for index, candidate in enumerate(parsed_candidates):
        recency_rank = total_candidates - 1 - index
        candidate_text = str(candidate.get("relevance_text", "") or "")
        match_detail = _extract_relevance_match_detail(task, candidate_text)
        score, reasons = _score_context_relevance(
            task=task,
            candidate_text=candidate_text,
            recency_rank=recency_rank,
            has_user_actions=False,
            source_task=str(candidate.get("source_task", "") or ""),
        )
        if candidate.get("answer_preview"):
            score += 3
            reasons.append("历史中包含可直接复用的回答")
        if candidate.get("key_data", {}).get("structured_result") not in (None, "", [], {}):
            score += 2
            reasons.append("历史中包含结构化结果")
        if score <= 0:
            continue

        ranked_candidates.append(
            {
                **candidate,
                "index": index,
                "score": score,
                "reasons": reasons,
                "matched_subject_hints": match_detail["subject_hints"],
                "matched_carrier_hints": match_detail["carrier_hints"],
                "exact_task_match": _normalize_whitespace(task or "")
                == _normalize_whitespace(str(candidate.get("source_task", "") or "")),
                "follow_up_task": _contains_follow_up_task_hint(task),
            }
        )

    ranked_candidates.sort(key=lambda item: (-int(item["score"]), -int(item["index"])))
    return ranked_candidates[:max_candidates]


def select_relevant_conversation_history(
    task: str,
    conversation_history: List[Dict[str, Any]],
    *,
    max_messages: int = MAX_RELEVANT_CONVERSATION_MESSAGES,
    recent_window: int = MAX_RECENT_CONVERSATION_WINDOW,
) -> List[Dict[str, Any]]:
    """
    按任务相关性筛选外部对话历史。

    设计原因：
    - 以前 `conversation_history` 会整段前置注入，随着会话变长很容易把无关旧对话也带进 Prompt；
    - 这里统一保留“显式相关的历史消息”以及“续问场景下最近几轮消息”，兼顾准确性与长度可控；
    - 返回前再做单条消息裁剪，避免某条超长 assistant 回复撑爆上下文。
    """
    if not conversation_history:
        return []

    follow_up_task = _contains_follow_up_task_hint(task)
    explicit_subject_hints = _extract_task_subject_hints(task)
    explicit_carrier_hints = _extract_task_carrier_hints(task)
    selected_indexes: set[int] = set()
    total_messages = len(conversation_history)

    ranked_messages: List[Dict[str, Any]] = []
    for index, message in enumerate(conversation_history):
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        recency_rank = total_messages - 1 - index
        match_detail = _extract_relevance_match_detail(task, str(content or ""))
        score, reasons = _score_context_relevance(
            task=task,
            candidate_text=str(content or ""),
            recency_rank=recency_rank,
            has_user_actions=False,
            source_task="",
        )
        if score <= 0:
            continue
        ranked_messages.append(
            {
                "index": index,
                "score": score,
                "reasons": reasons,
                "matched_subject_hints": match_detail["subject_hints"],
                "matched_carrier_hints": match_detail["carrier_hints"],
            }
        )

    ranked_messages.sort(key=lambda item: (-int(item["score"]), -int(item["index"])))

    subject_matched_messages = [
        item
        for item in ranked_messages
        if item["matched_subject_hints"]
    ]
    carrier_matched_messages = [
        item
        for item in ranked_messages
        if item["matched_carrier_hints"] and not item["matched_subject_hints"]
    ]

    if subject_matched_messages:
        selected_indexes.update(
            _expand_conversation_pair_indexes(
                conversation_history=conversation_history,
                ranked_indexes=[int(item["index"]) for item in subject_matched_messages],
                max_messages=max_messages,
            )
        )
    elif follow_up_task and not explicit_subject_hints:
        start_index = max(0, total_messages - recent_window)
        selected_indexes.update(range(start_index, total_messages))
    elif not explicit_subject_hints and explicit_carrier_hints and carrier_matched_messages:
        selected_indexes.update(
            _expand_conversation_pair_indexes(
                conversation_history=conversation_history,
                ranked_indexes=[int(item["index"]) for item in carrier_matched_messages],
                max_messages=max_messages,
            )
        )

    if not selected_indexes:
        return []

    selected_history: List[Dict[str, Any]] = []
    for index, message in enumerate(conversation_history):
        if index not in selected_indexes:
            continue
        if not isinstance(message, dict):
            message = {"role": "user", "content": str(message)}
        selected_history.append(_trim_context_message(message))

    return selected_history[:max_messages]


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


def _collect_capability_trace_from_step_results(
    step_results: List[Dict[str, Any]],
    capability_trace: Dict[str, List[str]],
    *,
    depth: int = 0,
    max_depth: int = 3,
) -> None:
    """
    递归提炼步骤级能力轨迹。

    设计原因：
    - 顶层 Agent 常只执行 `delegate`，真正的 `skill/tool` 会藏在子 Agent 的嵌套结果中；
    - 若摘要里只记住“委派过”，下一轮就不知道应继续沿用 `general_agent + find-skills`
      还是其他执行链路；
    - 因此这里统一递归遍历 step_results，把委派/技能/工具轨迹都压缩成结构化摘要。
    """
    if depth > max_depth:
        return

    for step in step_results or []:
        if not isinstance(step, dict):
            continue

        action = str(step.get("action", "") or "").strip().lower()
        if action == "delegate":
            _append_unique_text(
                capability_trace["delegated_agents"],
                str(step.get("agent_id", "") or ""),
            )
        elif action == "skill":
            _append_unique_text(
                capability_trace["skills_used"],
                str(step.get("skill_id", "") or ""),
            )
        elif action == "tool":
            _append_unique_text(
                capability_trace["tools_used"],
                str(step.get("tool_name", "") or ""),
            )

        if isinstance(step.get("step_results"), list):
            _collect_capability_trace_from_step_results(
                step.get("step_results") or [],
                capability_trace,
                depth=depth + 1,
                max_depth=max_depth,
            )

        nested_result = step.get("result")
        if isinstance(nested_result, dict):
            if isinstance(nested_result.get("step_results"), list):
                _collect_capability_trace_from_step_results(
                    nested_result.get("step_results") or [],
                    capability_trace,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            nested_inner_result = nested_result.get("result")
            if isinstance(nested_inner_result, dict) and isinstance(
                nested_inner_result.get("step_results"), list
            ):
                _collect_capability_trace_from_step_results(
                    nested_inner_result.get("step_results") or [],
                    capability_trace,
                    depth=depth + 1,
                    max_depth=max_depth,
                )


def _extract_capability_trace(
    run_memory: AgentRunMemory,
    final_result: Dict[str, Any],
) -> Dict[str, List[str]]:
    """
    从运行记忆与最终结果中提炼“能力执行轨迹”。

    输出只保留对跨轮路由真正有价值的三类结构：
    - delegated_agents: 最近成功链路里出现过的子 Agent
    - skills_used:      最近成功链路里使用过的技能
    - tools_used:       最近成功链路里使用过的工具
    """
    capability_trace: Dict[str, List[str]] = {
        "delegated_agents": [],
        "skills_used": [],
        "tools_used": [],
    }

    for msg in run_memory._messages:
        meta = msg.meta or {}
        entry_type = str(meta.get("entry_type", "") or "").strip()
        if entry_type == "delegate":
            _append_unique_text(
                capability_trace["delegated_agents"],
                str(meta.get("child_agent_id", "") or ""),
            )
        elif entry_type == "skill_call":
            _append_unique_text(
                capability_trace["skills_used"],
                str(meta.get("skill_id", "") or ""),
            )
        elif entry_type == "tool_call":
            _append_unique_text(
                capability_trace["tools_used"],
                str(meta.get("tool_name", "") or ""),
            )

    sanitized_final = sanitize_model_payload(final_result or {})
    _collect_capability_trace_from_step_results(
        sanitized_final.get("step_results", []) or [],
        capability_trace,
    )

    return {
        key: value
        for key, value in capability_trace.items()
        if value
    }


def extract_follow_up_capability_context_from_messages(
    context_messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    从上下文消息中提取结构化的“续问能力轨迹候选”。

    设计原因：
    - `LangGraphExecutor` 不应依赖某条自然语言文案来猜测上轮用了什么能力；
    - 因此会话记忆在注入给 LLM 的同时，也把同一份能力轨迹放成可机器读取的 JSON；
    - 执行器可直接复用这份结构化数据，在 LLM 规划前完成框架级兜底委派判断。
    """
    candidates: List[Dict[str, Any]] = []

    for message in context_messages or []:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content", "") or "")
        if FOLLOW_UP_CAPABILITY_CONTEXT_HEADER not in content:
            continue

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith(FOLLOW_UP_CAPABILITY_JSON_PREFIX):
                continue
            payload_text = stripped.split(FOLLOW_UP_CAPABILITY_JSON_PREFIX, 1)[-1].strip()
            try:
                payload = json.loads(payload_text)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                candidates.append(payload)

    return candidates


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
    capability_trace: dict = field(default_factory=dict)
    conversation_turn_id: str = ""
    source_user_task: str = ""
    entry_scope: str = "primary"
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

    def build_relevance_text(self) -> str:
        """
        构建用于相关性匹配的搜索文本。

        设计原因：
        - 会话检索不能只看 `task` 或 `summary`；
        - 真正可用于下一轮判断的线索，经常散落在 actionable_facts、结构化结果、步骤摘要里；
        - 因此这里统一聚合成一段“可检索文本”，供公共打分逻辑复用。
        """
        parts: List[str] = [self.task, self.source_user_task, self.summary]

        if self.tools_used:
            parts.extend(self.tools_used)

        actionable_facts = self.key_data.get("actionable_facts") or []
        for fact in actionable_facts:
            if not isinstance(fact, dict):
                continue
            parts.append(str(fact.get("label", "") or ""))
            parts.append(str(fact.get("value", "") or ""))

        for key in ("result_preview", "structured_result", "step_results_summary"):
            value = self.key_data.get(key)
            if value in (None, "", [], {}):
                continue
            try:
                parts.append(json.dumps(value, ensure_ascii=False, default=str))
            except Exception:
                parts.append(str(value))

        return _normalize_whitespace(" ".join(part for part in parts if part))

    def _build_compact_key_data_json(self) -> str:
        """构建适合注入上下文的紧凑 key_data JSON。"""
        if not self.key_data:
            return ""

        compact_key_data = {
            "result_preview": self.key_data.get("result_preview"),
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
        ]

        if self.source_user_task and self.source_user_task != self.task:
            lines.append(f"主线任务: {self.source_user_task}")

        if self.entry_scope and self.entry_scope != "primary":
            scope_label = "子任务" if self.entry_scope == "subtask" else self.entry_scope
            lines.append(f"记录来源: {scope_label}")

        lines.extend([
            f"结果: {status}",
            f"结论: {self.summary}",
        ])

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

    def build_relevant_context_messages(
        self,
        task: str,
        max_entries: int = MAX_RELEVANT_SESSION_ENTRIES,
    ) -> list[dict]:
        """
        按当前任务相关性筛选会话级任务摘要。

        设计目标：
        - 从“全量前置注入”升级为“按任务相关性检索/裁剪”；
        - 既保留跨轮复用能力，又避免多主题长会话把无关摘要全部塞进 Prompt；
        - 保持框架通用性，不对技能查询等单一场景写死特判。
        """
        if not self._entries:
            return []

        follow_up_task = _contains_follow_up_task_hint(task)
        explicit_subject_hints = _extract_task_subject_hints(task)
        explicit_carrier_hints = _extract_task_carrier_hints(task)
        ranked_entries: List[Dict[str, Any]] = []
        total_entries = len(self._entries)
        for index, entry in enumerate(self._entries):
            recency_rank = total_entries - 1 - index
            match_detail = _extract_relevance_match_detail(task, entry.build_relevance_text())
            score, reasons = _score_context_relevance(
                task=task,
                candidate_text=entry.build_relevance_text(),
                recency_rank=recency_rank,
                has_user_actions=bool(entry.user_actions),
                source_task=entry.source_user_task or entry.task,
            )
            ranked_entries.append(
                {
                    "index": index,
                    "entry": entry,
                    "score": score,
                    "reasons": reasons,
                    "matched_subject_hints": match_detail["subject_hints"],
                    "matched_carrier_hints": match_detail["carrier_hints"],
                    "has_user_actions": bool(entry.user_actions),
                }
            )

        positive_entries = [
            item
            for item in sorted(
                ranked_entries,
                key=lambda item: (-int(item["score"]), -int(item["index"])),
            )
            if int(item["score"]) > 0
        ]

        subject_matched_entries = [
            item for item in positive_entries
            if item["matched_subject_hints"]
        ]
        carrier_matched_entries = [
            item for item in positive_entries
            if item["matched_carrier_hints"] and not item["matched_subject_hints"]
        ]
        constrained_entries = [item for item in positive_entries if item["has_user_actions"]]

        if subject_matched_entries:
            selected_candidates = subject_matched_entries + [
                item for item in constrained_entries if item not in subject_matched_entries
            ]
        elif follow_up_task and not explicit_subject_hints:
            selected_candidates = positive_entries
        elif not explicit_subject_hints and explicit_carrier_hints:
            selected_candidates = carrier_matched_entries + [
                item for item in constrained_entries if item not in carrier_matched_entries
            ]
        else:
            selected_candidates = constrained_entries

        selected = selected_candidates[:max_entries]

        if not selected:
            logger.info(
                f"{Fore.CYAN}[会话记忆] 会话 {self.conversation_id} 未命中与任务相关的历史摘要，"
                f"本轮不注入跨任务摘要 | task={task[:80]!r}{Style.RESET_ALL}"
            )
            return []

        selected.sort(key=lambda item: int(item["index"]))
        logger.info(
            f"{Fore.CYAN}[会话记忆] 会话 {self.conversation_id} 按任务相关性筛选历史摘要: "
            f"total={total_entries} -> selected={len(selected)} | task={task[:80]!r}{Style.RESET_ALL}"
        )
        for item in selected:
            entry = item["entry"]
            logger.info(
                f"{Fore.CYAN}[会话记忆] 选中摘要[{item['index']}] "
                f"score={item['score']} | task={entry.task[:60]!r} | reasons={item['reasons']}{Style.RESET_ALL}"
            )

        return [item["entry"].to_context_message() for item in selected]

    def _build_follow_up_capability_context_message(
        self,
        *,
        entry: TaskSummaryEntry,
        score: int,
        reasons: List[str],
    ) -> Dict[str, str]:
        """
        将“最近成功能力轨迹”压缩成一条独立上下文消息。

        设计原因：
        - 主题摘要与能力轨迹承担的职责不同，不能混在一条历史摘要里统一靠相关性匹配；
        - 对显式续问，只需要告诉框架和 LLM“上一轮成功链路是什么”，而不是把旧主题结果整段带入。
        """
        capability_trace = entry.capability_trace or {}
        payload = {
            "source_task": entry.task,
            "source_summary": entry.summary,
            "source_agent_id": entry.agent_id,
            "source_agent_name": entry.agent_name,
            "delegated_agents": capability_trace.get("delegated_agents", []) or [],
            "skills_used": capability_trace.get("skills_used", []) or [],
            "tools_used": capability_trace.get("tools_used", []) or [],
            "score": score,
            "reasons": reasons,
        }

        lines = [
            FOLLOW_UP_CAPABILITY_CONTEXT_HEADER,
            "这是显式续问场景下提炼出的最近成功能力轨迹，仅用于沿用执行路径，不代表旧主题结果仍然适用。",
            f"最近成功任务: {entry.task}",
            f"执行结论: {entry.summary}",
        ]
        if payload["delegated_agents"]:
            lines.append(f"历史委派链路: {', '.join(payload['delegated_agents'])}")
        if payload["skills_used"]:
            lines.append(f"历史技能链路: {', '.join(payload['skills_used'])}")
        if payload["tools_used"]:
            lines.append(f"历史工具链路: {', '.join(payload['tools_used'])}")
        lines.append(
            f"{FOLLOW_UP_CAPABILITY_JSON_PREFIX} "
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        return {"role": "user", "content": "\n".join(lines)}

    def build_follow_up_capability_context_messages(
        self,
        task: str,
        max_entries: int = MAX_FOLLOW_UP_CAPABILITY_MESSAGES,
    ) -> List[Dict[str, str]]:
        """
        为显式续问任务提炼最近成功的“能力执行轨迹”。

        设计目标：
        - 与主题摘要检索解耦，避免“新闻 -> mcp”这类换主题续问时既丢了执行链路，
          又错误混入旧主题内容；
        - 优先保留最近成功、且与当前能力域更接近的轨迹，供上层做通用委派/路由决策。
        """
        if not self._entries or not _contains_follow_up_task_hint(task):
            return []

        explicit_carrier_hints = _extract_task_carrier_hints(task)
        domain_hints = _extract_task_domain_hints(task)
        ranked_entries: List[Dict[str, Any]] = []
        total_entries = len(self._entries)

        for index, entry in enumerate(self._entries):
            if not entry.success:
                continue

            capability_trace = entry.capability_trace or {}
            capability_tokens: List[str] = []
            for token in capability_trace.get("delegated_agents", []) or []:
                _append_unique_text(capability_tokens, token)
            for token in capability_trace.get("skills_used", []) or []:
                _append_unique_text(capability_tokens, token)
            for token in capability_trace.get("tools_used", []) or []:
                _append_unique_text(capability_tokens, token)
            for token in entry.tools_used or []:
                _append_unique_text(capability_tokens, token)

            if not capability_tokens:
                continue

            candidate_text = _normalize_whitespace(
                " ".join(capability_tokens + [entry.task, entry.summary])
            ).lower()
            if not candidate_text:
                continue

            matched_carriers = [
                hint for hint in explicit_carrier_hints
                if hint in candidate_text
            ]
            matched_domains = [
                hint for hint in domain_hints
                if hint in candidate_text
            ]

            # 若当前续问已经显式暴露能力域/调用载体，则历史候选至少要命中其中之一；
            # 否则宁可不注入，也不要把“最近一次无关成功任务”误当成应该沿用的能力链。
            if (explicit_carrier_hints or domain_hints) and not (matched_carriers or matched_domains):
                continue

            recency_rank = total_entries - 1 - index
            score = max(0, 8 - recency_rank * 2)
            reasons = ["显式续问沿用最近成功能力链"]
            if matched_carriers:
                score += 6
                reasons.append(f"命中调用载体:{','.join(matched_carriers)}")
            if matched_domains:
                score += 4
                reasons.append(f"命中能力域:{','.join(matched_domains)}")

            ranked_entries.append(
                {
                    "index": index,
                    "entry": entry,
                    "score": score,
                    "reasons": reasons,
                }
            )

        if not ranked_entries:
            return []

        ranked_entries.sort(key=lambda item: (-int(item["score"]), -int(item["index"])))
        selected = ranked_entries[:max_entries]

        logger.info(
            f"{Fore.CYAN}[会话记忆] 会话 {self.conversation_id} 已为续问提炼能力轨迹: "
            f"selected={len(selected)} | task={task[:80]!r}{Style.RESET_ALL}"
        )
        for item in selected:
            entry = item["entry"]
            logger.info(
                f"{Fore.CYAN}[会话记忆] 选中能力轨迹[{item['index']}] "
                f"score={item['score']} | task={entry.task[:60]!r} | reasons={item['reasons']}{Style.RESET_ALL}"
            )

        return [
            self._build_follow_up_capability_context_message(
                entry=item["entry"],
                score=int(item["score"]),
                reasons=item["reasons"],
            )
            for item in selected
        ]

    def _build_conversation_turn_payloads(self) -> List[Dict[str, Any]]:
        """
        将零散的主/子 Agent 摘要聚合成“按轮次排列的会话主线”。

        设计原因：
        - 会话中同时存在主 Agent 摘要和子 Agent 摘要，不能直接按 entry 平铺给 LLM；
        - 对“第一轮问了什么 / 上一轮做了什么”这类问题，真正需要的是按用户轮次整理后的主线；
        - 因此这里按 `conversation_turn_id` 聚合，同一轮内保留原始用户问题、关键结论和能力轨迹。
        """
        grouped_entries: List[Dict[str, Any]] = []
        turn_index_by_id: Dict[str, int] = {}

        for index, entry in enumerate(self._entries):
            turn_id = (
                entry.conversation_turn_id
                or entry.source_user_task
                or f"{entry.task_id or entry.task or 'turn'}::{index}"
            )
            if turn_id not in turn_index_by_id:
                turn_index_by_id[turn_id] = len(grouped_entries)
                grouped_entries.append({"turn_id": turn_id, "entries": []})
            grouped_entries[turn_index_by_id[turn_id]]["entries"].append(entry)

        turn_payloads: List[Dict[str, Any]] = []
        for group in grouped_entries:
            entries: List[TaskSummaryEntry] = group["entries"]
            if not entries:
                continue

            primary_entries = [entry for entry in entries if entry.entry_scope == "primary"]
            canonical_entry = primary_entries[0] if primary_entries else entries[0]

            def _entry_score(item: TaskSummaryEntry) -> float:
                score = 0.0
                if item.success:
                    score += 6.0
                if item.entry_scope == "primary":
                    score += 3.0
                if item.key_data:
                    score += float(len(item.key_data))
                if item.capability_trace:
                    score += 2.0
                score += min(len(item.summary or ""), 180) / 180.0
                return score

            summary_entry = max(entries, key=_entry_score)

            capability_trace: Dict[str, List[str]] = {
                "delegated_agents": [],
                "skills_used": [],
                "tools_used": [],
            }
            actual_tasks: List[str] = []
            agent_names: List[str] = []
            entry_scopes: List[str] = []
            for entry in entries:
                _append_unique_text(actual_tasks, entry.task)
                _append_unique_text(agent_names, entry.agent_name)
                _append_unique_text(entry_scopes, entry.entry_scope)
                for key in ("delegated_agents", "skills_used", "tools_used"):
                    for value in (entry.capability_trace or {}).get(key, []) or []:
                        _append_unique_text(capability_trace[key], value)
                for tool_name in entry.tools_used or []:
                    _append_unique_text(capability_trace["tools_used"], tool_name)

            source_user_task = (
                canonical_entry.source_user_task
                or canonical_entry.task
                or summary_entry.source_user_task
                or summary_entry.task
            )
            payload: Dict[str, Any] = {
                "turn_id": group["turn_id"],
                "source_user_task": source_user_task,
                "summary": summary_entry.summary,
                "agent_names": agent_names,
                "actual_tasks": actual_tasks,
                "entry_scopes": entry_scopes,
            }

            compact_trace = {
                key: value
                for key, value in capability_trace.items()
                if value
            }
            if compact_trace:
                payload["capability_trace"] = compact_trace

            turn_payloads.append(payload)

        return turn_payloads

    def build_conversation_recall_context_messages(
        self,
        task: str,
        max_turns: int = MAX_CONVERSATION_RECALL_TURNS,
    ) -> List[Dict[str, str]]:
        """
        为“回顾之前对话”的任务构造统一的会话主线时间线。

        设计目标：
        - 不是只回答某个固定问法，而是给 LLM 一份按轮次整理的会话主线；
        - 既保留原始用户问题，也保留该轮最终结论与关键能力轨迹；
        - 主 Agent / 子 Agent 共享同一上下文后，都能基于主线继续规划或直接回答。
        """
        if not self._entries or not _is_conversation_recall_request(task):
            return []

        turn_payloads = self._build_conversation_turn_payloads()
        if not turn_payloads:
            return []

        selected_turns = turn_payloads
        omitted_count = 0
        if len(turn_payloads) > max_turns:
            head_count = max(1, max_turns // 2)
            tail_count = max(1, max_turns - head_count)
            selected_turns = turn_payloads[:head_count] + turn_payloads[-tail_count:]
            omitted_count = len(turn_payloads) - len(selected_turns)

        lines = [
            CONVERSATION_RECALL_CONTEXT_HEADER,
            "以下为当前会话按时间顺序整理的主要对话主线，可用于回答“之前问过什么、上一轮做了什么、当前进行到哪一步”等历史问题，也可作为后续规划参考。",
        ]

        for index, turn in enumerate(selected_turns, start=1):
            lines.append(f"{index}. 用户问题: {turn.get('source_user_task', '')}")

            summary = str(turn.get("summary", "") or "").strip()
            if summary:
                lines.append(f"   当前结论: {summary}")

            actual_tasks = [
                item
                for item in (turn.get("actual_tasks") or [])
                if item and item != turn.get("source_user_task")
            ]
            if actual_tasks:
                lines.append(f"   相关子任务: {'；'.join(actual_tasks[:2])}")

            capability_trace = turn.get("capability_trace") or {}
            capability_parts: List[str] = []
            if capability_trace.get("delegated_agents"):
                capability_parts.append(
                    f"委派={','.join(capability_trace['delegated_agents'])}"
                )
            if capability_trace.get("skills_used"):
                capability_parts.append(
                    f"技能={','.join(capability_trace['skills_used'])}"
                )
            if capability_trace.get("tools_used"):
                capability_parts.append(
                    f"工具={','.join(capability_trace['tools_used'])}"
                )
            if capability_parts:
                lines.append(f"   能力轨迹: {' | '.join(capability_parts)}")

        if omitted_count > 0:
            lines.append(f"...（中间还有 {omitted_count} 轮对话主线已省略）")

        payload_text = json.dumps(selected_turns, ensure_ascii=False, default=str)
        if len(payload_text) > MAX_CONVERSATION_RECALL_JSON_LENGTH:
            payload_text = build_balanced_text_preview(
                payload_text,
                limit=MAX_CONVERSATION_RECALL_JSON_LENGTH,
                note="以下为会话主线数据的首尾节选，中间内容仅因控制提示词长度而省略，不代表真实轮次缺失。",
            )
        lines.append(f"{CONVERSATION_RECALL_JSON_PREFIX} {payload_text}")

        logger.info(
            f"{Fore.CYAN}[会话记忆] 会话 {self.conversation_id} 已构建主线回顾上下文: "
            f"total_turns={len(turn_payloads)} -> selected={len(selected_turns)} | task={task[:80]!r}"
            f"{Style.RESET_ALL}"
        )

        return [{"role": "user", "content": "\n".join(lines)}]

    def get_summary_list(self) -> list[dict]:
        """返回供调试或展示的条目列表"""
        return [asdict(e) for e in self._entries]


def extract_summary_from_run_memory(
    run_memory: AgentRunMemory,
    final_result: Dict[str, Any],
    *,
    conversation_turn_id: str = "",
    source_user_task: str = "",
    entry_scope: str = "primary",
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
    capability_trace = _extract_capability_trace(
        run_memory=run_memory,
        final_result=final_result or {},
    )

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
        capability_trace=capability_trace,
        conversation_turn_id=conversation_turn_id,
        source_user_task=source_user_task or run_memory.task,
        entry_scope=entry_scope or "primary",
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
