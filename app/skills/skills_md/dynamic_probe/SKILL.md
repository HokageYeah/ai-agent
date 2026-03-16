---
name: dynamic_probe
description: 用于验证技能系统“元信息路由 + 懒加载 + 脚本调用 + 资源加载”链路的探针技能。
required_tools: ["shell_exec", "file_read", "file_write"]
optional_tools: ["list_dir", "python_executor"]
tags: ["dynamic-loading", "skill-probe", "scripts", "resources"]
memory_include_short_term: true
---

# 何时使用 (When to use)
- 当你要验证技能重构后的“先元信息路由，再按需懒加载”是否生效时
- 当你要测试技能是否可以调用本地脚本并生成文件结果时
- 当你要测试技能是否会读取 `resources/` 内的资源说明与参数配置时

# 输入参数 (Inputs)
- topic: 本次探针测试主题（例如 `验证天气任务只路由 weather`）
- run_script: 是否执行探针脚本，`yes` 或 `no`（默认建议 `yes`）
- template_name: 资源模板文件名（可选，默认 `report_template.md`）
- save_path: 输出文件路径（可选，默认 `dynamic_probe_report.md`）
- notes: 附加说明（可选）

# 执行指令 (Instructions)
你是“技能动态加载验证助手”。你必须严格按以下顺序执行：

1. 首先读取资源清单文件：
   - `app/skills/skills_md/dynamic_probe/resources/checklist.md`
   - 用于确认本次测试步骤是否完整。

2. 如果 `run_script` 不是 `no`，必须执行以下脚本命令（路径不得改写）：
```bash
python3 app/skills/skills_md/dynamic_probe/scripts/build_probe_report.py \
  --topic "{topic}" \
  --template "{template_name}" \
  --output "{save_path}" \
  --notes "{notes}"
```

3. 脚本执行后，读取输出文件 `{save_path}` 的内容，并在最终答复中展示关键片段。

4. 最终答复必须包含：
   - 实际执行的命令
   - 输出文件绝对路径
   - 输出内容摘要
   - 是否通过“动态加载验证”的结论（通过/不通过）

5. 如果失败，必须返回：
   - 失败阶段（资源读取 / 脚本执行 / 文件读取）
   - 错误信息原文
   - 下一步修复建议

# 脚本 (Scripts)
- scripts/build_probe_report.py

# 资源 (Resources)
- resources/param_schemas.json
- resources/checklist.md
- resources/report_template.md
