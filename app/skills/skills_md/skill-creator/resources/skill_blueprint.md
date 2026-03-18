# 技能蓝图（skill-creator 参考）

用于自动创建技能时的最小结构约束：

1. 目录结构
   - `<skill_name>/SKILL.md`（必须）
   - `<skill_name>/scripts/`（按需）
   - `<skill_name>/resources/`（按需）

2. `SKILL.md` 必须包含章节
   - `# 何时使用 (When to use)`
   - `# 输入参数 (Inputs)`
   - `# 执行指令 (Instructions)`
   - `# 脚本 (Scripts)`
   - `# 资源 (Resources)`

3. Frontmatter 最低要求
   - `name`
   - `description`
   - 推荐补充 `required_tools`、`optional_tools`、`tags`、`memory_include_short_term`
   - 可选补充 `output_validators`（声明式输出校验规则列表）
     - 每条规则需包含 `type`（校验类型）、`markers`（标记词列表）、`error`（失败提示）
     - 支持的 type：`must_contain_any`（输出须含至少一个标记词）、`must_not_contain_any`（输出不得含任何标记词）
     - 示例见 `weather/SKILL.md` 的 frontmatter

4. 命名规范
   - 技能 ID 使用小写英文+连字符
   - 长度建议不超过 64
   - 与目录名保持一致

5. 生成后的自检
   - 能被 SkillManager 扫描到
   - 执行阶段可被懒加载
   - 脚本路径、资源路径与 `SKILL.md` 声明一致
