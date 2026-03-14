---
name: tmux
description: 通过 tmux 会话控制交互式命令行，支持发送按键与抓取面板输出。
---

# 何时使用 (When to use)
- 当任务必须驱动交互式 TTY 程序（如 REPL、需要持续输入的 CLI）时
- 当需要向会话发送按键并周期性抓取终端输出时
- 当需要并行维护多个独立终端会话并持续观测其状态时

# 输入参数 (Inputs)
- goal: 目标操作，例如“在 Python REPL 中执行一组命令并读取输出”
- session: 会话名（可选），默认建议 `ai-agent-session`
- socket: tmux socket 路径（可选），建议使用私有路径避免冲突
- target: pane 目标（可选），格式 `session:window.pane`，默认 `session:0.0`

# 执行指令 (Instructions)
你是 tmux 会话操作助手。请遵循以下约束：

1. 仅在“必须交互”的场景使用 tmux；非交互长任务优先普通后台命令
2. 必须使用独立 socket，避免污染用户已有 tmux 环境
3. 所有命令先给“可直接执行版本”，再解释关键参数
4. 执行后给出监控命令，便于用户接管与排查

推荐初始化流程：
```bash
SOCKET_DIR="${AI_AGENT_TMUX_SOCKET_DIR:-${NANOBOT_TMUX_SOCKET_DIR:-${TMPDIR:-/tmp}/ai-agent-tmux-sockets}}"
mkdir -p "$SOCKET_DIR"
SOCKET="$SOCKET_DIR/ai-agent.sock"
SESSION="ai-agent-session"

tmux -S "$SOCKET" new -d -s "$SESSION" -n shell
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -- 'PYTHON_BASIC_REPL=1 python3 -q' Enter
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

监控与排查：
```bash
# 进入会话观察
tmux -S "$SOCKET" attach -t "$SESSION"

# 抓取最近输出
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200

# 列出会话与面板
tmux -S "$SOCKET" list-sessions
tmux -S "$SOCKET" list-panes -a
```

输入发送规范：
- 普通文本优先字面量发送：`tmux -S "$SOCKET" send-keys -t "$TARGET" -l -- "$cmd"`
- 控制信号单独发送：`tmux -S "$SOCKET" send-keys -t "$TARGET" C-c`
- 目标格式统一为 `session:window.pane`，默认 `:0.0`

清理规范：
```bash
# 关闭单个会话
tmux -S "$SOCKET" kill-session -t "$SESSION"

# 关闭该 socket 下全部会话
tmux -S "$SOCKET" list-sessions -F '#{session_name}' | xargs -r -n1 tmux -S "$SOCKET" kill-session -t

# 关闭并移除整个 tmux server
tmux -S "$SOCKET" kill-server
```

平台约束：
- macOS / Linux 原生支持 tmux
- Windows 请在 WSL 内安装并运行 tmux

# 脚本 (Scripts)
- scripts/find-sessions.sh
- scripts/wait-for-text.sh

# 资源 (Resources)
- 无
