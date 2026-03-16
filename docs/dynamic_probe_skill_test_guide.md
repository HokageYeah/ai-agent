# dynamic_probe 技能测试提问指南

本文用于快速验证技能系统重构后的动态加载模式：
- 元信息路由（只看 metadata）
- 命中后懒加载（加载 SKILL.md 正文与资源）
- 执行脚本（scripts/）
- 读取输出（file_read）

## 推荐提问 1（标准全链路）

```text
请使用 dynamic_probe 技能做一次动态加载验证：
topic=验证天气任务是否只路由 weather
run_script=yes
template_name=report_template.md
save_path=dynamic_probe_report.md
notes=请在最终结果里给出执行命令和报告摘要
```

## 推荐提问 2（验证资源与脚本路径）

```text
请运行 dynamic_probe，主题是“验证技能懒加载后脚本调用成功”，
要求执行脚本并把结果保存到 tmp/dynamic_probe_report.md。
```

## 推荐提问 3（只测懒加载不跑脚本）

```text
请调用 dynamic_probe 技能，但本次 run_script=no。
我要确认技能可以被路由并懒加载，同时返回将要执行的脚本命令。
```

## 日志中应重点关注

1. 路由阶段：
   - `[技能路由]` 日志中出现 `dynamic_probe` 入选。
2. 懒加载阶段：
   - `技能懒加载成功: dynamic_probe`
3. 执行阶段：
   - 有 `python3 app/skills/skills_md/dynamic_probe/scripts/build_probe_report.py ...`
4. 输出阶段：
   - 能读取并返回 `dynamic_probe_report.md`（或你指定的路径）内容摘要。

如果以上 4 点都出现，说明动态加载模式链路验证通过。
