"""
技能管理器（Claude Code 风格动态加载）
====================================

核心约束：
1. 技能来源统一为 `skills_md/<skill_name>/SKILL.md`
2. 文档格式统一为 `YAML Frontmatter + Markdown Body`
3. 元数据阶段优先读取 frontmatter，并补充解析标准章节：
   - 何时使用 (When to use)
   - 输入参数 (Inputs)
   - 执行指令 (Instructions)
   - 脚本 (Scripts)
   - 资源 (Resources)
4. 执行阶段按需懒加载完整技能正文，不做旧架构预注册
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import hashlib
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from colorama import Fore, Style
from loguru import logger

from app.skills.base import MemoryStrategy, ParamSchema, Skill, SkillMetadata


class SkillManager:
    """技能管理器（动态扫描 + 懒加载 + 运行时执行）"""

    def __init__(
        self,
        skills_root: Optional[str | Path] = None,
        auto_discover: bool = True,
    ):
        self.skills_root = (
            Path(skills_root)
            if skills_root
            else Path(__file__).resolve().parent / "skills_md"
        )
        self.auto_discover = auto_discover
        self._metadata: Dict[str, SkillMetadata] = {}
        self._skill_files: Dict[str, Path] = {}
        self._loaded_skills: Dict[str, Skill] = {}
        self._availability: Dict[str, tuple[bool, List[str]]] = {}
        # 目录指纹：用于检测 skills_md 目录是否变化（新增/删除/修改）
        self._last_fs_signature: str = ""
        # 线程锁：避免并发请求同时触发重载导致状态抖动
        self._reload_lock = threading.RLock()

        logger.info(
            f"{Fore.BLUE}SkillManager 初始化完成 | root={self.skills_root} | "
            f"auto_discover={self.auto_discover}{Style.RESET_ALL}"
        )
        if self.auto_discover:
            self.discover_skills(force_reload=True)

    # ------------------------------------------------------------------
    # 对外核心接口
    # ------------------------------------------------------------------
    def discover_skills(
        self,
        force_reload: bool = False,
        include_unavailable: bool = False,
    ) -> List[SkillMetadata]:
        """
        扫描技能目录，生成轻量元数据索引
        """
        with self._reload_lock:
            if self._metadata and not force_reload:
                return self._filter_metadata(include_unavailable=include_unavailable)

            self._metadata.clear()
            self._skill_files.clear()
            self._availability.clear()
            self._loaded_skills.clear()

            if not self.skills_root.exists():
                logger.warning(
                    f"{Fore.YELLOW}技能目录不存在，跳过扫描: {self.skills_root}{Style.RESET_ALL}"
                )
                self._last_fs_signature = self._compute_fs_signature()
                return []

            skill_files = sorted(self.skills_root.glob("*/SKILL.md"))
            logger.info(
                f"{Fore.CYAN}开始扫描技能目录，共发现 {len(skill_files)} 个 SKILL.md{Style.RESET_ALL}"
            )

            for skill_file in skill_files:
                try:
                    raw_content = skill_file.read_text(encoding="utf-8")
                    frontmatter, body = self._split_frontmatter(raw_content)
                    fm = self._parse_frontmatter(frontmatter)
                    sections = self._parse_standard_sections(body)

                    skill_id = str(fm.get("name") or skill_file.parent.name).strip()
                    if not skill_id:
                        logger.warning(
                            f"{Fore.YELLOW}跳过无 name 的技能文件: {skill_file}{Style.RESET_ALL}"
                        )
                        continue

                    description = str(fm.get("description") or "未提供描述").strip()

                    input_defs = self._parse_inputs_section(sections.get("inputs", ""))
                    input_names = list(input_defs.keys())
                    when_to_use = self._parse_markdown_list(sections.get("when_to_use", ""))
                    scripts = self._parse_markdown_list(sections.get("scripts", ""))
                    resources = self._parse_markdown_list(sections.get("resources", ""))

                    required_tools = self._ensure_list(fm.get("required_tools"))
                    optional_tools = self._ensure_list(fm.get("optional_tools"))
                    tags = self._ensure_list(fm.get("tags"))
                    # NOTE: 解析声明式输出校验规则（从 frontmatter 中的 output_validators 字段读取）
                    #       例如 weather 技能可以在 SKILL.md 中声明 "must_contain_any" / "must_not_contain_any" 规则，
                    #       这样新增技能时不需要修改执行引擎 Python 代码。
                    raw_validators = fm.get("output_validators")
                    output_validators: List[Dict[str, Any]] = []
                    if isinstance(raw_validators, list):
                        for v in raw_validators:
                            if isinstance(v, dict):
                                output_validators.append(v)

                    available, missing = self._check_availability(fm=fm)
                    self._availability[skill_id] = (available, missing)

                    meta = SkillMetadata(
                        skill_id=skill_id,
                        name=skill_id,  # Claude Code 风格下 name 使用技能唯一标识
                        description=description,
                        source_path=str(skill_file),
                        when_to_use=when_to_use,
                        inputs=input_names,
                        input_descriptions=input_defs,
                        required_tools=required_tools,
                        optional_tools=optional_tools,
                        tags=tags,
                        memory_include_short_term=bool(
                            fm.get("memory_include_short_term", True)
                        ),
                        scripts=scripts,
                        resources=resources,
                        output_validators=output_validators,
                    )

                    self._metadata[skill_id] = meta
                    self._skill_files[skill_id] = skill_file

                    if available:
                        logger.debug(
                            f"{Fore.GREEN}技能可用: {skill_id} | path={skill_file}{Style.RESET_ALL}"
                        )
                    else:
                        logger.warning(
                            f"{Fore.YELLOW}技能不可用(已保留索引): {skill_id} | 缺失={missing}{Style.RESET_ALL}"
                        )
                except Exception as exc:
                    logger.error(
                        f"{Fore.RED}解析技能失败: {skill_file} | error={exc}{Style.RESET_ALL}"
                    )

            # 记录扫描后的目录签名，作为后续自动重载对比基线
            self._last_fs_signature = self._compute_fs_signature()
            logger.info(
                f"{Fore.GREEN}技能扫描完成，总计 {len(self._metadata)} 个（含不可用技能）"
                f" | fs_signature={self._last_fs_signature[:12]}...{Style.RESET_ALL}"
            )
            return self._filter_metadata(include_unavailable=include_unavailable)

    def list_skill_metadata(
        self,
        include_unavailable: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        获取技能元数据列表（供路由阶段使用）
        """
        self._auto_reload_if_changed(trigger="list_skill_metadata")
        if not self._metadata:
            self.discover_skills(include_unavailable=include_unavailable)
        meta_list = self._filter_metadata(include_unavailable=include_unavailable)
        return [m.model_dump() for m in meta_list]

    def load_skill(self, skill_name: str) -> Optional[Skill]:
        """
        按需加载完整技能
        """
        self._auto_reload_if_changed(trigger=f"load_skill:{skill_name}")
        if skill_name in self._loaded_skills:
            return self._loaded_skills[skill_name]

        if not self._metadata:
            self.discover_skills(include_unavailable=True)

        if skill_name not in self._metadata:
            logger.warning(f"{Fore.RED}技能不存在: {skill_name}{Style.RESET_ALL}")
            return None

        available, missing = self._availability.get(skill_name, (True, []))
        if not available:
            logger.warning(
                f"{Fore.YELLOW}技能当前不可用: {skill_name} | 缺失依赖={missing}{Style.RESET_ALL}"
            )
            return None

        skill_file = self._skill_files[skill_name]
        meta = self._metadata[skill_name]

        try:
            raw_content = skill_file.read_text(encoding="utf-8")
            frontmatter, body = self._split_frontmatter(raw_content)
            fm = self._parse_frontmatter(frontmatter)
            sections = self._parse_standard_sections(body)

            instructions = sections.get("instructions", "").strip()
            if not instructions:
                instructions = body.strip()

            input_defs = self._parse_inputs_section(sections.get("inputs", ""))
            param_schemas = self._build_param_schemas(
                input_defs=input_defs,
                skill_dir=skill_file.parent,
                resources=meta.resources,
            )

            skill = Skill(
                skill_id=meta.skill_id,
                name=meta.name,
                description=meta.description,
                prompt_template=instructions,
                required_tools=meta.required_tools,
                optional_tools=meta.optional_tools,
                memory_strategy=MemoryStrategy(
                    include_short_term=meta.memory_include_short_term
                ),
                tags=meta.tags,
                param_schemas=param_schemas,
                source_path=meta.source_path,
                instruction_markdown=instructions,
                scripts=meta.scripts,
                resources=meta.resources,
                output_validators=meta.output_validators,
            )
            self._loaded_skills[skill_name] = skill

            logger.info(
                f"{Fore.GREEN}技能懒加载成功: {skill_name} | "
                f"inputs={list(param_schemas.keys())}{Style.RESET_ALL}"
            )
            return skill
        except Exception as exc:
            logger.error(
                f"{Fore.RED}技能加载失败: {skill_name} | error={exc}{Style.RESET_ALL}"
            )
            return None

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取技能（按需加载）"""
        return self.load_skill(skill_id)

    def list_skills(self) -> List[Skill]:
        """
        列出可用技能（仅可用）

        说明：仅返回轻量 Skill 视图，执行时再懒加载完整指令。
        """
        self._auto_reload_if_changed(trigger="list_skills")
        if not self._metadata:
            self.discover_skills(include_unavailable=False)

        result: List[Skill] = []
        for meta in self._filter_metadata(include_unavailable=False):
            light_param_schemas = {
                p: ParamSchema(
                    label=p,
                    description=meta.input_descriptions.get(p, f"{p} 参数"),
                    examples=[],
                    required=True,
                )
                for p in meta.inputs
            }
            result.append(
                Skill(
                    skill_id=meta.skill_id,
                    name=meta.name,
                    description=meta.description,
                    prompt_template="",
                    required_tools=meta.required_tools,
                    optional_tools=meta.optional_tools,
                    memory_strategy=MemoryStrategy(
                        include_short_term=meta.memory_include_short_term
                    ),
                    tags=meta.tags,
                    param_schemas=light_param_schemas,
                    source_path=meta.source_path,
                    instruction_markdown="",
                    scripts=meta.scripts,
                    resources=meta.resources,
                )
            )
        return result

    def reload_skills(self, reason: str = "manual") -> List[SkillMetadata]:
        """
        显式重载技能索引（供外部在安装/删除后主动触发）。
        """
        logger.info(
            f"{Fore.CYAN}收到技能重载请求，开始强制扫描 | reason={reason}{Style.RESET_ALL}"
        )
        return self.discover_skills(force_reload=True, include_unavailable=True)

    async def execute_skill_runtime(
        self,
        *,
        skill_name: str,
        user_request: str,
        inputs: Optional[Dict[str, Any]],
        llm_hub: Any,
        config: Any,
    ) -> Any:
        """
        技能运行时执行入口
        """
        skill = self.load_skill(skill_name)
        if not skill:
            raise ValueError(f"技能不存在或不可用: {skill_name}")

        safe_inputs = inputs or {}
        rendered_instructions = self._safe_format(
            template=skill.prompt_template,
            values=safe_inputs,
        )
        runtime_prompt = self._build_runtime_prompt(
            skill=skill,
            user_request=user_request,
            inputs=safe_inputs,
            rendered_instructions=rendered_instructions,
        )

        logger.info(
            f"{Fore.CYAN}开始执行技能: {skill_name} | "
            f"参数键={list(safe_inputs.keys())}{Style.RESET_ALL}"
        )
        return await llm_hub.infer(
            messages=[{"role": "user", "content": runtime_prompt}],
            config=config,
        )

    # ------------------------------------------------------------------
    # 解析与辅助
    # ------------------------------------------------------------------
    def _filter_metadata(self, include_unavailable: bool) -> List[SkillMetadata]:
        rows: List[SkillMetadata] = []
        for skill_id in sorted(self._metadata.keys()):
            available, _ = self._availability.get(skill_id, (True, []))
            if include_unavailable or available:
                rows.append(self._metadata[skill_id])
        return rows

    def _compute_fs_signature(self) -> str:
        """
        计算 skills_root 当前文件系统签名，用于快速判断目录是否变化。

        签名覆盖范围：
        - skills_root 下所有文件（含 SKILL.md、resources、scripts 等）
        - 每个文件的相对路径、mtime_ns、size
        """
        if not self.skills_root.exists():
            return "missing"

        hasher = hashlib.sha1()
        file_count = 0
        for path in sorted(self.skills_root.rglob("*")):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                # 扫描过程中若并发删除，忽略该文件即可
                continue
            rel = path.relative_to(self.skills_root).as_posix()
            payload = f"{rel}|{stat.st_mtime_ns}|{stat.st_size}\n"
            hasher.update(payload.encode("utf-8", errors="ignore"))
            file_count += 1
        hasher.update(f"count={file_count}".encode("utf-8"))
        return hasher.hexdigest()

    def _auto_reload_if_changed(self, trigger: str) -> None:
        """
        自动检测目录变化并按需重载。

        触发时机：list_skills / list_skill_metadata / load_skill 等读取路径前。
        """
        if not self.auto_discover:
            return

        current = self._compute_fs_signature()
        # 首次建立基线（通常初始化 discover 已建立，这里做兜底）
        if not self._last_fs_signature:
            self._last_fs_signature = current
            return
        if current == self._last_fs_signature:
            return

        logger.info(
            f"{Fore.YELLOW}检测到 skills_md 目录变化，自动重载技能索引 "
            f"| trigger={trigger} | old={self._last_fs_signature[:10]}... "
            f"| new={current[:10]}...{Style.RESET_ALL}"
        )
        self.discover_skills(force_reload=True, include_unavailable=True)

    def _split_frontmatter(self, content: str) -> tuple[str, str]:
        if not content.startswith("---"):
            return "", content
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
        if not m:
            return "", content
        return m.group(1).strip(), m.group(2)

    def _parse_frontmatter(self, text: str) -> Dict[str, Any]:
        """
        简化 frontmatter 解析器
        """
        if not text:
            return {}
        data: Dict[str, Any] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            data[k.strip()] = self._parse_value(v.strip())
        return data

    def _parse_value(self, raw: str) -> Any:
        if raw == "":
            return ""
        # JSON list/object
        if (raw.startswith("[") and raw.endswith("]")) or (
            raw.startswith("{") and raw.endswith("}")
        ):
            try:
                return json.loads(raw)
            except Exception:
                return raw
        # quoted string
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            return raw[1:-1]
        lowered = raw.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except Exception:
            return raw

    def _parse_standard_sections(self, body: str) -> Dict[str, str]:
        """
        解析标准章节
        """
        sections: Dict[str, str] = {}
        current_key: Optional[str] = None
        buffer: List[str] = []

        for line in body.splitlines():
            m = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
            if m:
                if current_key:
                    sections[current_key] = "\n".join(buffer).strip()
                current_key = self._normalize_section_name(m.group(1))
                buffer = []
                continue
            if current_key:
                buffer.append(line)

        if current_key:
            sections[current_key] = "\n".join(buffer).strip()

        return sections

    def _normalize_section_name(self, title: str) -> str:
        normalized = title.strip().lower()
        normalized = normalized.replace("（", "(").replace("）", ")")

        mapping = {
            "when_to_use": ["when to use", "何时使用", "使用场景"],
            "inputs": ["inputs", "输入参数", "输入"],
            "instructions": ["instructions", "执行指令", "指令", "执行步骤"],
            "scripts": ["scripts", "脚本"],
            "resources": ["resources", "资源"],
        }
        for key, aliases in mapping.items():
            if any(alias in normalized for alias in aliases):
                return key
        return f"other::{normalized}"

    def _parse_markdown_list(self, text: str) -> List[str]:
        rows: List[str] = []
        in_code_block = False
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block or not line:
                continue

            line = re.sub(r"^[-*+]\s+", "", line)
            line = re.sub(r"^\d+\.\s+", "", line)
            line = line.strip()
            if line and line != "无":
                rows.append(line)
        return rows

    def _parse_inputs_section(self, text: str) -> Dict[str, str]:
        """
        解析输入参数章节，返回 {param_name: description}
        """
        inputs: Dict[str, str] = {}
        for item in self._parse_markdown_list(text):
            if ":" in item or "：" in item:
                sep = ":" if ":" in item else "："
                key, desc = item.split(sep, 1)
                name = key.strip().strip("`")
                description = desc.strip()
            else:
                name = item.strip().strip("`")
                description = f"{name} 参数"
            if name:
                inputs[name] = description
        return inputs

    def _build_param_schemas(
        self,
        *,
        input_defs: Dict[str, str],
        skill_dir: Path,
        resources: List[str],
    ) -> Dict[str, ParamSchema]:
        # 先按 Inputs 章节生成默认参数说明
        schemas: Dict[str, ParamSchema] = {
            name: ParamSchema(
                label=name,
                description=desc,
                examples=[],
                required=True,
            )
            for name, desc in input_defs.items()
        }

        # 再尝试从 resources/param_schemas.json 覆盖更细粒度说明
        param_file = self._find_param_schema_file(skill_dir=skill_dir, resources=resources)
        if param_file:
            try:
                payload = json.loads(param_file.read_text(encoding="utf-8"))
                for key, val in payload.items():
                    if isinstance(val, dict):
                        schemas[key] = ParamSchema(**val)
            except Exception as exc:
                logger.warning(
                    f"{Fore.YELLOW}参数资源解析失败: {param_file} | error={exc}{Style.RESET_ALL}"
                )
        return schemas

    def _find_param_schema_file(self, *, skill_dir: Path, resources: List[str]) -> Optional[Path]:
        for rel in resources:
            rel_path = rel.strip()
            if not rel_path:
                continue
            full = (skill_dir / rel_path).resolve()
            if full.is_file() and full.name.endswith(".json") and "param" in full.name:
                return full
        return None

    def _safe_format(self, *, template: str, values: Dict[str, Any]) -> str:
        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:
                return "{" + key + "}"

        try:
            return template.format_map(_SafeDict(values))
        except Exception:
            return template

    def _build_runtime_prompt(
        self,
        *,
        skill: Skill,
        user_request: str,
        inputs: Dict[str, Any],
        rendered_instructions: str,
    ) -> str:
        scripts_text = "\n".join(f"- {p}" for p in skill.scripts) if skill.scripts else "- 无"
        resources_text = (
            "\n".join(f"- {p}" for p in skill.resources) if skill.resources else "- 无"
        )
        input_text = json.dumps(inputs, ensure_ascii=False, indent=2, default=str)

        return f"""你正在执行技能：{skill.skill_id}

