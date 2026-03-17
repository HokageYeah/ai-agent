"""
文件操作工具模块

本模块实现了文件读取和写入工具，提供安全的文件操作功能。

功能特点：
1. FileReadTool: 安全读取文件内容
2. FileWriteTool: 安全写入文件内容
3. 路径验证，防止路径遍历攻击
4. 访问控制，限制可操作目录
5. 多种编码支持
6. 完善的错误处理

安全措施：
- 路径规范化（resolve 绝对路径）
- 路径遍历攻击防护
- 可配置的根目录限制
- 文件大小限制
- 编码检测和指定

使用示例：
    # 读取文件
    read_tool = FileReadTool()
    result = await read_tool.execute({"path": "/path/to/file.txt"})
    
    # 写入文件
    write_tool = FileWriteTool()
    result = await write_tool.execute({
        "path": "/path/to/file.txt",
        "content": "Hello, World!"
    })
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from colorama import Fore, Style
from loguru import logger

from app.tools.base import Tool, ToolSchema


class BaseFileTool(Tool):
    """
    文件工具基类
    
    提供文件工具的通用功能，包括：
    - 路径验证
    - 访问控制
    - 编码处理
    
    属性：
        allowed_base_dirs: 允许访问的根目录列表
        max_file_size: 最大文件大小（字节）
    """
    
    def __init__(
        self,
        allowed_base_dirs: List[str] = None,
        max_file_size: int = 10 * 1024 * 1024,  # 默认 10MB
        allow_full_paths: Optional[bool] = None,
    ):
        """
        初始化 BaseFileTool
        
        Args:
            allowed_base_dirs: 允许访问的根目录列表，默认当前工作目录 + 系统临时目录
            max_file_size: 最大文件大小（字节）
            allow_full_paths: 是否允许访问整机任意绝对路径。
                - None: 从环境变量 FILE_TOOL_ALLOW_FULL_PATHS 读取（默认 True）
                - True: 不做目录白名单限制，仅做路径规范化
                - False: 启用 allowed_base_dirs 白名单限制
        """
        if allow_full_paths is None:
            raw_flag = str(os.getenv("FILE_TOOL_ALLOW_FULL_PATHS", "true")).strip().lower()
            self.allow_full_paths = raw_flag in ("1", "true", "yes", "y", "on")
        else:
            self.allow_full_paths = bool(allow_full_paths)

        # 设置允许访问的根目录（仅在白名单模式生效）
        if allowed_base_dirs is None:
            import tempfile
            self.allowed_base_dirs = [os.getcwd(), tempfile.gettempdir()]
        else:
            self.allowed_base_dirs = [
                str(Path(self._expand_user_and_env(d)).resolve())
                for d in allowed_base_dirs
            ]
        
        self.max_file_size = max_file_size
        
        if self.allow_full_paths:
            logger.debug(
                f"{Fore.CYAN}[BaseFileTool] 初始化完成，已启用全路径模式："
                f"允许访问本机任意绝对路径{Style.RESET_ALL}"
            )
        else:
            logger.debug(
                f"{Fore.CYAN}[BaseFileTool] 初始化完成，允许目录: {self.allowed_base_dirs}{Style.RESET_ALL}"
            )

    def _expand_user_and_env(self, raw_path: str) -> str:
        """
        展开用户路径与环境变量。

        设计原因：
        1. LLM 常生成 "~/Desktop/xxx.txt" 这类路径，不展开会被当作普通相对路径。
        2. 部分场景会传 "$HOME/xxx"、"${HOME}/xxx"，也需要先还原为真实目录。
        """
        expanded_path = os.path.expanduser(os.path.expandvars(raw_path))
        if expanded_path != raw_path:
            logger.debug(
                f"{Fore.CYAN}[BaseFileTool] 路径展开: '{raw_path}' -> '{expanded_path}'{Style.RESET_ALL}"
            )
        return expanded_path
    
    def _validate_path(self, path: str) -> tuple[bool, str, str]:
        """
        验证路径安全性
        
        检查路径是否在允许的目录范围内，防止路径遍历攻击。
        
        验证步骤：
        1. 解析路径为绝对路径
        2. 规范化路径（解析 .. 和 .）
        3. 检查是否在允许的目录内
        
        Args:
            path: 文件路径
            
        Returns:
            tuple: (是否合法, 规范化路径, 错误信息)
        """
        if not path:
            return False, "", "路径不能为空"
        
        try:
            # 先展开 "~" 与环境变量，避免被当作普通目录名拼到当前工程路径下
            expanded_path = self._expand_user_and_env(path)

            # 解析为绝对路径
            absolute_path = os.path.abspath(expanded_path)
            
            # 规范化路径（处理 .. 和 .）
            resolved_path = Path(absolute_path).resolve()

            # 全路径模式：仅做路径规范化，不做目录白名单限制
            if self.allow_full_paths:
                return True, str(resolved_path), ""
            
            # 检查路径是否在允许的目录内
            is_allowed = False
            for base_dir in self.allowed_base_dirs:
                try:
                    resolved_base = Path(base_dir).resolve()
                    # 检查 resolved_path 是否在 base_dir 下
                    resolved_path.relative_to(resolved_base)
                    is_allowed = True
                    break
                except ValueError:
                    # resolved_path 不在 base_dir 下，继续检查
                    continue
            
            if not is_allowed:
                return (
                    False, 
                    str(resolved_path),
                    f"路径不在允许的目录范围内。允许的目录: {self.allowed_base_dirs}"
                )
            
            return True, str(resolved_path), ""
            
        except Exception as e:
            return False, "", f"路径解析失败: {str(e)}"
    
    def _detect_encoding(self, path: str) -> str:
        """
        检测文件编码
        
        尝试检测文件的文本编码。
        
        Args:
            path: 文件路径
            
        Returns:
            str: 检测到的编码，默认为 utf-8
        """
        encodings_to_try = ['utf-8', 'gbk', 'gb2312', 'utf-16', 'latin-1']
        
        for encoding in encodings_to_try:
            try:
                with open(path, 'r', encoding=encoding) as f:
                    f.read(1024)  # 尝试读取一小部分
                return encoding
            except UnicodeDecodeError:
                continue
        
        return 'utf-8'  # 默认使用 UTF-8
    
    def _check_file_size(self, path: str) -> tuple[bool, str]:
        """
        检查文件大小是否超出限制
        
        Args:
            path: 文件路径
            
        Returns:
            tuple: (是否通过, 错误信息)
        """
        try:
            file_size = os.path.getsize(path)
            if file_size > self.max_file_size:
                return False, (
                    f"文件大小 ({file_size} 字节) "
                    f"超出限制 ({self.max_file_size} 字节)"
                )
            return True, ""
        except OSError as e:
            return False, f"获取文件大小失败: {str(e)}"


class FileReadTool(BaseFileTool):
    """
    文件读取工具
    
    继承自 BaseFileTool，提供安全的文件读取功能。
    
    功能特性：
    - 路径安全验证
    - 自动检测文件编码
    - 支持分块读取大文件
    - 限制文件大小
    - 返回文件元信息
    
    属性：
        name: 工具名称，固定为 "file_read"
        description: 工具描述
    """
    
    def __init__(
        self,
        allowed_base_dirs: List[str] = None,
        max_file_size: int = 10 * 1024 * 1024,
        allow_full_paths: Optional[bool] = None,
    ):
        """
        初始化 FileReadTool
        
        Args:
            allowed_base_dirs: 允许访问的根目录列表
            max_file_size: 最大文件大小（字节）
            allow_full_paths: 是否允许访问整机任意绝对路径
        """
        super().__init__(
            allowed_base_dirs=allowed_base_dirs,
            max_file_size=max_file_size,
            allow_full_paths=allow_full_paths,
        )
        self._name = "file_read"
        self._description = "安全读取文件内容。支持文本文件和二进制文件读取，自动检测编码，返回文件元信息。"
        logger.info("[FileReadTool] 文件读取工具初始化完成")
    
    @property
    def name(self) -> str:
        """
        获取工具名称
        
        Returns:
            str: 工具名称，固定为 "file_read"
        """
        return self._name
    
    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema
        
        定义文件读取工具的参数规范：
        - path: 文件路径（必需）
        - encoding: 文本编码（可选，默认自动检测）
        - max_size: 最大读取大小（可选，默认 10MB）
        
        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读取的文件路径，支持绝对路径和相对路径"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，如 utf-8、gbk 等。设为 None 则自动检测",
                        "default": "auto"
                    },
                    "max_size": {
                        "type": "integer",
                        "description": "最大读取大小（字节），默认 10485760（10MB）",
                        "default": 10485760
                    }
                },
                "required": ["path"],
                "additionalProperties": False
            }
        )
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        读取文件内容
        
        读取指定路径的文件内容，返回文件数据和元信息。
        
        参数处理逻辑：
        1. 提取并验证 path 参数
        2. 验证路径安全性
        3. 检查文件是否存在
        4. 检测或使用指定编码
        5. 读取并返回内容
        
        Args:
            params: 参数字典，必须包含 "path" 键
            
        Returns:
            Dict[str, Any]: 读取结果，包含：
                - success: 是否成功
                - content: 文件内容（文本或二进制 base64）
                - encoding: 文件编码
                - size: 文件大小（字节）
                - path: 文件路径
                - error: 错误信息（失败时）
        """
        # ========== 参数提取阶段 ==========
        # 增加容错：LLM 可能会不按 schema 中的 "path" 传参，也许会传 "file_path", "filepath" 或 "file"
        path = params.get("path") or params.get("file_path") or params.get("filepath") or params.get("file") or ""
        encoding = params.get("encoding", "auto")
        max_size = params.get("max_size", self.max_file_size)
        
        # 打印详细中文日志，便于排查 LLM 到底传了什么参数
        logger.debug(f"[FileReadTool] 接收到原始参数 dict 结构: {params}")
        
        # 参数验证
        if not path:
            logger.warning("[FileReadTool] 文件路径为空，可能是 LLM 传递的参数名不匹配（未找到 path/file_path/filepath/file）。")
            return {
                "success": False,
                "error": "文件路径不能为空"
            }
        
        logger.info(f"{Fore.CYAN}[FileReadTool] 准备读取文件: {path}{Style.RESET_ALL}")
        
        # ========== 路径验证阶段 ==========
        is_valid, resolved_path, error_msg = self._validate_path(path)
        if not is_valid:
            logger.warning(f"[FileReadTool] 路径验证失败: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "path": path
            }
        
        # ========== 文件检查阶段 ==========
        # 检查文件是否存在
        if not os.path.exists(resolved_path):
            logger.warning(f"[FileReadTool] 文件不存在: {resolved_path}")
            return {
                "success": False,
                "error": f"文件不存在: {resolved_path}",
                "path": resolved_path
            }
        
        # 检查是否是文件
        if not os.path.isfile(resolved_path):
            logger.warning(f"[FileReadTool] 路径不是文件: {resolved_path}")
            return {
                "success": False,
                "error": f"路径不是文件: {resolved_path}",
                "path": resolved_path
            }
        
        # 检查文件大小
        is_valid, error_msg = self._check_file_size(resolved_path)
        if not is_valid:
            logger.warning(f"[FileReadTool] 文件大小检查失败: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "path": resolved_path
            }
        
        # ========== 文件读取阶段 ==========
        try:
            # 获取文件大小
            file_size = os.path.getsize(resolved_path)
            
            # 检测文件类型
            is_binary = self._is_binary_file(resolved_path)
            
            content = None
            detected_encoding = None
            
            if is_binary:
                # 二进制文件读取
                with open(resolved_path, 'rb') as f:
                    content = f.read()
                
                logger.info(
                    f"[FileReadTool] 成功读取二进制文件: {resolved_path}, "
                    f"大小: {file_size} 字节"
                )
                
                return {
                    "success": True,
                    "content": content,
                    "path": resolved_path,
                    "size": file_size,
                    "encoding": None,
                    "is_binary": True,
                    "mime_type": self._get_mime_type(resolved_path)
                }
            else:
                # 文本文件读取
                # 检测或使用指定编码
                if encoding == "auto":
                    detected_encoding = self._detect_encoding(resolved_path)
                    encoding_to_use = detected_encoding
                else:
                    detected_encoding = encoding
                    encoding_to_use = encoding
                
                # 读取文件内容
                with open(resolved_path, 'r', encoding=encoding_to_use) as f:
                    content = f.read()
                
                logger.info(
                    f"{Fore.GREEN}[FileReadTool] 成功读取文本文件: {resolved_path} "
                    f"| 编码={encoding_to_use} | 字符数={len(content)}{Style.RESET_ALL}"
                )
                
                return {
                    "success": True,
                    "content": content,
                    "path": resolved_path,
                    "size": file_size,
                    "encoding": detected_encoding,
                    "is_binary": False,
                    "line_count": content.count('\n') + 1 if content else 0
                }
                
        except PermissionError:
            logger.error(f"[FileReadTool] 无权限读取文件: {resolved_path}")
            return {
                "success": False,
                "error": "无权限读取该文件",
                "path": resolved_path
            }
            
        except UnicodeDecodeError as e:
            logger.error(f"[FileReadTool] 文件编码错误: {resolved_path}")
            return {
                "success": False,
                "error": f"文件编码错误，无法解码: {str(e)}",
                "path": resolved_path
            }
            
        except Exception as e:
            logger.exception(f"[FileReadTool] 读取文件失败: {str(e)}")
            return {
                "success": False,
                "error": f"读取文件失败: {str(e)}",
                "path": resolved_path
            }
    
    def _is_binary_file(self, path: str, chunk_size: int = 8192) -> bool:
        """
        判断文件是否为二进制文件
        
        通过检查文件开头的字节来判断是否为二进制文件。
        
        Args:
            path: 文件路径
            chunk_size: 读取的字节块大小
            
        Returns:
            bool: 是否为二进制文件
        """
        try:
            with open(path, 'rb') as f:
                chunk = f.read(chunk_size)
                
                # 检查是否有空字符（0x00），这是二进制文件的常见特征
                if b'\x00' in chunk:
                    return True
                
                # 检查是否大部分字节都是不可打印的
                non_printable = sum(1 for byte in chunk if byte < 32 and byte not in [9, 10, 13])
                if non_printable > len(chunk) * 0.3:
                    return True
                
                return False
                
        except Exception:
            # 如果无法判断，假设为文本文件
            return False
    
    def _get_mime_type(self, path: str) -> str:
        """
        获取文件的 MIME 类型
        
        Args:
            path: 文件路径
            
        Returns:
            str: MIME 类型
        """
        import mimetypes
        mime_type, _ = mimetypes.guess_type(path)
        return mime_type or 'application/octet-stream'


