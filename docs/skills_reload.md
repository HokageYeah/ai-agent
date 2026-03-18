# AI Agent 技能系统重构指南：迁移至 Claude Code 动态加载模式

## 背景与核心变化

在当前架构中，技能（Skill）采用的是**“预注册 + 直接加载执行”**模式（基于 `Pydantic BaseModel` 硬编码在 Python 文件中）。为了提升系统的扩展性与灵活性，现需将其重构为类似 **Claude Code / OpenAI ReAct Skill Loader** 的模式。

### 架构模式对比

| 特性 | 旧模式（当前架构） | 新模式（Claude Code 风格） |
| :--- | :--- | :--- |
| **注册方式** | 硬编码在 Python 代码中注册 | 基于文件系统，定义在 `skills/<name>/SKILL.md` 中 |
| **LLM 视野** | LLM 需了解并承载所有技能的详细 Prompt | LLM 仅看精简的技能元数据列表（Metadata List） |
| **调用逻辑** | 执行时直接指定 `skill_id` 调用 | LLM 根据任务动态决定是否调用以及调用哪个技能 |
| **加载机制** | 运行时（Runtime）全量预加载 | **按需动态加载（Lazy Loading）** |
| **技能边界** | 仅包含 Prompt 模板和所需工具声明 | 可独立打包，包含专有的 `scripts/` 和 `resources/` |

---

## 一、 技能包目录与文件规范

技能将从代码中剥离，转变为独立的文件夹，统一存放在 `skills/` 目录下。

### 1. 典型目录结构

```text
/app
    ├──
    skills/
    ├── code_review/                  # 技能唯一标识
    │    ├── SKILL.md                 # 技能核心定义（元数据 + 指令）
    │    ├── scripts/                 # 技能专用的可执行脚本
    │    │     └── analyze_repo.py
    │    └── resources/               # 技能依赖的静态资源
    │          └── rules.md
    │
    ├── data_analysis/
    │    ├── SKILL.md
    │    ├── scripts/
    │    └── resources/
```

### 2. `SKILL.md` 规范示例

采用 **YAML Frontmatter + Markdown Body** 结构。顶部 YAML 用于系统轻量级解析，Markdown 主体用于执行时的 Prompt 注入。

```markdown
---
name: code_review
description: 审查源代码并提供改进建议
---

# 何时使用 (When to use)
在以下情况下使用此技能：
- 当用户要求进行代码审查时
- 当用户寻求代码重构建议时
- 当用户询问代码最佳实践时

# 输入参数 (Inputs)
repository_path: 代码仓库的路径
language: 编程语言

# 执行指令 (Instructions)
1. 分析代码仓库的目录结构
2. 识别潜在的代码问题和坏味道
3. 提供具体的改进建议
4. 必要时提供重构的代码示例

# 脚本 (Scripts)
scripts/analyze_repo.py

# 资源 (Resources)
resources/coding_rules.md
```

---

## 二、 现有架构改造点

以 `SkillManager` 为核心，原有的一次性加载执行逻辑需拆分为“发现 -> 路由 -> 加载执行”的三步走逻辑。

**当前架构：**
```python
class SkillManager:
    def register_skill()  # 注册技能
    def get_skill()       # 获取技能
    def execute_skill()   # 执行技能
```

**改造后架构：**
```python
class SkillManager:
    def discover_skills()         # 启动时扫描 SKILL.md，仅解析 YAML 头部
    def list_skill_metadata()     # 为 LLM 生成轻量级的可用技能列表
    def load_skill(skill_name)    # 按需读取完整的 Markdown 和相关路径
    def execute_skill_runtime()   # 组装上下文并执行局部推理
```

### 工作流演进对比

*   **当前执行流：** 用户请求 ➜ Agent 规划 ➜ 技能执行
*   **升级后执行流（解耦）：** 用户请求 ➜ **技能发现与路由 (LLM)** ➜ Agent 规划 ➜ **技能运行时 (动态加载执行)**

### 当前落地实现（v1.5+）

为兼顾可解释性、稳定性与动态扩展能力，当前主链路采用**混合模式**：

