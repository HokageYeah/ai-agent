"""
LLM 输出解析辅助工具
====================

本模块提供一组通用的 LLM 输出提取函数，用于从混合格式文本中尽量恢复结构化载荷。

设计目标：
1. 兼容 `<think>...</think>`、Markdown 代码块、裸 JSON 等常见混合输出；
2. 兼容 JSON 对象与 JSON 数组两种顶层结构；
3. 尽量避免把字符串内部的括号误判为结构边界；
4. 供 Planning / Reflection / 错误分析等多个引擎复用，减少重复实现。
"""

from __future__ import annotations

import json
import re
from typing import Optional, Any


def strip_think_blocks(text: str) -> str:
    """
    去掉 `<think>...</think>` 推理块，保留对外可消费的正文。

    为什么做这一步：
    - 部分模型会把推理过程直接输出到 content 中；
    - 这些内容既不属于最终 JSON，也容易干扰后续正则/括号扫描。
    """
    return re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=re.IGNORECASE).strip()


def sanitize_model_payload(payload: Any) -> Any:
    """
    递归清洗模型/Agent 载荷中的推理噪声。

    设计目标：
    1. 技能、子 Agent、反思结果里若混入 `<think>`，统一在公共层去除；
    2. 保持原有结构（dict/list）不变，避免只对某个 action/skill 做特判；
    3. 供执行阶段、SSE 返回、记忆写入等多个边界复用。
    """
    if isinstance(payload, str):
        return strip_think_blocks(payload)
    if isinstance(payload, list):
        return [sanitize_model_payload(item) for item in payload]
    if isinstance(payload, dict):
        return {key: sanitize_model_payload(value) for key, value in payload.items()}
    return payload


