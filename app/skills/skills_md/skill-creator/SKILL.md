---
name: skill-creator
description: 根据用户描述自动创建或更新扩展能力包（目录、配置文件、scripts、resources），适配本项目动态路由与懒加载架构。仅在用户明确要求“创建/新建/生成/修改能力包”时使用。
required_tools: ["shell_exec", "list_dir", "file_read", "file_edit"]
optional_tools: ["python_executor", "search"]
tags: ["capability-package", "generator", "dynamic-loading", "scaffold"]
memory_include_short_term: true
---

# 何时使用 (When to use)
- 仅当用户明确提出“创建一个新能力包”“按某个需求生成能力包”时
- 当用户希望把自然语言需求转成可落地的目录结构与文件骨架时
- 当用户明确要求在现有能力包上做迭代（补充脚本、资源、参数定义）时

# 输入参数 (Inputs)
- brief: 用户对目标能力包的自然语言描述（必填）
- skill_name: 目标包唯一 ID（可选，建议小写英文+连字符，例如 `order-reporter`）
- target_dir: 目标包根目录（可选，默认 `app/skills/skills_md`）
- required_tools: 目标包依赖工具（可选，逗号分隔，例如 `shell_exec,file_read`）
- optional_tools: 目标包可选工具（可选，逗号分隔）
- tags: 目标包标签（可选，逗号分隔）
- include_script_template: 是否生成示例脚本（可选，`yes/no`，默认 `yes`）
- include_param_schema: 是否生成 `resources/param_schemas.json`（可选，`yes/no`，默认 `yes`）
- overwrite: 若同名目标包已存在是否覆盖（可选，`yes/no`，默认 `no`）

# 执行指令 (Instructions)
你是“技能创建助手”。目标是把用户描述转换成**符合本项目动态技能规范**的技能包，并确保可立即被 `SkillManager` 发现。

请严格按以下顺序执行：

0. 触发前置判定（必须先执行）
   - 仅当用户明确表达“请创建/新建/生成/改造一个能力包”时才继续执行后续步骤。
   - 如果用户只是问“有哪些技能/能力”“某个技能不存在怎么办”“请调用某个不存在的技能”，但没有明确要求创建，禁止自动创建。
   - 以上非触发场景必须直接返回说明：当前不应调用 skill-creator，应先由主模型回答或让用户明确创建意图。

1. 解析参数  
   - 若未给出 `skill_name`，根据 `brief` 生成一个规范化 ID（小写、连字符、长度 <= 64）。  
   - 若用户给的 `skill_name` 不合法，也要自动规范化后再创建。  

2. 调用脚本创建技能骨架（必须执行）  
   - 使用 `shell_exec` 执行以下命令（按需替换参数）：
```bash
python3 app/skills/skills_md/skill-creator/scripts/create_skill_from_brief.py \
  --brief "{brief}" \
  --skill-name "{skill_name}" \
  --target-dir "{target_dir}" \
  --required-tools "{required_tools}" \
  --optional-tools "{optional_tools}" \
  --tags "{tags}" \
  --include-script-template "{include_script_template}" \
  --include-param-schema "{include_param_schema}" \
  --overwrite "{overwrite}"
```

3. 回读并校验生成结果  
   - 使用 `list_dir` 查看目标技能目录；  
   - 使用 `file_read` 读取新技能 `SKILL.md`；  
   - 若生成了 `resources/param_schemas.json`，也要读取并确认 JSON 可读。  

4. 按用户追加要求做增量修订  
   - 使用 `file_edit` 精准修改生成内容。  
   - 保持章节结构与本项目规范一致：  
     - `# 何时使用 (When to use)`  
     - `# 输入参数 (Inputs)`  
     - `# 执行指令 (Instructions)`  
     - `# 脚本 (Scripts)`  
     - `# 资源 (Resources)`  

5. 最终返回必须包含  
   - 创建出的技能 ID 与目录路径  
   - 已创建文件列表  
   - 可直接在对话窗口验证的提问示例（至少 1 条）  
   - 若失败：失败原因、失败阶段、可执行修复建议

执行约束：
- 禁止创建与技能运行无关的文档（如 README、CHANGELOG）。  
- 优先保证“可运行、可发现、可懒加载”，不要堆叠冗长说明。  
- 输出内容必须使用简体中文。

# 脚本 (Scripts)
- scripts/create_skill_from_brief.py

# 资源 (Resources)
- resources/param_schemas.json
- resources/skill_blueprint.md
