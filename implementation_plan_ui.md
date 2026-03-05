# Agent 轨迹 UI 重设计计划

本计划概述了对 `web/src/views/agents/AgentsView.vue` 的改造，以满足新的 UI 需求：按迭代分组轨迹步骤、支持折叠、将子智能体隔离为独立的可折叠区块，并应用现代化美学设计。

## 一、拟议变更

### 1. 整体布局反转（聊天 UI 风格）
- 调换"任务输入区域"与"轨迹展示区域"的位置
- 轨迹区域（已执行动作的历史记录）将位于顶部，占据可用高度，并具有灵活的滚动区域
- 任务输入区域（文本框 + 执行按钮）将固定/放置在屏幕底部。这为将来实现多轮对话体验做好准备

### 2. 数据结构转换
不再将 `streamEvents` 映射为扁平数组 `streamEventsWithBlockInfo`，我们将引入一个嵌套的计算属性 `groupedStreamEvents`：

- **层级 1**：迭代（`迭代 1`、`迭代 2` 等）。每个迭代跟踪一个 `expanded` 状态
- **层级 2**：迭代内的区块。一个区块可以是主智能体执行流程，或子智能体执行流程（`sub_agent_start` 到 `sub_agent_end`）。每个区块跟踪一个 `expanded` 状态
- **层级 3**：区块内的实际流事件（`plan_start`、`tool_complete` 等）

### 3. UI/UX 重设计
- **迭代区块**：将每个迭代包裹在可视容器中（Bento 盒子风格），头部显示"迭代 X"和折叠/展开切换按钮。默认情况下，最新的迭代处于展开状态
- **智能体区块**：在迭代内部，将事件分组为主智能体和子智能体的子区块。为这些子区块也提供折叠切换功能。子智能体将有一个独特的标识头部，显示其名称、ID 和任务
- **现代美学**：使用 Element Plus 变量和自定义 CSS 应用毛玻璃效果、柔和阴影和圆角边框。增强事件渲染（思考过程、执行步骤）以提高可读性

### 4. 修改 AgentsView.vue
- 新增 Vue 接口类型：`GroupedIteration`、`AgentBlock`
- 用 `groupedStreamEvents` 替换 `streamEventsWithBlockInfo`
- 将当前的 `<el-timeline>` 扁平循环替换为嵌套的 `v-for` 循环，遍历 迭代 -> 区块 -> 事件
- 添加切换方法，如 `toggleIteration(iter)` 和 `toggleBlock(block)`
- 更新 `.execution-panel` 的 flex 布局，正确支持 `flex-direction: column`，使轨迹区域占据 `flex: 1` 并具有 `overflow-y: auto`，而输入区域固定在底部

## 二、验证计划

### 手动验证步骤
1. 打开 UI，选择一个主智能体（如 `cs_master`），输入一个需要委托给 `order_agent` 和 `general_agent` 的复杂任务（参考示例 3）
2. 观察流解析：
   - 确保外层结构区块显示"迭代 1"、"迭代 2"等
   - 验证点击头部可以折叠/展开迭代
   - 在迭代内部，验证子智能体（如 `order_agent`）有自己的可折叠头部
   - 验证切换子智能体可以隐藏/显示其内部的流事件
3. 验证美学效果（颜色、间距、响应式设计）