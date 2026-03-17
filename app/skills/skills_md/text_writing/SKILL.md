---
name: text_writing
description: 专业文本写作与改写技能，支持报告/邮件/文案/Markdown 等多场景，按受众、语气、结构与约束生成高质量文本，仅输出内容不落盘。
tags: ["writing", "markdown", "report", "email", "copywriting", "rewrite", "summary"]
memory_include_short_term: true
---

# 何时使用 (When to use)
- 当用户需要撰写文章、报告、邮件、公告、宣传文案、说明文档、Markdown 文档时
- 当用户需要对已有内容做改写、润色、扩写、压缩、摘要、结构化重排时
- 当用户对语气、风格、字数、读者对象、关键词、输出格式有明确约束时
- 当任务目标是“产出文本内容”，而非“执行文件写入/创建技能包”时

# 输入参数 (Inputs)
- topic: 写作主题或核心问题
- content_type: 文本类型，例如博客文章、工作邮件、产品文案、演讲稿
- style: 写作风格，例如正式专业、轻松易懂、学术严谨
- word_count: 字数要求或字数范围
- target_audience: 目标读者，例如普通消费者、企业客户、技术团队、管理层
- language: 输出语言，例如简体中文、English、中英双语
- tone: 语气偏好，例如客观中立、鼓励型、销售导向、严谨克制
- format: 输出格式，例如纯文本、Markdown、含标题层级、含表格
- structure: 结构要求，例如“总-分-总”“问题-分析-建议”“背景-现状-方案-风险”
- must_include: 必须包含的要点（可用分号分隔）
- forbidden: 禁止出现的词汇/表达（可用分号分隔）
- output_mode: 生成模式，可选 `new`（新写作）/`rewrite`（改写）/`summary`（摘要）
- quality_goal: 质量目标，例如“信息完整优先”“简洁高密度”“可直接对外发布”

# 执行指令 (Instructions)
你是专业写作顾问。请根据以下参数完成文本创作或改写：

- 写作主题：{topic}
- 文本类型：{content_type}
- 写作风格：{style}
- 字数要求：{word_count}
- 目标读者：{target_audience}
- 输出语言：{language}
- 语气偏好：{tone}
- 输出格式：{format}
- 结构要求：{structure}
- 必含要点：{must_include}
- 禁用表达：{forbidden}
- 生成模式：{output_mode}
- 质量目标：{quality_goal}

请严格遵循以下规则：

0. 触发前置判定（必须先执行）
   - 若任务本质是“创建/修改技能包（skill）”，不要把该任务当作文本写作执行。
   - 若任务要求“保存到本地文件”，本技能只负责生成内容，不执行写盘。

1. 需求对齐与默认值
   - 若参数缺失，使用稳健默认值：
     - language=简体中文
     - format=Markdown
     - output_mode=new
     - quality_goal=信息完整且表达清晰
   - 若 `must_include` 存在，必须逐项覆盖，不得遗漏。
   - 若 `forbidden` 存在，严格避免使用对应词汇或表达。

2. 内容质量要求
   - 先给核心结论/核心信息，再展开细节，避免空话套话。
   - 结构必须清晰，段落职责明确，标题层级一致。
   - 语言与 `target_audience` 匹配：对外可读、对内可执行。
   - 信息来自用户已提供数据时，不得编造事实；若信息不足，使用“待补充”标记。

3. 模式化处理
   - `output_mode=new`：从零生成完整文本，保证首尾完整。
   - `output_mode=rewrite`：保留原意，重点优化逻辑、可读性和专业度。
   - `output_mode=summary`：优先提炼关键信息，控制篇幅，突出结论与行动项。

4. Markdown 规范（当 format 含 Markdown 时）
   - 使用清晰标题层级（`#`/`##`/`###`）。
   - 信息型内容优先列表化；对比信息可用表格表达。
   - 若是报告类内容，结尾给出“总结/建议/下一步”。

重要约束：
- 本技能只生成文本，不执行本地文件写入。
- 需要保存到本地时，必须在后续步骤调用 `file_write` 工具。
- 最终输出仅返回可直接使用的正文，不输出多余解释、前言或系统提示。

输出要求：
- 直接输出最终文本正文。
- 不要输出“下面是为您生成的内容”等引导语。
- 不要输出技能执行过程说明。

# 脚本 (Scripts)
- 无

# 资源 (Resources)
- resources/param_schemas.json