1. **规则预筛阶段（代码侧）**：`_route_skills_by_metadata()` 基于任务文本与技能元数据进行打分，先筛出 Top-K 候选技能。  
2. **LLM 决策阶段（规划侧）**：Planning 仅接收候选技能元信息，由 LLM 决定是否调用技能、调用哪个技能及参数。  
3. **执行阶段（运行时）**：仅在实际执行 `action=skill` 时通过 `load_skill/get_skill` 懒加载技能正文与资源。  

其中规则预筛中的 `skill_boost_rules` 已改为**动态构建**（来源于 `skill_id/name/tags/inputs/when_to_use/description`），不再写死具体技能映射；并通过跨技能高频词抑制减少误召回。

---

## 三、 核心大模型提示词（Prompts）

核心思想：**LLM 在决策阶段只看 Metadata，不加载具体实现。只有当 LLM 确定选择该技能后，系统才加载完整上下文进行执行。**

### 1. 技能发现与路由 Prompt（生产级推荐）

这是给 LLM 的**技能选择**提示词，用于任务的初始规划或意图路由阶段：

```text
你是一个智能 AI Agent，拥有一个动态技能库的访问权限。

技能是存储在外部的模块化能力。
每个技能都包含执行指令、脚本和资源。

你必须首先确定使用某个技能是否能帮助解决用户的任务。

可用技能列表：
{{skills}}

决策规则：
- 如果任务明确匹配某个技能，请使用该技能。
- 如果通过简单的逻辑推理就能解决问题，请不要使用技能。
- 优先选择最专业、最对口的技能。
- 除非绝对必要，否则避免将多个技能串联使用。

请以 JSON 格式返回你的决策：
{
  "use_skill": true | false,
  "skill_name": "如果需要使用，请填写技能名称",
  "confidence": 0.95,
  "reason": "解释需要或不需要使用该技能的原因",
  "inputs": {}
}
```

### 2. 构建传递给 LLM 的技能列表 `{{skills}}`

系统启动时扫描解析出的列表（不要包含 Scripts 和 Instructions 等细节），将其注入到上述 Prompt 的 `{{skills}}` 变量中：

```text
技能名称: code_review
描述: 分析源代码并提供质量反馈
何时使用:
- 当用户要求进行代码审查时
- 当用户询问代码最佳实践时
输入参数:
- repository_path (代码仓库路径)
- programming_language (编程语言)

技能名称: data_analysis
描述: 分析数据集并生成洞察报告
何时使用:
- 当用户要求分析 CSV/JSON 等数据时
输入参数:
- data_file (数据文件路径)
```

### 3. 技能执行 Prompt（Skill Execution）

当 LLM 返回上述 JSON 决定使用某技能后，系统调用 `load_skill` 组装以下 Prompt 交给**执行引擎**：

```text
你正在执行技能：{{skill_name}}

技能描述：
{{skill_description}}

执行指令：
{{skill_instructions}}

可用资源：
{{resource_list}}

可用脚本：
{{script_list}}

用户请求：
{{user_request}}

请严格遵循上述技能执行指令。
如果提供了可用脚本，你可以在需要时调用它们。

请为用户返回最终的执行结果。
```

---

## 四、 进阶优化：引入技能检索机制（Skill Embedding）

**痛点**：当技能库逐渐庞大（超过 20-30 个技能）时，将所有技能的 Metadata 全部塞入 Prompt 会导致 Token 浪费及 LLM 注意力分散（产生幻觉）。

**解决方案**：引入向量检索（Vector Search），实现类似 Claude Code 的精准路由能力。

**目录结构扩充：**
```text
skills/
 ├ skill_index.json      # 技能基础倒排索引
 ├ embeddings/           # 向量化存储（如 FAISS / ChromaDB 缓存）
 └ ...
```

**执行流程优化：**
1. 接收 `用户请求 (User Request)`
2. 对请求进行向量化检索 (`Vector Search Skills`)
3. 召回相关度最高的 Top 5 技能
4. 将这 5 个技能的 Metadata 传入上文的**“技能发现与路由 Prompt”**
5. 由 LLM 进行最终确认，决定调用哪个技能以及提取对应的参数


## 重要提示
1. 在本次重构中，请暂时不要实现“技能向量检索（Skill Embedding/Vector Search）”机制！先实现整体技能架构的转换，后续有需要在实现优化。
2. 技能加载器可以参考app/skills/skills.py文件，这个文件是从其他工程里面拿过来的，可作为参考，如果不需要参考可以忽略
