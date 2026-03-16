#!/usr/bin/env python3
"""
dynamic_probe 探针脚本
======================

用途：
1. 读取 resources 下的模板文件
2. 注入主题/时间等变量
3. 生成本地测试报告文件

该脚本用于验证技能系统在“懒加载后”是否能正确调用技能脚本。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


def _safe_format(template: str, payload: dict[str, str]) -> str:
    """安全格式化：模板缺失变量时保留原占位符，避免脚本直接异常退出。"""

    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(_SafeDict(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 dynamic_probe 测试报告")
    parser.add_argument("--topic", required=True, help="探针测试主题")
    parser.add_argument(
        "--template",
        default="report_template.md",
        help="模板文件名（位于 resources/ 下）",
    )
    parser.add_argument(
        "--output",
        default="dynamic_probe_report.md",
        help="输出文件路径（可相对当前工作目录）",
    )
    parser.add_argument("--notes", default="", help="附加说明")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # scripts/ 的上一级目录就是技能目录 dynamic_probe
    skill_root = Path(__file__).resolve().parents[1]
    template_path = skill_root / "resources" / args.template
    output_path = Path(args.output).expanduser().resolve()
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not template_path.exists():
        print(
            f"[dynamic_probe] 模板不存在: {template_path}",
            file=sys.stderr,
        )
        return 2

    template_text = template_path.read_text(encoding="utf-8")
    rendered = _safe_format(
        template_text,
        {
            "topic": args.topic,
            "timestamp": timestamp,
            "template_path": str(template_path),
            "script_path": str(Path(__file__).resolve()),
            "notes": args.notes,
        },
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    summary = {
        "ok": True,
        "topic": args.topic,
        "template": str(template_path),
        "output": str(output_path),
        "timestamp": timestamp,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