def extract_user_visible_result(payload: Any) -> str:
    """
    从复杂执行结果中提取最适合直接展示给用户的正文字符串。

    典型输入：
    - 技能原始文本（可能带 `<think>`）
    - 子 Agent / ExecutionResult 风格包装字典
    - python_executor 风格结果（`result` / `output`）
    """
    sanitized = sanitize_model_payload(payload)
    unwrapped = _unwrap_execution_like_payload(sanitized)

    if unwrapped is None:
        return ""
    if isinstance(unwrapped, str):
        return unwrapped.strip()
    if isinstance(unwrapped, dict):
        for key in ("content", "text", "message", "summary", "output", "result"):
            value = unwrapped.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    try:
        return json.dumps(unwrapped, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(unwrapped).strip()


def compact_user_visible_text(text: str, limit: int = 1200) -> str:
    """
    将用户可见文本压缩为适合日志/SSE 事件展示的预览。

    设计目标：
    1. 避免中间轨迹事件塞入超长 HTML / Markdown，污染前端展示；
    2. 保留足够的可读上下文，便于排障；
    3. 作为公共边界能力，供 SSE、日志摘要、嵌套 step_results 复用。
    """
    cleaned = strip_think_blocks(text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n...（内容已截断）"


def build_balanced_text_preview(
    text: str,
    *,
    limit: int = 1600,
    head_chars: Optional[int] = None,
    tail_chars: Optional[int] = None,
    note: str = "以下为首尾节选，中间内容仅因控制上下文长度而省略，不代表原始内容在传输或执行过程中被截断。",
) -> str:
    """
    构建“保留首尾信息”的长文本预览。

    设计目标：
    1. 传统的“只保留前 N 字”会让列表/表格类答案只剩前几项，容易让反思/重规划误判为“结果被截断”；
    2. 这里统一保留开头和结尾，并显式说明“中间省略只是上下文压缩”，避免模型把摘要误认为传输异常；
    3. 作为公共能力，供 Reflection / Planning 等需要“控长但又不能丢尾部关键信息”的场景复用。
    """
    cleaned = strip_think_blocks(text or "").strip()
    if len(cleaned) <= limit:
        return cleaned

    normalized_note = str(note or "").strip()
    # 为了保证前后文都能保留，默认按 6:4 分配头尾窗口。
    if head_chars is None or tail_chars is None:
        budget = max(240, limit - 120)
        computed_head = max(140, int(budget * 0.6))
        computed_tail = max(100, budget - computed_head)
        head_chars = computed_head if head_chars is None else head_chars
        tail_chars = computed_tail if tail_chars is None else tail_chars

    head_chars = max(60, int(head_chars))
    tail_chars = max(60, int(tail_chars))
    if head_chars + tail_chars >= len(cleaned):
        return cleaned

    omitted = len(cleaned) - head_chars - tail_chars
    head_part = cleaned[:head_chars].rstrip()
    tail_part = cleaned[-tail_chars:].lstrip()

    return (
        f"{normalized_note}\n"
        f"【原始长度】{len(cleaned)} 字\n"
        f"【开头片段】\n{head_part}\n"
        f"...（中间省略 {omitted} 字）\n"
        f"【结尾片段】\n{tail_part}"
    )


def extract_user_visible_preview(payload: Any, limit: int = 1200) -> Any:
    """
    从复杂执行结果中提取“适合中间事件展示”的预览载荷。

    与 extract_user_visible_result 的区别：
    - extract_user_visible_result 面向最终答案，优先返回完整正文；
    - 本函数面向中间轨迹/SSE 事件，优先返回精简预览，避免超长载荷污染界面。
    """
    sanitized = sanitize_model_payload(payload)
    unwrapped = _unwrap_execution_like_payload(sanitized)

    if unwrapped is None:
        return ""
    if isinstance(unwrapped, str):
        return compact_user_visible_text(unwrapped, limit=limit)
    if isinstance(unwrapped, list):
        previews = [
            extract_user_visible_preview(item, limit=max(200, limit // 2))
            for item in unwrapped[:3]
        ]
        if len(unwrapped) > 3:
            previews.append(f"...（其余 {len(unwrapped) - 3} 项已省略）")
        return previews
    if isinstance(unwrapped, dict):
        preview: dict[str, Any] = {}
        for key in (
            "success",
            "status_code",
            "status_text",
            "content_type",
            "response_time_ms",
            "url",
            "truncated",
            "download_path",
            "result_type",
        ):
            value = unwrapped.get(key)
            if value not in (None, ""):
                preview[key] = value

        for key in ("content", "text", "message", "summary", "output", "result"):
            value = unwrapped.get(key)
            if isinstance(value, str) and value.strip():
                preview_key = "content_preview" if key == "content" else f"{key}_preview"
                preview[preview_key] = compact_user_visible_text(value, limit=limit)
                break

        if preview:
            return preview

    try:
        rendered = json.dumps(unwrapped, ensure_ascii=False, indent=2, default=str)
    except Exception:
        rendered = str(unwrapped)
    return compact_user_visible_text(rendered, limit=limit)


def extract_first_fenced_block(text: str) -> Optional[str]:
    """提取第一个 Markdown 代码块内容。"""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text or "", flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def extract_outer_fenced_block(text: str) -> Optional[str]:
    """
    仅在“整个输出都被单个代码块包裹”时提取其内容。

    设计原因：
    - 避免把 JSON 字符串字段里的示例代码块（如 final_answer.content 中的 ```bash）
      误识别为真正的结构化载荷；
    - 同时保留对 ```json ... ``` / ``` ... ``` 顶层包裹输出的兼容能力。
    """
    match = re.match(
        r"^\s*```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```\s*$",
        text or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip()


def extract_first_balanced_json_object(text: str) -> Optional[str]:
    """提取首个平衡的大括号 JSON 对象。"""
    return _extract_first_balanced_segment(text=text, open_char="{", close_char="}")


def extract_first_balanced_json_array(text: str) -> Optional[str]:
    """提取首个平衡的中括号 JSON 数组。"""
    return _extract_first_balanced_segment(text=text, open_char="[", close_char="]")


def extract_json_payload(llm_output: str) -> str:
    """
    从 LLM 输出中尽量提取 JSON 载荷。

    提取顺序：
    1. 顶层包裹的代码块内容
    2. 平衡 JSON 对象
    3. 平衡 JSON 数组
    4. 任意位置的首个代码块（最后兜底）
    5. 原始文本（调用方自行兜底）

    关键约束：
    - 不能优先抓取“任意位置的代码块”，否则会把 JSON 字符串字段里的 markdown 示例
      当成真正载荷，导致后续 `json.loads()` 从普通 shell/python 文本开始解析而失败。
    """
    raw_text = (llm_output or "").strip()
    if not raw_text:
        return raw_text

    stripped_text = strip_think_blocks(raw_text)
    candidates = []
    for candidate in (stripped_text, raw_text):
        normalized = (candidate or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    for text in candidates:
        outer_fenced = extract_outer_fenced_block(text)
        if outer_fenced:
            return outer_fenced

    for text in candidates:
        json_object = extract_first_balanced_json_object(text)
        if json_object:
            return json_object

        json_array = extract_first_balanced_json_array(text)
        if json_array:
            return json_array

    for text in candidates:
        fenced = extract_first_fenced_block(text)
        if fenced:
            return fenced

    return stripped_text or raw_text


def _unwrap_execution_like_payload(payload: Any) -> Any:
    """
    递归剥离 ExecutionResult / 子 Agent / python_executor 常见包装层。
    """
    current = payload

    for _ in range(8):
        if not isinstance(current, dict):
            break

        nested_result = current.get("result")
        looks_like_execution_wrapper = (
            "result" in current and any(
                key in current
                for key in ("step_results", "reflection", "error", "user_rejected_tools", "agent_id", "agent_name")
            )
        )
        if looks_like_execution_wrapper and nested_result not in (None, ""):
            current = nested_result
            continue

        if nested_result not in (None, "") and set(current.keys()).issubset({"success", "result", "output", "error", "result_type"}):
            current = nested_result
            continue

        nested_output = current.get("output")
        if nested_result in (None, "") and nested_output not in (None, ""):
            current = nested_output
            continue

        break

    return current


def _extract_first_balanced_segment(
    *,
    text: str,
    open_char: str,
    close_char: str,
) -> Optional[str]:
    """
    提取首个“括号平衡”的结构片段。

    通过字符扫描处理字符串与转义，避免误把 JSON 字符串内部的括号当成结构边界。
    """
    raw_text = text or ""
    start_idx = raw_text.find(open_char)
    if start_idx < 0:
        return None

    depth = 0
    in_string = False
    escape = False

    for idx in range(start_idx, len(raw_text)):
        ch = raw_text[idx]

        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
            elif ch == "\"":
                in_string = False
            continue

        if ch == "\"":
            in_string = True
            continue
        if ch == open_char:
            depth += 1
            continue
        if ch == close_char:
            depth -= 1
            if depth == 0:
                return raw_text[start_idx : idx + 1].strip()

    return None
