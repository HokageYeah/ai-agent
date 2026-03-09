**【角色设定与技术栈】**
你是一个资深的前端开发工程师和 UX/UI 设计师。请使用 **[请填写你的前端框架，例如：React / Vue3]** 和 **[原生 CSS / CSS Modules / SCSS，严禁使用 Tailwind CSS]** 为我开发一个“AI Agent 思考与执行轨迹”的展示组件。

**【核心视觉规范：纯缩进极简树 (Pure Indentation Tree)】**
这是本需求最重要的设计原则，请严格遵守：
1. **绝对禁止卡片与引导线**：不要使用任何形式的外层卡片（No Cards）、阴影（No Box-Shadow），**绝对不要使用左侧垂直引导线（No Left Border/Lines）**。
2. **留白驱动层级**：完全依靠左侧的空白缩进（如 CSS 的 `padding-left` 或 `margin-left`，建议每个层级缩进 `24px` 或 `2rem`）来表达父子层级关系。
3. **折叠交互指示**：因为没有引导线，具有子节点的父级项，其最左侧只需保留一个极简的折叠/展开箭头图标（如 `>` 和 `v`，颜色用浅灰），点击整行即可触发展开折叠。
4. **悬停高亮 (Hover)**：当鼠标悬停在任意一层的数据行上时，给予整行一个极淡的背景色（如 `#f9fafb`），这是区分当前阅读行的唯一视觉辅助。

**【色彩与排版规范（浅色极客风）】**
1. **背景**：全局纯白 `#ffffff`。
2. **品牌主色**：执行中的节点、核心图标或高亮文字使用紫色 `#8b5cf6`；成功状态使用绿色 `#10b981`；失败使用红色 `#ef4444`；等待确认使用橙色 `#f59e0b`。
3. **字体运用（关键）**：
   - 描述性文本（如“Agent 正在分析任务”）使用常规无衬线字体，颜色深灰 `#111827`。
   - **所有的专业名词**（如 `order_agent`）、工具名（`database_query`）、文件路径、代码、JSON参数，**必须使用等宽字体（Monospace）**，文字颜色略深，配合极其微弱的浅灰背景色包裹成行内小标签。

**【数据映射与多级缩进结构 (Level 0 - Level 3)】**
后端会通过 SSE 推送 JSON 数据流。包含 `iteration`, `plan`, `execute`, `sub_agent`, `tool`, `reflection` 等事件。你需要将其解析并渲染为以下**纯缩进**结构：

*   **[Indent Level 0: 顶层] 迭代层 (Iteration)**
    *   触发条件：数据中的 `iteration` 字段。如 `> 迭代回合 0 (Iteration 0)`。
    *   **[Indent Level 1: 缩进 24px] 核心阶段层 (Phases)**
        *   对应 `plan_start/complete`, `step_start`, `reflection_start/complete`。
        *   如：`> 🤔 规划与推理`、`> ⚡️ 执行阶段`。
        *   **[Indent Level 2: 缩进 48px] 动作与区块层 (Actions & Blocks)**
            *   单行子动作：`[机器人图标] 委派给 order_agent`
            *   长文本区块（如 reasoning/SQL结果）：**不要边框**，文字颜色变浅（`#6b7280`），字体略小，作为段落文本直接平铺。
            *   **[Indent Level 3: 缩进 72px] 子 Agent 内部细节**
                *   **⚠️核心难点**：当解析到 `is_sub_agent: true` 的数据时，必须递归地将其内部的流程渲染在触发它的 `sub_agent` 节点内部。

**【特殊场景 UI 渲染】**
1. **等待用户确认节点 (`user_confirm_required`)**：
   - 渲染一个纯文本的等待提示行，文字颜色使用橙色，使用等宽字体高亮工具名（如 `file_write`），并提供确认/拒绝按钮。
2. **执行失败与重新规划 (`needs_replanning: true`)**：
   - 在 Reflection 阶段使用红色文字平铺展示 `feedback` 原因。
3. **✨ 底部流式加载中状态 (Streaming / Loading Indicator)**：
   - **触发条件**：只要 SSE 连接未断开，且任务尚未完结（如还没收到最终的 complete/end 信号）。
   - **位置**：永远固定在整个树状日志流的**最底部**（无需跟随当前节点的缩进，靠最左侧即可）。
   - **UI 设计**：**严禁使用传统的旋转菊花圈 (Spinner)**。请使用类似终端命令行正在执行的极客感效果。
   - **具体样式**：展示文字 `Agent 正在思考与执行`，后面紧跟一个**纯 CSS 实现的闪烁终端光标**（例如一个宽高相近的实心矩形 `▮` 或者下划线 `_`，使用 `@keyframes blink` 实现 `opacity: 1` 到 `0` 的周期闪烁），或者使用**打字机省略号跳动**动画。文字和光标颜色使用你的品牌主色（紫色 `#8b5cf6`）。

**【开发要求】**
请编写完整的、包含数据解析逻辑的组件代码，并手写原生 CSS/SCSS（严禁 Tailwind）。CSS 中请明确体现不同 `.level-0`, `.level-1` 类的 `padding-left` 递增逻辑。为了演示效果，请在代码中 mock 处理平铺的 SSE JSON 数组流。

---

### 💡 为你准备的“终端光标”动效预览：

你可以将下面这段极简的 HTML/CSS 代码保存为 `.html` 文件在浏览器里打开，看看这种**极客风的 Loading 效果**是不是比传统的转圈图标高级得多：

```html
<!DOCTYPE html>
<html>
<head>
<style>
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 40px;
    background-color: #ffffff;
  }
  
  /* Loading 容器 */
  .streaming-indicator {
    display: flex;
    align-items: center;
    color: #8b5cf6; /* 品牌紫 */
    font-size: 14px;
    font-weight: 500;
    margin-top: 16px;
    padding: 8px 0;
  }

  /* 极客感终端光标闪烁动画 */
  .terminal-cursor {
    display: inline-block;
    width: 8px;
    height: 16px;
    background-color: #8b5cf6;
    margin-left: 6px;
    /* CSS 关键帧闪烁 */
    animation: blink 1s step-end infinite; 
  }

  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }
</style>
</head>
<body>

  <!-- 模拟上面是已经生成的日志树 -->
  <div style="color: #6b7280; font-size: 14px; margin-bottom: 8px;">
    ...<br>
    ▸ 💡 反思与总结 <span style="font-family: monospace; background: #f3f4f6; padding: 2px 4px; border-radius: 4px; font-size: 12px; color: #10b981;">success</span>
  </div>

  <!-- 固定在底部的 Loading 效果 -->
  <div class="streaming-indicator">
    <span class="icon">✨</span>
    <span style="margin-left: 6px;">Agent 正在思考与执行</span>
    <span class="terminal-cursor"></span> <!-- 闪烁的光标 -->
  </div>
