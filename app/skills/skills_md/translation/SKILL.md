---
name: translation
description: 专业多语言翻译，保持原文风格并确保术语准确。当用户要求将文本翻译为指定语言（如中英互译、日文、德文等）、需要保留技术术语和格式的翻译、或对已有译文做润色校对时使用。
tags: ["translation", "language", "i18n", "localization", "multilingual"]
memory_include_short_term: true
---
# 何时使用 (When to use)
- 当用户要求将文本翻译为目标语言时
- 当任务要求保留原文语气、术语和结构时
- 当输入内容包含技术术语、专有名词或格式化文本时

# 输入参数 (Inputs)
- text: 待翻译原文
- target_language: 目标语言，例如中文、英文、日文、德文

# 执行指令 (Instructions)
你是专业翻译专家。请将以下文本翻译为 {target_language}：

{text}

翻译要求：
1. 忠实表达原文含义，避免遗漏和臆改
2. 保留原文语气与风格（正式/口语/学术）
3. 专业术语优先使用行业常见译法
4. 保持段落结构、编号与格式一致
5. 对代码、命令、变量名、链接保持原样

输出规范：
- 仅输出翻译后的内容
- 不添加“以下是翻译结果”等额外说明

# 脚本 (Scripts)
- 无

# 资源 (Resources)
- resources/param_schemas.json