技能描述：
{skill.description}

执行指令：
{rendered_instructions}

可用资源：
{resources_text}

可用脚本：
{scripts_text}

用户请求：
{user_request}

输入参数（JSON）：
{input_text}

请严格遵循技能执行指令完成任务。
若存在脚本或资源，请在需要时合理使用。
最后仅输出对用户有价值的执行结果。"""

    def _ensure_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if "," in text:
                return [x.strip() for x in text.split(",") if x.strip()]
            return [text]
        return [str(value).strip()]

    def _check_availability(self, *, fm: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        兼容 tmux 风格 metadata:
          metadata: {"nanobot":{"os":["darwin"],"requires":{"bins":["tmux"],"env":["A"]}}}
        """
        missing: List[str] = []
        metadata = fm.get("metadata")
        meta_obj: Dict[str, Any] = {}
        if isinstance(metadata, dict):
            meta_obj = metadata
        elif isinstance(metadata, str):
            try:
                meta_obj = json.loads(metadata)
            except Exception:
                meta_obj = {}

        nanobot = meta_obj.get("nanobot", {}) if isinstance(meta_obj, dict) else {}
        if not isinstance(nanobot, dict):
            return True, []

        supported_os = nanobot.get("os", [])
        if isinstance(supported_os, list) and supported_os:
            system_name = platform.system().lower()
            if "darwin" in system_name or "mac" in system_name:
                current_os = "darwin"
            elif "linux" in system_name:
                current_os = "linux"
            elif "windows" in system_name:
                current_os = "windows"
            else:
                current_os = system_name or os.name
            if current_os not in supported_os:
                missing.append(f"OS不匹配: current={current_os}, required={supported_os}")

        requires = nanobot.get("requires", {})
        if isinstance(requires, dict):
            for cmd in requires.get("bins", []) or []:
                if not shutil.which(str(cmd)):
                    missing.append(f"缺少命令: {cmd}")
            for env in requires.get("env", []) or []:
                if not os.environ.get(str(env)):
                    missing.append(f"缺少环境变量: {env}")

        return len(missing) == 0, missing
