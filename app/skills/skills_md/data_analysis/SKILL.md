---
name: data_analysis
description: 分析数据并生成洞察报告，识别趋势、发现异常值并提供可执行建议。当用户要求分析 CSV/JSON/表格数据、提取统计规律、生成数据报告或做数据驱动决策时使用。
required_tools: ["python_executor"]
optional_tools: ["file_read", "shell_exec"]
tags: ["data", "analysis", "statistics", "trend", "report", "csv", "json"]
memory_include_short_term: true
---
# 何时使用 (When to use)
- 当用户要求分析 CSV、JSON、表格文本或数字序列时
- 当用户希望从数据中提取趋势、异常值和可执行建议时
- 当任务需要结构化分析报告而非一句话结论时

# 输入参数 (Inputs)
- data: 待分析数据，可为表格文本、JSON、列表或统计摘要

# 执行指令 (Instructions)
你是资深数据分析师，请对以下数据完成分析：

{data}

分析要求：
1. 给出数据概览（规模、字段、数据质量）
2. 完成核心统计分析（均值/分布/极值等）
3. 识别关键趋势与变化拐点
4. 标记潜在异常并说明判断依据
5. 输出可执行建议，区分“短期动作”和“长期优化”

输出结构必须包含：
- 数据概览
- 统计分析
- 趋势分析
- 异常检测
- 结论与建议

# 脚本 (Scripts)
- 无

# 资源 (Resources)
- resources/param_schemas.json
