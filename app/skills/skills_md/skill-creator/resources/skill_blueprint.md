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

4. 命名规范
   - 技能 ID 使用小写英文+连字符
   - 长度建议不超过 64
   - 与目录名保持一致

5. 生成后的自检
   - 能被 SkillManager 扫描到
   - 执行阶段可被懒加载
   - 脚本路径、资源路径与 `SKILL.md` 声明一致
