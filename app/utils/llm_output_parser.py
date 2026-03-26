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

import re
from typing import Optional


def strip_think_blocks(text: str) -> str:
    """
    去掉 `<think>...</think>` 推理块，保留对外可消费的正文。

    为什么做这一步：
    - 部分模型会把推理过程直接输出到 content 中；
    - 这些内容既不属于最终 JSON，也容易干扰后续正则/括号扫描。
    """
    return re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=re.IGNORECASE).strip()


def extract_first_fenced_block(text: str) -> Optional[str]:
    """提取第一个 Markdown 代码块内容。"""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text or "", flags=re.IGNORECASE)
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
    1. 代码块内容
    2. 平衡 JSON 对象
    3. 平衡 JSON 数组
    4. 原始文本（调用方自行兜底）
    """
    text = strip_think_blocks(llm_output or "")
    if not text:
        return text

    fenced = extract_first_fenced_block(text)
    if fenced:
        return fenced

    json_object = extract_first_balanced_json_object(text)
    if json_object:
        return json_object

    json_array = extract_first_balanced_json_array(text)
    if json_array:
        return json_array

    return text


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