class FileWriteTool(BaseFileTool):
    """
    文件写入工具
    
    继承自 BaseFileTool，提供安全的文件写入功能。
    
    功能特性：
    - 路径安全验证
    - 自动创建父目录
    - 支持文本和二进制写入
    - 备份现有文件（可选）
    - 文件存在性检查
    
    属性：
        name: 工具名称，固定为 "file_write"
        description: 工具描述
    """
    
    def __init__(
        self,
        allowed_base_dirs: List[str] = None,
        max_file_size: int = 10 * 1024 * 1024,
        allow_full_paths: Optional[bool] = None,
    ):
        """
        初始化 FileWriteTool
        
        Args:
            allowed_base_dirs: 允许访问的根目录列表
            max_file_size: 最大文件大小（字节）
            allow_full_paths: 是否允许访问整机任意绝对路径
        """
        super().__init__(
            allowed_base_dirs=allowed_base_dirs,
            max_file_size=max_file_size,
            allow_full_paths=allow_full_paths,
        )
        self._name = "file_write"
        self._description = "安全写入文件内容。支持文本和二进制写入，自动创建父目录，可选择备份现有文件。"
        logger.info("[FileWriteTool] 文件写入工具初始化完成")
    
    @property
    def name(self) -> str:
        """
        获取工具名称
        
        Returns:
            str: 工具名称，固定为 "file_write"
        """
        return self._name
    
    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema
        
        定义文件写入工具的参数规范：
        - path: 文件路径（必需）
        - content: 要写入的内容（必需）
        - encoding: 文本编码（可选，默认 utf-8）
        - mode: 写入模式（可选，'w' 覆盖或 'a' 追加）
        - create_dirs: 是否自动创建父目录（可选，默认 True）
        - backup: 是否备份现有文件（可选，默认 False）
        
        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要写入的文件路径，支持绝对路径和相对路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的内容（文本）或 base64 编码的二进制数据"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，如 utf-8、gbk 等",
                        "default": "utf-8"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["w", "a", "x"],
                        "description": "写入模式: w(覆盖), a(追加), x(排他创建)",
                        "default": "w"
                    },
                    "create_dirs": {
                        "type": "boolean",
                        "description": "是否自动创建父目录",
                        "default": True
                    },
                    "backup": {
                        "type": "boolean",
                        "description": "写入前是否备份现有文件",
                        "default": False
                    },
                    "is_binary": {
                        "type": "boolean",
                        "description": "是否为二进制写入",
                        "default": False
                    }
                },
                "required": ["path", "content"],
                "additionalProperties": False
            }
        )
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        写入文件内容
        
        将内容写入指定路径的文件。
        
        参数处理逻辑：
        1. 提取并验证 path 和 content 参数
        2. 验证路径安全性
        3. 检查是否需要备份
        4. 创建父目录（如需要）
        5. 执行写入操作
        
        Args:
            params: 参数字典，必须包含 "path" 和 "content" 键
            
        Returns:
            Dict[str, Any]: 写入结果，包含：
                - success: 是否成功
                - path: 文件路径
                - size: 写入字节数
                - error: 错误信息（失败时）
        """
        # ========== 参数提取阶段 ==========
        # 增加参数容错与日志：LLM 返回的参数往往可能使用不同的命名
        logger.debug(f"[FileWriteTool] 接收到原始参数 dict 结构: 内部键包括 {list(params.keys())}")
        
        path = params.get("path") or params.get("file_path") or params.get("filepath") or params.get("file") or ""
        content = params.get("content") or params.get("text") or params.get("data")
        encoding = params.get("encoding", "utf-8")
        mode = params.get("mode", "w")
        create_dirs = params.get("create_dirs", True)
        backup = params.get("backup", False)
        is_binary = params.get("is_binary", False)
        
        # 参数验证
        if not path:
            logger.warning("[FileWriteTool] 文件路径为空，可能是 LLM 未正确传递 path/file_path 等字段。")
            return {
                "success": False,
                "error": "文件路径不能为空"
            }
        
        if content is None:
            logger.warning("[FileWriteTool] 文件内容为空")
            return {
                "success": False,
                "error": "文件内容不能为 None"
            }
        
        logger.info(f"{Fore.CYAN}[FileWriteTool] 准备写入文件: {path}{Style.RESET_ALL}")
        
        # ========== 路径验证阶段 ==========
        is_valid, resolved_path, error_msg = self._validate_path(path)
        if not is_valid:
            logger.warning(f"[FileWriteTool] 路径验证失败: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "path": path
            }
        
        # ========== 预处理阶段 ==========
        # 检查文件是否存在
        file_exists = os.path.exists(resolved_path)
        
        # 备份现有文件
        if file_exists and backup:
            backup_path = resolved_path + ".bak"
            try:
                os.rename(resolved_path, backup_path)
                logger.info(f"[FileWriteTool] 已备份文件到: {backup_path}")
            except Exception as e:
                logger.warning(f"[FileReadTool] 备份文件失败: {str(e)}")
        
        # 创建父目录
        parent_dir = os.path.dirname(resolved_path)
        if not os.path.exists(parent_dir):
            if create_dirs:
                try:
                    os.makedirs(parent_dir, exist_ok=True)
                    logger.info(f"[FileWriteTool] 已创建父目录: {parent_dir}")
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"无法创建父目录: {str(e)}",
                        "path": resolved_path
                    }
            else:
                return {
                    "success": False,
                    "error": f"父目录不存在: {parent_dir}",
                    "path": resolved_path
                }
        
        # 检查文件大小限制
        if is_binary and isinstance(content, str):
            # 如果是 base64 编码的内容，先解码检查大小
            try:
                import base64
                binary_content = base64.b64decode(content)
                if len(binary_content) > self.max_file_size:
                    return {
                        "success": False,
                        "error": f"内容大小超出限制",
                        "path": resolved_path
                    }
            except Exception:
                pass
        elif not is_binary and isinstance(content, str):
            if len(content.encode(encoding)) > self.max_file_size:
                return {
                    "success": False,
                    "error": f"内容大小超出限制",
                    "path": resolved_path
                }
        
        # ========== 文件写入阶段 ==========
        try:
            # 检查写入模式
            if mode == "x" and file_exists:
                return {
                    "success": False,
                    "error": f"文件已存在，无法使用排他创建模式: {resolved_path}",
                    "path": resolved_path
                }
            
            # 确定文件打开模式
            if is_binary:
                file_mode = "wb" if mode != "a" else "ab"
                # 如果是二进制模式但 content 是字符串，假设是 base64
                if isinstance(content, str):
                    import base64
                    content = base64.b64decode(content)
            else:
                file_mode = "w" if mode != "a" else "a"
                if isinstance(content, bytes):
                    content = content.decode(encoding)
            
            # 执行写入
            with open(resolved_path, file_mode, encoding=encoding if not is_binary else None) as f:
                bytes_written = f.write(content)
            
            logger.info(
                f"{Fore.GREEN}[FileWriteTool] 成功写入文件: {resolved_path} "
                f"| 写入={bytes_written}字节{Style.RESET_ALL}"
            )
            
            return {
                "success": True,
                "path": resolved_path,
                "bytes_written": bytes_written,
                "mode": mode,
                "is_binary": is_binary
            }
            
        except PermissionError:
            logger.error(f"[FileWriteTool] 无权限写入文件: {resolved_path}")
            return {
                "success": False,
                "error": "无权限写入该文件",
                "path": resolved_path
            }
            
        except OSError as e:
            logger.exception(f"[FileWriteTool] 写入文件失败: {str(e)}")
            return {
                "success": False,
                "error": f"写入文件失败: {str(e)}",
                "path": resolved_path
            }
            
        except Exception as e:
            logger.exception(f"[FileWriteTool] 写入文件发生未知错误: {str(e)}")
            return {
                "success": False,
                "error": f"写入文件失败: {str(e)}",
                "path": resolved_path
            }


# ============================================================
# 便捷函数：快速文件操作
# ============================================================

async def quick_read(path: str, encoding: str = "auto") -> Dict[str, Any]:
    """
    便捷文件读取函数
    
    Args:
        path: 文件路径
        encoding: 编码
        
    Returns:
        Dict[str, Any]: 读取结果
    """
    tool = FileReadTool()
    return await tool.execute({"path": path, "encoding": encoding})


async def quick_write(path: str, content: str, 
                      encoding: str = "utf-8") -> Dict[str, Any]:
    """
    便捷文件写入函数
    
    Args:
        path: 文件路径
        content: 写入内容
        encoding: 编码
        
    Returns:
        Dict[str, Any]: 写入结果
    """
    tool = FileWriteTool()
    return await tool.execute({
        "path": path, 
        "content": content, 
        "encoding": encoding
    })


# ============================================================
# 文件操作结果格式化
# ============================================================

def format_file_result(result: Dict[str, Any], 
                       preview_length: int = 200) -> str:
    """
    格式化文件操作结果为可读文本
    
    Args:
        result: 操作结果字典
        preview_length: 预览内容最大长度
        
    Returns:
        str: 格式化后的结果文本
    """
    if not result.get("success"):
        return f"❌ 操作失败: {result.get('error', '未知错误')}"
    
    lines = []
    lines.append("✅ 操作成功")
    lines.append(f"文件路径: {result.get('path', 'N/A')}")
    
    if 'size' in result:
        lines.append(f"文件大小: {result['size']} 字节")
    
    if 'bytes_written' in result:
        lines.append(f"写入字节: {result['bytes_written']}")
    
    if 'encoding' in result and result['encoding']:
        lines.append(f"文件编码: {result['encoding']}")
    
    if 'line_count' in result:
        lines.append(f"行数: {result['line_count']}")
    
    if 'content' in result and result['content']:
        content = result['content']
        if isinstance(content, bytes):
            content = f"<二进制数据: {len(content)} 字节>"
        else:
            if len(content) > preview_length:
                content = content[:preview_length] + "..."
        lines.append("")
        lines.append("内容预览:")
        lines.append(content)
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# FileEditTool：文本精准替换
# 移植并增强自 filesystem.py 的 EditFileTool 设计
# ═══════════════════════════════════════════════════════════════

class FileEditTool(BaseFileTool):
    """
    文件文本精准替换工具

    移植自 filesystem.py 的 EditFileTool，并增强了以下能力：
    - 路径安全验证（复用 BaseFileTool._validate_path）
    - 重复匹配检测：若 old_text 在文件中出现多次，则拒绝替换并给出提示
      （防止误替换错误位置，保证操作幂等性）
    - 精准单次替换（replace(..., 1)）
    - 替换前后字符数对比，便于调试
    - colorama 彩色日志分层记录

    属性：
        name: 工具名称，固定为 "file_edit"
        description: 工具描述
    """

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
        self._name        = "file_edit"
        self._description = (
            "精准编辑文件内容：将文件中的 old_text 替换为 new_text。"
            "old_text 必须在文件中精确存在且唯一，否则操作将被拒绝。"
        )
        logger.info(
            f"{Fore.CYAN}[FileEditTool] 文件精准编辑工具初始化完成{Style.RESET_ALL}"
        )

    @property
    def name(self) -> str:
        """获取工具名称（固定为 "file_edit"）"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema

        参数规范：
        - path:     文件路径（必需）
        - old_text: 要被替换的精确文本（必需）
        - new_text: 替换后的新文本（必需）
        - encoding: 文件编码（可选，默认 utf-8）
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type":        "string",
                        "description": "要编辑的文件路径"
                    },
                    "old_text": {
                        "type":        "string",
                        "description": "要被替换的精确文本（必须在文件中唯一存在）"
                    },
                    "new_text": {
                        "type":        "string",
                        "description": "替换后的新文本内容"
                    },
                    "encoding": {
                        "type":        "string",
                        "description": "文件编码，默认 utf-8",
                        "default":     "utf-8"
                    }
                },
                "required":             ["path", "old_text", "new_text"],
                "additionalProperties": False
            }
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行文本精准替换

        执行流程：
        1. 参数提取与非空校验
        2. 路径安全验证
        3. 检查文件存在性
        4. 读取文件内容
        5. 检测 old_text 出现次数（0 次 → 报错；多次 → 拒绝并提示）
        6. 精准替换首次出现的 old_text（replace(..., 1)）
        7. 写回文件

        Args:
            params: 参数字典，必须包含 path / old_text / new_text

        Returns:
            Dict[str, Any]: 替换结果，包含：
                - success:       是否成功
                - path:          文件路径
                - replaced:      是否执行了替换
                - chars_before:  替换前文件字符数
                - chars_after:   替换后文件字符数
                - error:         错误信息（失败时存在）
        """
        # ═══ 参数提取 ═══
        logger.debug(
            f"{Fore.CYAN}[FileEditTool] 接收到参数: {list(params.keys())}{Style.RESET_ALL}"
        )
        path     = params.get("path", "")
        old_text = params.get("old_text")
        new_text = params.get("new_text")
        encoding = params.get("encoding", "utf-8")

        # ─── 非空校验 ───
        if not path:
            logger.warning(
                f"{Fore.YELLOW}[FileEditTool] 文件路径为空{Style.RESET_ALL}"
            )
            return {"success": False, "error": "文件路径不能为空"}
        if old_text is None:
            return {"success": False, "error": "old_text 不能为空"}
        if new_text is None:
            return {"success": False, "error": "new_text 不能为空"}

        logger.info(
            f"{Fore.CYAN}[FileEditTool] 准备编辑文件: {path} "
            f"| old_text 长度={len(old_text)}{Style.RESET_ALL}"
        )

        # ═══ 路径安全验证 ═══
        is_valid, resolved_path, error_msg = self._validate_path(path)
        if not is_valid:
            logger.warning(
                f"{Fore.YELLOW}[FileEditTool] 路径验证失败: {error_msg}{Style.RESET_ALL}"
            )
            return {"success": False, "error": error_msg, "path": path}

        # ═══ 文件存在性检查 ═══
        if not os.path.exists(resolved_path):
            logger.warning(
                f"{Fore.YELLOW}[FileEditTool] 文件不存在: {resolved_path}{Style.RESET_ALL}"
            )
            return {"success": False, "error": f"文件不存在: {resolved_path}", "path": resolved_path}
        if not os.path.isfile(resolved_path):
            return {"success": False, "error": f"路径不是文件: {resolved_path}", "path": resolved_path}

        try:
            # ═══ 读取文件内容 ═══
            with open(resolved_path, "r", encoding=encoding) as f:
                original_content = f.read()

            chars_before = len(original_content)

            # ─── 检测 old_text 出现次数（核心安全逻辑，来自 filesystem.py）───
            count = original_content.count(old_text)

            if count == 0:
                # old_text 根本不存在，报告错误
                logger.warning(
                    f"{Fore.YELLOW}[FileEditTool] old_text 在文件中未找到，"
                    f"请检查是否精确匹配（包括空白和换行）{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error":   "old_text 在文件中不存在，请确保内容完全匹配（包括空格和换行符）",
                    "path":    resolved_path
                }

            if count > 1:
                # NOTE: 多次出现时拒绝替换，防止歧义操作破坏文件（移植自 filesystem.py 的安全设计）
                logger.warning(
                    f"{Fore.YELLOW}[FileEditTool] old_text 在文件中出现了 {count} 次，"
                    f"请提供更多上下文使其唯一{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error":   f"old_text 在文件中出现了 {count} 次，请提供更多上下文使目标文本唯一",
                    "path":    resolved_path,
                    "count":   count
                }

            # ═══ 精准替换（首次且唯一的出现）═══
            new_content  = original_content.replace(old_text, new_text, 1)
            chars_after  = len(new_content)

            with open(resolved_path, "w", encoding=encoding) as f:
                f.write(new_content)

            logger.info(
                f"{Fore.GREEN}[FileEditTool] 替换成功: {resolved_path} "
                f"| 字符数 {chars_before} → {chars_after}{Style.RESET_ALL}"
            )
            return {
                "success":      True,
                "path":         resolved_path,
                "replaced":     True,
                "chars_before": chars_before,
                "chars_after":  chars_after
            }

        except PermissionError:
            logger.error(
                f"{Fore.RED}[FileEditTool] 无权限操作文件: {resolved_path}{Style.RESET_ALL}"
            )
            return {"success": False, "error": "无权限操作该文件", "path": resolved_path}
        except UnicodeDecodeError as e:
            logger.error(
                f"{Fore.RED}[FileEditTool] 文件编码错误: {e}{Style.RESET_ALL}"
            )
            return {"success": False, "error": f"文件编码错误: {e}", "path": resolved_path}
        except Exception as e:
            logger.exception(
                f"{Fore.RED}[FileEditTool] 编辑文件失败: {e}{Style.RESET_ALL}"
            )
            return {"success": False, "error": f"编辑文件失败: {e}", "path": resolved_path}


# ═══════════════════════════════════════════════════════════════
# FileListDirTool：目录内容列表
# 移植并增强自 filesystem.py 的 ListDirTool 设计
# ═══════════════════════════════════════════════════════════════

class FileListDirTool(BaseFileTool):
    """
    目录内容列表工具

    移植自 filesystem.py 的 ListDirTool，并增强了：
    - 路径安全验证（复用 BaseFileTool._validate_path）
    - 显示文件大小（字节）
    - 显示子目录内的文件/子目录数量
    - emoji 前缀区分文件（📄）和目录（📁）
    - 支持是否显示隐藏文件（默认不显示 . 开头的文件）
    - colorama 彩色日志

    属性：
        name: 工具名称，固定为 "list_dir"
        description: 工具描述
    """

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
        self._name        = "list_dir"
        self._description = "列出目录内容，显示文件和子目录列表，包含大小和条目数信息。"
        logger.info(
            f"{Fore.CYAN}[FileListDirTool] 目录列表工具初始化完成{Style.RESET_ALL}"
        )

    @property
    def name(self) -> str:
        """获取工具名称（固定为 "list_dir"）"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema

        参数规范：
        - path:         目录路径（必需）
        - show_hidden:  是否显示隐藏文件（默认 False）
        - show_size:    是否显示文件大小（默认 True）
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type":        "string",
                        "description": "要列出内容的目录路径（绝对或相对路径）"
                    },
                    "show_hidden": {
                        "type":        "boolean",
                        "description": "是否显示隐藏文件（以 . 开头），默认 false",
                        "default":     False
                    },
                    "show_size": {
                        "type":        "boolean",
                        "description": "是否显示文件大小，默认 true",
                        "default":     True
                    }
                },
                "required":             ["path"],
                "additionalProperties": False
            }
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        列出目录内容

        执行流程：
        1. 参数提取与路径安全验证
        2. 目录存在性检查
        3. 遍历目录条目，按名称排序
        4. 返回结构化列表（含 emoji 前缀、大小/数量信息）

        Args:
            params: 参数字典，必须包含 path

        Returns:
            Dict[str, Any]: 目录列表结果，包含：
                - success:     是否成功
                - path:        目录路径
                - items:       条目列表（每项含 name/type/size/count/formatted）
                - total_count: 总条目数
                - summary:     格式化摘要文本
                - error:       错误信息（失败时存在）
        """
        # ═══ 参数提取 ═══
        path        = params.get("path", "")
        show_hidden = params.get("show_hidden", False)
        show_size   = params.get("show_size",   True)

        if not path:
            logger.warning(
                f"{Fore.YELLOW}[FileListDirTool] 目录路径为空{Style.RESET_ALL}"
            )
            return {"success": False, "error": "目录路径不能为空"}

        logger.info(
            f"{Fore.CYAN}[FileListDirTool] 列举目录: {path} "
            f"| 显示隐藏={show_hidden}{Style.RESET_ALL}"
        )

        # ═══ 路径安全验证 ═══
        is_valid, resolved_path, error_msg = self._validate_path(path)
        if not is_valid:
            logger.warning(
                f"{Fore.YELLOW}[FileListDirTool] 路径验证失败: {error_msg}{Style.RESET_ALL}"
            )
            return {"success": False, "error": error_msg, "path": path}

        # ═══ 目录存在性检查 ═══
        dir_path = Path(resolved_path)
        if not dir_path.exists():
            return {"success": False, "error": f"目录不存在: {resolved_path}", "path": resolved_path}
        if not dir_path.is_dir():
            return {"success": False, "error": f"路径不是目录: {resolved_path}", "path": resolved_path}

        try:
            items      = []
            formatted_lines = []

            # 遍历目录，按名称排序（目录在前）
            all_entries = sorted(
                dir_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower())
            )

            for entry in all_entries:
                # 默认过滤隐藏文件（以 . 开头）
                if not show_hidden and entry.name.startswith("."):
                    continue

                if entry.is_dir():
                    # 统计子目录内的条目数
                    try:
                        sub_count = sum(1 for _ in entry.iterdir())
                    except PermissionError:
                        sub_count = -1  # 无权限访问时标记为 -1

                    item = {
                        "name":      entry.name,
                        "type":      "directory",
                        "count":     sub_count,
                        "formatted": f"📁 {entry.name}/  ({sub_count} 项)" if sub_count >= 0
                                     else f"📁 {entry.name}/  (无权限)"
                    }
                else:
                    # 获取文件大小
                    try:
                        size = entry.stat().st_size
                        size_str = _format_size(size) if show_size else ""
                    except OSError:
                        size     = -1
                        size_str = "未知"

                    item = {
                        "name":      entry.name,
                        "type":      "file",
                        "size":      size,
                        "formatted": f"📄 {entry.name}  {size_str}" if show_size
                                     else f"📄 {entry.name}"
                    }

                items.append(item)
                formatted_lines.append(item["formatted"])

            # ─── 生成汇总摘要 ───
            dir_count  = sum(1 for i in items if i["type"] == "directory")
            file_count = sum(1 for i in items if i["type"] == "file")
            summary_header = f"目录: {resolved_path}  ({dir_count} 个子目录，{file_count} 个文件)"

            if not items:
                summary = f"{summary_header}\n（目录为空）"
            else:
                summary = summary_header + "\n" + "\n".join(formatted_lines)

            logger.info(
                f"{Fore.GREEN}[FileListDirTool] 目录列举完成: {resolved_path} "
                f"| 子目录={dir_count} 文件={file_count}{Style.RESET_ALL}"
            )

            return {
                "success":     True,
                "path":        resolved_path,
                "items":       items,
                "total_count": len(items),
                "dir_count":   dir_count,
                "file_count":  file_count,
                "summary":     summary
            }

        except PermissionError:
            logger.error(
                f"{Fore.RED}[FileListDirTool] 无权限访问目录: {resolved_path}{Style.RESET_ALL}"
            )
            return {"success": False, "error": "无权限访问该目录", "path": resolved_path}
        except Exception as e:
            logger.exception(
                f"{Fore.RED}[FileListDirTool] 目录列举失败: {e}{Style.RESET_ALL}"
            )
            return {"success": False, "error": f"目录列举失败: {e}", "path": resolved_path}


def _format_size(size_bytes: int) -> str:
    """
    将字节数格式化为可读的大小字符串

    Args:
        size_bytes: 文件字节数

    Returns:
        str: 如 "1.2 KB"、"3.5 MB" 等
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024 ** 2:.1f} MB"
    else:
        return f"{size_bytes / 1024 ** 3:.1f} GB"


# ══════════════════════════════════════════════════
# 新增便捷函数
# ══════════════════════════════════════════════════

async def quick_edit(
    path: str,
    old_text: str,
    new_text: str,
    encoding: str = "utf-8"
) -> Dict[str, Any]:
    """
    便捷文件编辑函数

    Args:
        path:     文件路径
        old_text: 待替换的精确文本
        new_text: 替换后的新文本
        encoding: 文件编码

    Returns:
        Dict[str, Any]: 编辑结果
    """
    tool = FileEditTool()
    return await tool.execute({
        "path":     path,
        "old_text": old_text,
        "new_text": new_text,
        "encoding": encoding
    })


async def quick_listdir(
    path: str,
    show_hidden: bool = False
) -> Dict[str, Any]:
    """
    便捷目录列表函数

    Args:
        path:        目录路径
        show_hidden: 是否显示隐藏文件

    Returns:
        Dict[str, Any]: 目录列表结果
    """
    tool = FileListDirTool()
    return await tool.execute({"path": path, "show_hidden": show_hidden})
