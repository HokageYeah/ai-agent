#!/usr/bin/env python3
"""
API 日志分析脚本
================

用途：
1. 对日志文件做单次结构化统计
2. 输出 text（三段式）或 json 结果
3. 减少 LLM 多轮 shell_exec 的重复调用
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Iterable


@dataclass
class DateRange:
    mode: str
    start: date | None = None
    end: date | None = None
    exact: date | None = None

    def match(self, line: str) -> bool:
        if self.mode == "all":
            return True
        d = _extract_line_date(line)
        if d is None:
            return False
        if self.mode == "today":
            return d == date.today()
        if self.mode == "exact":
            return d == self.exact
        if self.mode == "range":
            return self.start <= d <= self.end
        return True


def _extract_line_date(line: str) -> date | None:
    # 常见格式：2026-03-16 09:32:33 | INFO ...
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\b", line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_date_range(raw: str) -> DateRange:
    text = (raw or "").strip().lower()
    if not text or text == "all":
        return DateRange(mode="all")
    if text == "today":
        return DateRange(mode="today")

    # 形式：YYYY-MM-DD
    exact_match = re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)
    if exact_match:
        exact = datetime.strptime(text, "%Y-%m-%d").date()
        return DateRange(mode="exact", exact=exact)

    # 形式：YYYY-MM-DD to YYYY-MM-DD
    range_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", text)
    if range_match:
        start = datetime.strptime(range_match.group(1), "%Y-%m-%d").date()
        end = datetime.strptime(range_match.group(2), "%Y-%m-%d").date()
        if start > end:
            start, end = end, start
        return DateRange(mode="range", start=start, end=end)

    # 兜底：无法解析时按 all 处理
    return DateRange(mode="all")


def _safe_percent(num: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return round(num * 100.0 / denom, 2)


def _collect(lines: Iterable[str]) -> dict[str, object]:
    total = 0
    info_count = 0
    debug_count = 0
    warn_count = 0
    error_count = 0

    # 统计业务相关关键事件
    stream_calls = 0
    infer_requests = 0
    infer_success = 0
    tool_success = 0
    skill_lazy_load = 0

    latencies_ms: list[float] = []
    request_ids: set[str] = set()
    infer_req_started_ids: set[str] = set()
    infer_req_success_ids: set[str] = set()

    req_pattern = re.compile(r"\[(req-\d+)\]")
    latency_pattern = re.compile(r"耗时:\s*([0-9]+(?:\.[0-9]+)?)ms")

    for line in lines:
        total += 1
        if "| INFO" in line:
            info_count += 1
        elif "| DEBUG" in line:
            debug_count += 1
        elif "| WARNING" in line:
            warn_count += 1
        elif "| ERROR" in line:
            error_count += 1

        if "【Agent流式接口】接收到 Agent 流式执行请求" in line:
            stream_calls += 1
        if "开始推理请求:" in line:
            infer_requests += 1
        if "推理请求成功完成" in line:
            infer_success += 1
        if "工具调用成功:" in line:
            tool_success += 1
        if "技能懒加载成功:" in line:
            skill_lazy_load += 1

        line_req_ids: list[str] = []
        for req_m in req_pattern.finditer(line):
            req_id = req_m.group(1)
            request_ids.add(req_id)
            line_req_ids.append(req_id)

        if line_req_ids and "开始推理请求:" in line:
            infer_req_started_ids.update(line_req_ids)
        if line_req_ids and "推理请求成功完成" in line:
            infer_req_success_ids.update(line_req_ids)

        lat_m = latency_pattern.search(line)
        if lat_m:
            try:
                latencies_ms.append(float(lat_m.group(1)))
            except ValueError:
                pass

    # 优先用 request_id 口径统计推理成功率，避免文本匹配重复导致 >100%。
    if infer_req_started_ids:
        infer_requests = len(infer_req_started_ids)
        infer_success = len(infer_req_success_ids & infer_req_started_ids)

    success_rate = _safe_percent(total - error_count, total)
    infer_success_rate = _safe_percent(infer_success, infer_requests)
    avg_latency = round(mean(latencies_ms), 2) if latencies_ms else 0.0
    p95_latency = round(_percentile(latencies_ms, 95), 2) if latencies_ms else 0.0

    return {
        "total_lines": total,
        "level_counts": {
            "INFO": info_count,
            "DEBUG": debug_count,
            "WARNING": warn_count,
            "ERROR": error_count,
        },
        "success_rate_percent": success_rate,
        "events": {
            "agent_stream_calls": stream_calls,
            "inference_requests": infer_requests,
            "inference_success": infer_success,
            "inference_success_rate_percent": infer_success_rate,
            "tool_call_success": tool_success,
            "skill_lazy_load_count": skill_lazy_load,
            "unique_request_ids": len(request_ids),
        },
        "latency_ms": {
            "avg": avg_latency,
            "p95": p95_latency,
            "samples": len(latencies_ms),
        },
    }


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    # 简化分位数实现，避免外部依赖
    idx = max(0, min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _to_text(payload: dict[str, object], log_path: Path, date_range: str) -> str:
    level_counts = payload["level_counts"]
    events = payload["events"]
    latency = payload["latency_ms"]
    total = payload["total_lines"]
    success_rate = payload["success_rate_percent"]

    conclusion = (
        "## 结论\n"
        f"- 已完成日志分析，目标文件：`{log_path}`\n"
        f"- 日志条目共 {total} 条，整体成功率约 {success_rate}%\n"
        f"- 统计范围：`{date_range or 'all'}`"
    )

    evidence = (
        "## 关键证据\n"
        f"- 日志级别分布：INFO={level_counts['INFO']}，DEBUG={level_counts['DEBUG']}，"
        f"WARNING={level_counts['WARNING']}，ERROR={level_counts['ERROR']}\n"
        f"- Agent 流式调用次数：{events['agent_stream_calls']}\n"
        f"- 推理请求：{events['inference_requests']}，成功：{events['inference_success']} "
        f"(成功率 {events['inference_success_rate_percent']}%)\n"
        f"- 工具调用成功次数：{events['tool_call_success']}\n"
        f"- 技能懒加载触发次数：{events['skill_lazy_load_count']}\n"
        f"- 推理耗时：平均 {latency['avg']}ms，P95 {latency['p95']}ms，样本 {latency['samples']} 条"
    )

    suggestions: list[str] = []
    if level_counts["ERROR"] > 0:
        suggestions.append("存在 ERROR 日志，建议先按时间倒序定位最近错误堆栈。")
    else:
        suggestions.append("当前无 ERROR 日志，可继续观察 WARNING 是否持续出现。")
    if latency["p95"] > 8000:
        suggestions.append("P95 耗时偏高，建议重点排查长尾请求与模型调用重试。")
    else:
        suggestions.append("耗时整体可接受，建议持续监控 P95 波动。")
    suggestions.append("建议将该分析接入定时任务，按日自动输出并归档。")

    next_step = "## 下一步建议\n" + "\n".join(f"- {x}" for x in suggestions)
    return f"{conclusion}\n\n{evidence}\n\n{next_step}\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="分析 API 日志并输出日报摘要")
    parser.add_argument("--log-path", required=True, help="日志文件路径")
    parser.add_argument("--date-range", default="today", help="日期范围：today/all/单日/区间")
    parser.add_argument("--output-format", default="text", choices=["text", "json"], help="输出格式")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_path = Path(args.log_path).expanduser().resolve()
    if not log_path.is_file():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_stage": "file_check",
                    "error": f"日志文件不存在: {log_path}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    date_range = _parse_date_range(args.date_range)
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    filtered = [line for line in lines if date_range.match(line)]

    payload = _collect(filtered)
    payload["ok"] = True
    payload["log_path"] = str(log_path)
    payload["date_range"] = args.date_range

    if args.output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_to_text(payload, log_path, args.date_range))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
