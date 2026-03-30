"""
压缩与解压工具模块
=================

本模块提供通用的 ZIP 压缩与解压能力，供 Agent 在“下载技能包后落地安装”等场景中直接调用。

设计目标：
1. 提供结构化参数的压缩/解压工具，减少模型拼接 shell 命令的不确定性
2. 复用文件工具的路径安全策略（支持 ~ 展开、目录白名单/全路径模式）
3. 解压阶段内置 Zip Slip 防护，避免路径穿越写出目标目录

当前支持：
- ZIP 压缩（archive_compress）
- ZIP 解压（archive_extract）
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from colorama import Fore, Style
from loguru import logger

from app.tools.base import ToolSchema
from app.tools.builtin.file import BaseFileTool


class BaseArchiveTool(BaseFileTool):
    """压缩工具基类，复用 BaseFileTool 的路径校验能力。"""

    def _safe_member_target(
        self,
        output_dir: Path,
        member_name: str,
    ) -> Tuple[bool, Optional[Path], str]:
        """
        计算压缩包成员的安全落地路径，防止路径穿越攻击。

        安全规则：
        1. 禁止绝对路径成员（/xxx 或 C:\\xxx）
        2. 禁止包含上级目录跳转（..）
        3. 最终 resolve 后必须仍在 output_dir 内
        """
        normalized = str(member_name or "").replace("\\", "/").strip()
        if not normalized:
            return False, None, "压缩包成员路径为空"

        member_path = Path(normalized)
        if member_path.is_absolute():
            return False, None, f"检测到绝对路径成员，已拒绝: {member_name}"

        if ".." in member_path.parts:
            return False, None, f"检测到路径穿越成员，已拒绝: {member_name}"

        target_path = (output_dir / member_path).resolve()
        try:
            target_path.relative_to(output_dir.resolve())
        except ValueError:
            return False, None, f"成员路径越界，已拒绝: {member_name}"
        return True, target_path, ""

    def _expand_extract_member_name(
        self,
        member_name: str,
        strip_prefix: Optional[str],
    ) -> str:
        """根据 strip_prefix 裁剪成员名前缀（用于去掉统一顶层目录）。"""
        normalized = str(member_name).replace("\\", "/")
        if not strip_prefix:
            return normalized
        prefix = strip_prefix.rstrip("/") + "/"
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
        return normalized


class ArchiveExtractTool(BaseArchiveTool):
    """
    ZIP 解压工具。

    planning_safe = False：
        解压操作会在磁盘写入文件，属于不可逆副作用，
        必须在 Execution Node 内执行。
    """

    # 有副作用——磁盘写入，禁止在 Planning tool-calling loop 中调用
    planning_safe: bool = False

    def __init__(
        self,
        allowed_base_dirs: List[str] = None,
        max_file_size: int = 10 * 1024 * 1024,
        allow_full_paths: Optional[bool] = None,
    ):
        super().__init__(
            allowed_base_dirs=allowed_base_dirs,
            max_file_size=max_file_size,
            allow_full_paths=allow_full_paths,
        )
        self._name = "archive_extract"
        self._description = "解压 ZIP 压缩包到指定目录（内置路径穿越防护）。"
        logger.info(f"{Fore.CYAN}[ArchiveExtractTool] 解压工具初始化完成{Style.RESET_ALL}")

    @property
    def name(self) -> str:
        return self._name

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "archive_path": {
                        "type": "string",
                        "description": "ZIP 压缩包路径（本地文件路径）",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "解压目标目录；不传则默认解压到压缩包同名目录",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "若目标文件已存在，是否覆盖",
                        "default": False,
                    },
                    "strip_top_level": {
                        "type": "boolean",
                        "description": "若压缩包内容都在同一顶层目录下，是否自动去掉该目录",
                        "default": False,
                    },
                },
                "required": ["archive_path"],
                "additionalProperties": False,
            },
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        archive_path_raw = (
            params.get("archive_path")
            or params.get("path")
            or params.get("zip_path")
            or ""
        )
        output_dir_raw = params.get("output_dir")
        overwrite = bool(params.get("overwrite", False))
        strip_top_level = bool(params.get("strip_top_level", False))

        if not archive_path_raw:
            return {"success": False, "error": "archive_path 不能为空"}

        ok, archive_path, archive_err = self._validate_path(str(archive_path_raw))
        if not ok:
            return {"success": False, "error": archive_err, "archive_path": archive_path_raw}

        archive_file = Path(archive_path)
        if not archive_file.exists() or not archive_file.is_file():
            return {
                "success": False,
                "error": f"压缩包不存在或不是文件: {archive_path}",
                "archive_path": archive_path,
            }
        if archive_file.suffix.lower() != ".zip":
            return {
                "success": False,
                "error": "当前仅支持 ZIP 压缩包（.zip）",
                "archive_path": archive_path,
            }

        if output_dir_raw:
            output_base_raw = str(output_dir_raw)
        else:
            output_base_raw = str(archive_file.parent / archive_file.stem)
        ok, output_dir_resolved, output_err = self._validate_path(output_base_raw)
        if not ok:
            return {
                "success": False,
                "error": output_err,
                "archive_path": archive_path,
                "output_dir": output_base_raw,
            }

        output_dir = Path(output_dir_resolved)
        logger.info(
            f"{Fore.CYAN}[ArchiveExtractTool] 开始解压 | archive={archive_path} | "
            f"output={output_dir} | overwrite={overwrite} | strip_top_level={strip_top_level}{Style.RESET_ALL}"
        )

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                members = [info for info in zf.infolist() if info.filename and info.filename != "/"]
                if not members:
                    return {
                        "success": False,
                        "error": "压缩包为空，没有可解压的成员",
                        "archive_path": archive_path,
                    }

                # 识别统一顶层目录
                top_levels = set()
                for info in members:
                    normalized = info.filename.replace("\\", "/").strip("/")
                    if not normalized:
                        continue
                    top_levels.add(normalized.split("/", 1)[0])
                strip_prefix = None
                if strip_top_level and len(top_levels) == 1:
                    strip_prefix = next(iter(top_levels))

                normalized_members: List[Tuple[zipfile.ZipInfo, Path]] = []
                conflicts: List[str] = []
                for info in members:
                    logical_name = self._expand_extract_member_name(info.filename, strip_prefix)
                    logical_name = logical_name.strip("/")
                    if not logical_name:
                        # 顶层目录本身被 strip 掉后可能为空，跳过
                        continue

                    safe_ok, target_path, safe_err = self._safe_member_target(output_dir, logical_name)
                    if not safe_ok or target_path is None:
                        return {
                            "success": False,
                            "error": safe_err,
                            "archive_path": archive_path,
                            "member": info.filename,
                        }

                    if target_path.exists() and not overwrite:
                        conflicts.append(str(target_path))
                    normalized_members.append((info, target_path))

                if conflicts:
                    preview = conflicts[:20]
                    return {
                        "success": False,
                        "error": "检测到已存在文件，且 overwrite=false",
                        "conflict_count": len(conflicts),
                        "conflicts": preview,
                        "archive_path": archive_path,
                        "output_dir": str(output_dir),
                    }

                extracted_files: List[str] = []
                created_dirs = 0
                output_dir.mkdir(parents=True, exist_ok=True)

                for info, target_path in normalized_members:
                    if info.is_dir():
                        target_path.mkdir(parents=True, exist_ok=True)
                        created_dirs += 1
                        continue

                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, "r") as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted_files.append(str(target_path))

                logger.info(
                    f"{Fore.GREEN}[ArchiveExtractTool] 解压成功 | files={len(extracted_files)} "
                    f"| dirs={created_dirs} | output={output_dir}{Style.RESET_ALL}"
                )
                return {
                    "success": True,
                    "archive_path": archive_path,
                    "output_dir": str(output_dir),
                    "extracted_count": len(extracted_files),
                    "created_dirs": created_dirs,
                    "extracted_files": extracted_files[:100],
                    "truncated": len(extracted_files) > 100,
                }
        except zipfile.BadZipFile:
            logger.exception(f"{Fore.RED}[ArchiveExtractTool] 非法 ZIP 文件: {archive_path}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": "压缩包格式损坏或不是有效 ZIP 文件",
                "archive_path": archive_path,
            }
        except Exception as exc:
            logger.exception(f"{Fore.RED}[ArchiveExtractTool] 解压失败: {exc}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": f"解压失败: {exc}",
                "archive_path": archive_path,
                "output_dir": str(output_dir),
            }


class ArchiveCompressTool(BaseArchiveTool):
    """
    ZIP 压缩工具。

    planning_safe = False：
        压缩操作会在磁盘生成新文件，属于不可逆副作用，
        必须在 Execution Node 内执行。
    """

    # 有副作用——磁盘写入，禁止在 Planning tool-calling loop 中调用
    planning_safe: bool = False

    def __init__(
        self,
        allowed_base_dirs: List[str] = None,
        max_file_size: int = 10 * 1024 * 1024,
        allow_full_paths: Optional[bool] = None,
    ):
        super().__init__(
            allowed_base_dirs=allowed_base_dirs,
            max_file_size=max_file_size,
            allow_full_paths=allow_full_paths,
        )
        self._name = "archive_compress"
        self._description = "将文件或目录压缩为 ZIP 文件。"
        logger.info(f"{Fore.CYAN}[ArchiveCompressTool] 压缩工具初始化完成{Style.RESET_ALL}")

    @property
    def name(self) -> str:
        return self._name

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "source_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要压缩的文件/目录路径列表",
                    },
                    "source_path": {
                        "type": "string",
                        "description": "单个源路径（与 source_paths 二选一）",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "输出 ZIP 路径，建议以 .zip 结尾",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "若输出文件已存在，是否覆盖",
                        "default": False,
                    },
                    "include_root": {
                        "type": "boolean",
                        "description": "压缩目录时是否保留目录根名",
                        "default": True,
                    },
                    "compression_level": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 9,
                        "description": "ZIP 压缩级别（0-9）",
                        "default": 6,
                    },
                },
                "required": ["output_path"],
                "additionalProperties": False,
            },
        )

    def _collect_source_files(
        self,
        source: Path,
        include_root: bool,
    ) -> List[Tuple[Path, str]]:
        """收集待压缩文件，并生成 zip 内部相对路径。"""
        files: List[Tuple[Path, str]] = []
        if source.is_file():
            files.append((source, source.name))
            return files

        if source.is_dir():
            for root, _, filenames in os.walk(source):
                root_path = Path(root)
                for filename in filenames:
                    file_path = root_path / filename
                    rel = file_path.relative_to(source)
                    if include_root:
                        arcname = str(Path(source.name) / rel).replace("\\", "/")
                    else:
                        arcname = str(rel).replace("\\", "/")
                    files.append((file_path, arcname))
            return files

        return files

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        source_paths = params.get("source_paths")
        source_path_single = params.get("source_path")
        output_path_raw = params.get("output_path") or params.get("archive_path") or ""
        overwrite = bool(params.get("overwrite", False))
        include_root = bool(params.get("include_root", True))
        compression_level = int(params.get("compression_level", 6))
        if compression_level < 0 or compression_level > 9:
            compression_level = 6

        normalized_sources: List[str] = []
        if isinstance(source_paths, list):
            normalized_sources.extend([str(p) for p in source_paths if str(p).strip()])
        if source_path_single:
            normalized_sources.append(str(source_path_single))
        if not normalized_sources:
            return {"success": False, "error": "source_paths/source_path 至少提供一个"}
        if not output_path_raw:
            return {"success": False, "error": "output_path 不能为空"}

        ok, output_path_resolved, output_err = self._validate_path(str(output_path_raw))
        if not ok:
            return {
                "success": False,
                "error": output_err,
                "output_path": output_path_raw,
            }
        output_path = Path(output_path_resolved)
        if output_path.suffix.lower() != ".zip":
            output_path = output_path.with_suffix(".zip")

        if output_path.exists() and not overwrite:
            return {
                "success": False,
                "error": "输出文件已存在，且 overwrite=false",
                "output_path": str(output_path),
            }

        source_files: List[Tuple[Path, str]] = []
        source_roots: List[str] = []
        for raw_source in normalized_sources:
            ok, resolved_source, source_err = self._validate_path(raw_source)
            if not ok:
                return {"success": False, "error": source_err, "source_path": raw_source}

            source_path = Path(resolved_source)
            if not source_path.exists():
                return {"success": False, "error": f"源路径不存在: {resolved_source}"}
            source_roots.append(str(source_path))
            source_files.extend(self._collect_source_files(source_path, include_root=include_root))

        if not source_files:
            return {"success": False, "error": "没有可压缩的文件（目录可能为空）"}

        # 检查 zip 内部路径冲突
        arcnames = [arc for _, arc in source_files]
        duplicate_names = sorted({name for name in arcnames if arcnames.count(name) > 1})
        if duplicate_names:
            return {
                "success": False,
                "error": "压缩目标内存在重名路径，请调整 source_paths 或 include_root",
                "duplicate_entries": duplicate_names[:20],
                "duplicate_count": len(duplicate_names),
            }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"{Fore.CYAN}[ArchiveCompressTool] 开始压缩 | output={output_path} | "
            f"sources={len(source_roots)} | files={len(source_files)} | overwrite={overwrite}{Style.RESET_ALL}"
        )

        try:
            with zipfile.ZipFile(
                output_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=compression_level,
            ) as zf:
                for file_path, arcname in source_files:
                    zf.write(file_path, arcname=arcname)

            logger.info(
                f"{Fore.GREEN}[ArchiveCompressTool] 压缩成功 | output={output_path} | "
                f"size={output_path.stat().st_size} bytes{Style.RESET_ALL}"
            )
            return {
                "success": True,
                "output_path": str(output_path),
                "source_count": len(source_roots),
                "file_count": len(source_files),
                "size_bytes": output_path.stat().st_size,
                "entries": arcnames[:100],
                "truncated": len(arcnames) > 100,
            }
        except Exception as exc:
            logger.exception(f"{Fore.RED}[ArchiveCompressTool] 压缩失败: {exc}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": f"压缩失败: {exc}",
                "output_path": str(output_path),
            }
