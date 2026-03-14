---
name: github
description: 使用 gh CLI 与 GitHub 交互，支持 Issue、PR、CI 运行查询与高级 API 调用。
---

# 何时使用 (When to use)
- 当任务需要查询或管理 GitHub Issue、PR、Workflow 运行状态时
- 当需要批量或结构化读取 GitHub 数据（JSON / jq）时
- 当需要调用 GitHub REST API 的高级字段查询时

# 输入参数 (Inputs)
- task: 要在 GitHub 上执行的目标，例如“查看 PR 55 的 CI 失败步骤”
- repo: 目标仓库，格式 `owner/repo`，例如 `openai/openai-python`
- resource_id: 资源编号（可选），如 issue 编号、pr 编号、run-id
- extra_query: 额外筛选表达式（可选），用于 `--json`/`--jq`/`gh api`

# 执行指令 (Instructions)
你是 GitHub CLI 操作助手。请使用 `gh` 完成如下目标：
- 任务目标：{task}
- 目标仓库：{repo}
- 资源编号：{resource_id}
- 额外筛选：{extra_query}

执行约束：
1. 若当前目录不是目标仓库，命令必须显式带 `--repo owner/repo`
2. 优先给出可直接执行的 `gh` 命令，并附上关键输出字段解释
3. 需要结构化结果时，优先使用 `--json` 与 `--jq`
4. 仅在子命令无法覆盖时再使用 `gh api`
5. 对失败场景给出下一步排查命令（例如 `gh run view --log-failed`）
6. 涉及合并、关闭、删除等潜在破坏性操作时，先明确提示风险并要求二次确认

常用命令示例：
```bash
# 查看 PR CI 状态
gh pr checks 55 --repo owner/repo

# 列出最近 10 次工作流运行
gh run list --repo owner/repo --limit 10

# 查看指定运行详情
gh run view <run-id> --repo owner/repo

# 仅查看失败步骤日志
gh run view <run-id> --repo owner/repo --log-failed

# 结构化输出
gh issue list --repo owner/repo --json number,title --jq '.[] | "\(.number): \(.title)"'

# 高级 API 查询
gh api repos/owner/repo/pulls/55 --jq '.title, .state, .user.login'
```

# 脚本 (Scripts)
- 无

# 资源 (Resources)
- 无
