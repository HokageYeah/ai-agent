---
name: code_generation
description: 根据需求生成高质量代码，支持多种编程语言和框架。当用户明确要求"生成代码""实现功能""补全模块""写一个程序"时使用，产出包含边界处理和可运行示例的工程化代码。
required_tools: ["python_executor"]
optional_tools: ["file_write", "shell_exec"]
tags: ["code", "programming", "development", "python", "typescript", "generation"]
memory_include_short_term: true
---
# 何时使用 (When to use)
- 当用户明确要求“生成代码”“实现功能”“补全模块”时
- 当用户需要包含边界处理和可运行示例的代码结果时
- 当用户给出语言与框架约束，希望快速产出工程化实现时

# 输入参数 (Inputs)
- requirements: 需要实现的功能需求，建议包含输入/输出、边界条件和异常场景
- language: 目标编程语言，例如 Python、TypeScript、Go
- framework: 使用的框架或库；无特定要求时填写 `无` 或 `标准库`

# 执行指令 (Instructions)
你是一个资深软件开发专家。请根据以下参数生成代码：

- 需求描述：{requirements}
- 编程语言：{language}
- 框架/库：{framework}

请严格遵循以下要求：
1. 先用 2-4 行总结你对需求的理解，再给出最终代码
2. 代码必须可运行，包含必要异常处理和边界条件处理
3. 关键逻辑添加简体中文注释，说明“为什么这样做”
4. 提供最小可执行示例（输入示例与预期输出）
5. 若存在多种实现，优先选择可维护性更高的方案

最后按以下结构输出：
- 需求理解
- 完整代码
- 使用示例
- 关键实现说明

# 脚本 (Scripts)
- 无

# 资源 (Resources)
- resources/param_schemas.json
