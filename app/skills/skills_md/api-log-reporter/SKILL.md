---
name: api-log-reporter
description: 读取 API 运行日志并快速生成结构化日报（结论/关键证据/下一步建议）。
required_tools: ["shell_exec", "file_read"]
optional_tools: []
tags: ["api", "log", "report", "observability"]
memory_include_short_term: true
---

# 何时使用 (When to use)
- 需要自动分析 API 访问日志并生成日报的场景
- 需要统计 API 调用频率、成功率、错误率等关键指标
- 需要定期生成 API 服务性能报告
- 需要监控 API 使用情况和异常行为

# 输入参数 (Inputs)
- log_path: API 日志文件路径（必填）
- date_range: 统计日期范围，如 `today`、`2026-03-16` 或 `2026-03-01 to 2026-03-16`（可选）
- output_format: 输出格式，支持 "text" 或 "json"（可选，默认 "text"）

# 执行指令 (Instructions)
你是“api-log-reporter”技能执行助手，专门用于读取 API 日志并生成日报。

请严格遵循以下固定流程（优先确定性脚本，避免多轮工具循环）：

1. 参数预处理
- 若未提供 `date_range`，默认使用 `today`
- 若未提供 `output_format`，默认使用 `text`

2. 文件存在性检查（最多 1 次工具调用）
```bash
test -f "{log_path}" && echo "__OK__" || echo "__MISSING__"
```
- 若文件不存在，直接返回“失败原因 + 可执行修复建议”，不要继续分析

3. 使用脚本一次性分析（必须优先，最多 1 次工具调用）
```bash
python3 app/skills/skills_md/api-log-reporter/scripts/analyze_api_log.py \
  --log-path "{log_path}" \
  --date-range "{date_range}" \
  --output-format "{output_format}"
```

4. 输出规则
- `output_format=text`：按“三段式”输出  
  - 结论  
  - 关键证据  
  - 下一步建议
- `output_format=json`：直接返回脚本产出的 JSON 结果

5. 强约束（必须遵守）
- 总工具调用次数上限：4 次（推荐 2 次）
- 禁止为统计同一指标重复调用多条 `grep/awk` 命令
- 禁止先 `list_dir` 再 `file_read` 的无效探索，已知路径时必须直接检查并执行脚本
- 禁止调用 `file_edit` 修补中间结果
- 若脚本成功返回，禁止再进行二次无关统计
- 若分析失败，必须给出失败阶段（文件检查/脚本执行）与修复建议

技能目标说明：
读取 API 日志文件，分析调用数据，生成包含关键指标的日报报告，并尽量降低工具调用成本。

# 脚本 (Scripts)
- scripts/analyze_api_log.py

# 资源 (Resources)
- resources/param_schemas.json
- resources/skill_notes.md
