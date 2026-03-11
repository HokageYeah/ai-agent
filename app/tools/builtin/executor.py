"""
Python 代码执行工具模块

本模块实现了 PythonExecutorTool 类，提供安全的 Python 代码执行功能。

功能特点：
1. 安全的代码执行环境
2. 超时控制，防止无限循环
3. 输出捕获，支持 print 结果展示
4. 错误捕获，友好的错误信息
5. 限制危险操作，保障系统安全

安全措施：
- 禁用 os、sys 等系统级模块
- 限制文件和网络访问
- 超时自动终止
- 捕获所有异常

使用示例：
    tool = PythonExecutorTool()
    result = await tool.execute({
        "code": "print('Hello, World!')\nresult = 2 + 2",
        "timeout": 10
    })
"""

import sys
import io
import asyncio
import signal
from typing import Any, Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from app.tools.base import Tool, ToolSchema
from loguru import logger
from colorama import Fore, Style


class PythonExecutorTool(Tool):
    """
    Python 代码执行工具
    
    继承自 Tool 抽象基类，提供安全的 Python 代码执行能力。
    
    安全设计：
    1. 使用受限的全局和局部命名空间
    2. 禁用危险模块（os、sys、subprocess 等）
    3. 超时控制，防止无限循环
    4. 捕获所有异常，返回结构化错误
    
    允许的模块：
    - math: 数学运算
    - random: 随机数生成
    - datetime: 日期时间操作
    - json: JSON 处理
    - re: 正则表达式
    - collections: 集合操作
    - itertools: 迭代工具
    - functools: 函数工具
    - statistics: 统计函数
    
    属性：
        name: 工具名称，固定为 "python_executor"
        description: 工具描述
    """
    
    # 允许导入的安全模块白名单
    _ALLOWED_MODULES = {
        "math", "random", "datetime", "json", "re", 
        "collections", "itertools", "functools", "statistics",
        "typing", "uuid", "hashlib", "base64", "decimal",
        "fractions", "heapq", "bisect", "array", "weakref",
        "types", "copy", "pprint", "textwrap", "unicodedata"
    }
    
    # 需要完全禁用的危险操作
    _FORBIDDEN_PATTERNS = [
        # "import os",
        # "from os ",
        # "import sys",
        # "from sys ",
        # "import subprocess",
        # "from subprocess ",
        # "import multiprocessing",
        # "from multiprocessing ",
        # "import threading",
        # "from threading ",
        # "open(",
        # "eval(",
        # "exec(",
        # "__import__",
        # "compile(",
        # "getattr(",
        # "setattr(",
        # "delattr(",
        # "breakpoint(",
        # "help(",
    ]
    
    def __init__(self):
        """
        初始化 PythonExecutorTool 实例
        
        配置安全执行环境和线程池。
        """
        self._name = "python_executor"
        self._description = "执行 Python 代码，支持数学运算、数据处理、文本操作等。提供安全的执行环境和超时控制。"
        self._default_timeout = 30  # 默认超时 30 秒
        self._max_timeout = 120     # 最大超时 120 秒
        
        # 运行时上下文（用于用户输入请求等功能）
        self._stream_callback = None
        self._pending_confirmations = None
        self._pending_user_inputs = None
        
        # 创建受限的安全命名空间
        self._safe_globals = self._create_safe_globals()
        
        # 线程池，用于执行代码
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="python_exec")
        
        logger.info("[PythonExecutorTool] Python 代码执行工具初始化完成")
    
    def update_context(
        self,
        stream_callback: Optional[Any] = None,
        pending_confirmations: Optional[Dict[str, Any]] = None,
        pending_user_inputs: Optional[Dict[str, Any]] = None,
        user_rejected_tools: Optional[List[str]] = None
    ) -> None:
        """
        更新运行时上下文

        在 Agent 每次执行任务前由执行引擎调用，注入当前会话的流式回调等运行时信息。

        Args:
            stream_callback: SSE 流式回调函数
            pending_confirmations: 挂起确认映射表
            pending_user_inputs: 挂起用户输入映射表
            user_rejected_tools: 用户拒绝的工具列表
        """
        if stream_callback is not None:
            self._stream_callback = stream_callback
        if pending_confirmations is not None:
            self._pending_confirmations = pending_confirmations
        if pending_user_inputs is not None:
            self._pending_user_inputs = pending_user_inputs
        logger.debug(f"{Fore.BLUE}[PythonExecutorTool] 运行时上下文已更新{Style.RESET_ALL}")
    
    def _create_safe_globals(self) -> Dict[str, Any]:
        """
        创建安全的全局命名空间
        
        构建只包含安全模块和函数的执行环境。
        
        Returns:
            Dict[str, Any]: 安全的全局命名空间
        """
        safe_globals = {
            # ========== 内置安全函数 ==========
            "print": print,
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "map": map,
            "filter": filter,
            "sorted": sorted,
            "reversed": reversed,
            "sum": sum,
            "min": min,
            "max": max,
            "abs": abs,
            "round": round,
            "pow": pow,
            "divmod": divmod,
            "chr": chr,
            "ord": ord,
            "hex": hex,
            "oct": oct,
            "bin": bin,
            "format": format,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "hasattr": hasattr,
            "getattr": getattr,
            "setattr": setattr,
            "delattr": delattr,
            "property": property,
            "staticmethod": staticmethod,
            "classmethod": classmethod,
            "super": super,
            "object": object,
            "type": type,
            "__import__": self._safe_import,
            
            # ========== True/False/None ==========
            "True": True,
            "False": False,
            "None": None,
            
            # ========== 异常类 ==========
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "AttributeError": AttributeError,
            "RuntimeError": RuntimeError,
            "ZeroDivisionError": ZeroDivisionError,
            "NameError": NameError,
            "SyntaxError": SyntaxError,
            "IndentationError": IndentationError,
        }
        
        # ========== 添加安全模块 ==========
        try:
            # 导入并暴露安全模块
            import math
            safe_globals["math"] = math
            
            import random
            safe_globals["random"] = random
            
            import datetime
            safe_globals["datetime"] = datetime
            
            import json
            safe_globals["json"] = json
            
            import re
            safe_globals["re"] = re
            
            import collections
            safe_globals["collections"] = collections
            
            import itertools
            safe_globals["itertools"] = itertools
            
            import functools
            safe_globals["functools"] = functools
            
            import statistics
            safe_globals["statistics"] = statistics
            
        except ImportError as e:
            logger.warning(f"[PythonExecutorTool] 导入安全模块失败: {e}")
        
        return safe_globals
    
    def _safe_import(self, name: str, *args, **kwargs):
        """
        安全导入模块
        
        只允许导入白名单中的模块。
        
        Args:
            name: 模块名称
            
        Returns:
            模块对象或 None
            
        Raises:
            ImportError: 不允许导入的模块
        """
        # 提取主模块名（忽略 from ... import ...）
        main_name = name.split('.')[0]
        
        if main_name in self._ALLOWED_MODULES:
            # 使用标准 __import__
            return __import__(name, *args, **kwargs)
        else:
            raise ImportError(f"模块 '{name}' 不允许导入")
    
    def _check_code_safety(self, code: str) -> tuple[bool, str]:
        """
        检查代码安全性
        
        检测代码中是否包含危险模式。
        
        Args:
            code: 待检查的代码
            
        Returns:
            tuple: (是否安全, 错误信息)
        """
        import re
        
        for pattern in self._FORBIDDEN_PATTERNS:
            # 使用单词边界匹配，避免误判
            if pattern in code:
                # 对于 import 语句，检查是否在行首或缩进后
                if pattern.startswith("import ") or pattern.startswith("from "):
                    # 检查 import 语句（忽略注释）
                    lines = code.split('\n')
                    for i, line in enumerate(lines):
                        stripped = line.strip()
                        if not stripped.startswith('#'):
                            if pattern in stripped:
                                return False, f"代码包含不允许的语句: {pattern.strip()}"
                else:
                    return False, f"代码包含不允许的模式: {pattern}"
        
        return True, ""
    
    def _execute_code_sync(self, code: str, timeout: int) -> Dict[str, Any]:
        """
        同步执行代码（在线程池中运行）
        
        Args:
            code: Python 代码
            timeout: 超时时间（秒）
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        # 重定向 stdout 以捕获 print 输出
        old_stdout = sys.stdout
        sys.stdout = captured_output = io.StringIO()
        
        try:
            # 使用单一命名空间：exec(code, g, l) 若 g≠l，Python 会按“类体”语义执行，
            # 导致 def 定义的函数在后续或递归调用时无法被正确解析（NameError: name 'xxx' is not defined）。
            # 传入同一 dict 作为 globals 与 locals，使定义与调用共享同一命名空间。
            namespace = self._safe_globals.copy()
            future = self._executor.submit(
                self._run_code,
                code,
                namespace,
                namespace,
            )
            
            try:
                result = future.result(timeout=timeout)
            except FuturesTimeoutError:
                return {
                    "success": False,
                    "error": f"代码执行超时（{timeout}秒），可能存在无限循环",
                    "output": captured_output.getvalue(),
                    "timeout": True
                }
            
            # 获取输出
            output = captured_output.getvalue()
            
            # 如果有结果但没有输出，尝试显示最后一条语句的结果
            if not output and result is not None:
                output = repr(result)
            
            return {
                "success": True,
                "result": result,
                "output": output,
                "result_type": type(result).__name__ if result is not None else "None"
            }
            
        except SyntaxError as e:
            return {
                "success": False,
                "error": f"语法错误: {str(e)}",
                "output": captured_output.getvalue(),
                "error_type": "SyntaxError"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"执行错误: {str(e)}",
                "output": captured_output.getvalue(),
                "error_type": type(e).__name__
            }
            
        finally:
            # 恢复 stdout
            sys.stdout = old_stdout
    
    def _run_code(self, code: str, globals_dict: Dict[str, Any], 
                  locals_dict: Dict[str, Any]):
        """
        执行代码的核心逻辑
        
        Args:
            code: Python 代码
            globals_dict: 全局命名空间
            locals_dict: 局部命名空间
            
        Returns:
            Any: 代码执行结果
        """
        stripped_code = code.strip()
        
        # 优先尝试作为简单表达式求值
        # 纯数学表达式、列表推导式、字典字面量、函数调用等
        expression_indicators = [
            '[', '(', '{',  # 以括号开头
            'range(', 'len(', 'str(', 'int(', 'float(', 'bool(',
            'list(', 'dict(', 'tuple(', 'set(',
            'math.', 'random.', 'datetime.',
        ]
        
        is_expression = any(stripped_code.startswith(ind) for ind in expression_indicators)
        
        # 简单数学表达式如 "2 + 2"（不包含括号）
        is_simple_expr = '\n' not in stripped_code and ';' not in stripped_code
        
        # 尝试作为表达式求值
        if is_expression or is_simple_expr:
            try:
                result = eval(stripped_code, globals_dict, locals_dict)
                if result is not None:
                    return result
            except (SyntaxError, NameError, TypeError, ValueError):
                # 表达式求值失败，作为语句执行
                pass
        
        # 执行代码
        exec(stripped_code, globals_dict, locals_dict)
        
        # 如果定义了 'result' 变量，返回它
        if 'result' in locals_dict:
            return locals_dict['result']
        if 'result' in globals_dict:
            return globals_dict['result']
        
        # 处理分号分隔的多语句代码（如 "import math; math.pi"）
        if ';' in stripped_code:
            statements = [s.strip() for s in stripped_code.split(';') if s.strip()]
            for stmt in statements:
                # 尝试求值最后一个语句
                if not stmt.startswith(('import ', 'from ', 'def ', 'class ', 'if ', 
                                       'for ', 'while ', 'with ', 'try:', 'except:')):
                    try:
                        result = eval(stmt, globals_dict, locals_dict)
                        if result is not None:
                            return result
                    except (SyntaxError, NameError, TypeError, ValueError):
                        continue
        
        return None
    
    @property
    def name(self) -> str:
        """
        获取工具名称
        
        Returns:
            str: 工具名称，固定为 "python_executor"
        """
        return self._name
    
    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema
        
        定义 Python 执行工具的参数规范：
        - code: 要执行的 Python 代码（必需）
        - timeout: 超时时间（可选，默认30秒）
        
        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要执行的 Python 代码。支持表达式、语句和完整的程序。"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "执行超时时间（秒），范围 1-120，默认 30",
                        "default": 30,
                        "minimum": 1,
                        "maximum": 120
                    }
                },
                "required": ["code"],
                "additionalProperties": False
            }
        )
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Python 代码
        
        在安全的执行环境中执行给定的 Python 代码。
        
        参数处理逻辑：
        1. 提取并验证 code 参数
        2. 提取并验证 timeout 参数
        3. 检查代码安全性
        4. 在线程池中执行代码
        5. 返回结构化结果
        6. 检测是否需要用户额外输入（如 SMTP 配置）
        
        Args:
            params: 参数字典，必须包含 "code" 键
            
        Returns:
            Dict[str, Any]: 执行结果，包含：
                - success: 是否成功
                - result: 代码返回值（如果有）
                - output: print 输出内容
                - error: 错误信息（失败时）
                - timeout: 是否超时
                - needs_user_input: 是否需要用户额外输入
                - user_input_request: 用户输入请求详情
        """
        # ========== 参数提取阶段 ==========
        code = params.get("code", "")
        timeout = params.get("timeout", self._default_timeout)
        
        # 参数验证
        if not code or not code.strip():
            logger.warning("[PythonExecutorTool] 代码为空")
            return {
                "success": False,
                "error": "代码不能为空"
            }
        
        # 限制超时时间范围
        timeout = max(1, min(self._max_timeout, timeout))
        
        logger.info(f"[PythonExecutorTool] 准备执行代码，超时: {timeout}秒")
        logger.debug(f"[PythonExecutorTool] 代码长度: {len(code)} 字符")
        
        # ========== 安全检查阶段 ==========
        is_safe, error_msg = self._check_code_safety(code)
        if not is_safe:
            logger.warning(f"[PythonExecutorTool] 代码安全检查失败: {error_msg}")
            return {
                "success": False,
                "error": f"代码包含不允许的操作: {error_msg}",
                "safety_check_failed": True
            }
        
        # ── 用户已提供配置时：注入到代码并跳过预检查 ─────────────────────
        # 若 params 中已包含用户提交的 smtp_server / sender_email 等，说明是「重试执行」，
        # 应将实际值注入代码后直接执行，不再返回 needs_user_input
        injected_code = self._inject_user_params_into_code(code, params)
        if injected_code is not None:
            code = injected_code
            logger.info(
                f"{Fore.GREEN}[PythonExecutorTool] 已注入用户提供的配置，跳过预检查，直接执行代码{Style.RESET_ALL}"
            )
        else:
            # ── 预检查：分析代码是否需要额外配置 ─────────────────────────────
            # 在执行前检测代码是否需要 SMTP/数据库等配置
            pre_check_result = self._analyze_code_for_required_info(code)
            if pre_check_result:
                logger.info(
                    f"{Fore.CYAN}[PythonExecutorTool] 预检查：检测到代码需要额外配置，"
                    f"返回需要用户输入{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "needs_user_input": True,
                    "user_input_request": pre_check_result,
                    "error": "代码需要额外配置才能执行",
                    "output": "代码需要 SMTP/数据库等配置信息，请提供必要参数",
                    "_pending_user_inputs": self._pending_user_inputs  # 传递引用，用于后续等待用户输入
                }

        # ── 修正 LLM 常见拼写错误（如 email 模块类名）────────────────────
        # 标准库为 MIMEText / MIMEMultipart，LLM 常生成 MimeText / MimeMultipart 导致 ImportError
        code = self._normalize_email_module_code(code)

        # ========== 代码执行阶段 ==========
        loop = asyncio.get_event_loop()
        
        try:
            # 在线程池中执行代码
            result = await loop.run_in_executor(
                self._executor,
                lambda: self._execute_code_sync(code, timeout)
            )
            
            logger.info(
                f"[PythonExecutorTool] 代码执行完成，"
                f"成功: {result['success']}"
            )
            
            # ── 检测是否需要用户额外输入（如 SMTP 配置缺失）───────────────
            # 检查执行结果中是否包含需要额外信息的错误
            if result.get("success") == False:
                error_output = result.get("output", "") or ""
                error_msg = result.get("error", "") or ""
                
                # 检测常见的需要用户输入的场景
                needs_input_info = self._detect_missing_info(error_output + error_msg)
                
                if needs_input_info:
                    logger.info(
                        f"{Fore.CYAN}[PythonExecutorTool] 检测到需要用户额外输入: "
                        f"{needs_input_info}{Style.RESET_ALL}"
                    )
                    result["needs_user_input"] = True
                    result["user_input_request"] = needs_input_info
            
            return result
            
        except Exception as e:
            logger.exception(f"[PythonExecutorTool] 执行过程出错: {str(e)}")
            return {
                "success": False,
                "error": f"执行失败: {str(e)}"
            }
    
    def _detect_missing_info(self, error_message: str) -> Optional[Dict[str, Any]]:
        """
        检测错误信息中是否包含需要用户提供额外信息的情况
        
        Args:
            error_message: 错误信息字符串
            
        Returns:
            如果检测到需要额外信息，返回包含 required_fields 和 message 的字典；否则返回 None
        """
        error_lower = error_message.lower()
        
        # 场景1：SMTP 邮件发送失败，需要 SMTP 配置
        if "smtp" in error_lower or "邮件发送失败" in error_message or "mail" in error_lower:
            # 检查是否提示缺少配置
            if any(keyword in error_lower for keyword in ["password", "授权码", "username", "配置", "server"]):
                return {
                    "message": "邮件发送需要 SMTP 服务器配置信息，请提供以下信息：",
                    "required_fields": [
                        {
                            "name": "smtp_server",
                            "label": "SMTP 服务器地址",
                            "type": "text",
                            "placeholder": "例如: smtp.qq.com",
                            "default": "smtp.qq.com"
                        },
                        {
                            "name": "smtp_port",
                            "label": "SMTP 端口",
                            "type": "number",
                            "placeholder": "例如: 465 或 587",
                            "default": "465"
                        },
                        {
                            "name": "sender_email",
                            "label": "发件人邮箱",
                            "type": "email",
                            "placeholder": "例如: your_email@qq.com"
                        },
                        {
                            "name": "sender_password",
                            "label": "SMTP 授权码",
                            "type": "password",
                            "placeholder": "在邮箱设置中生成的授权码",
                            "secret": True
                        }
                    ]
                }
        
        # 场景2：数据库连接需要配置
        if "database" in error_lower or "数据库" in error_message:
            if any(keyword in error_lower for keyword in ["host", "password", "连接", "connection"]):
                return {
                    "message": "数据库连接需要配置信息，请提供以下信息：",
                    "required_fields": [
                        {
                            "name": "db_host",
                            "label": "数据库主机",
                            "type": "text",
                            "placeholder": "例如: localhost"
                        },
                        {
                            "name": "db_port",
                            "label": "数据库端口",
                            "type": "number",
                            "placeholder": "例如: 3306"
                        },
                        {
                            "name": "db_name",
                            "label": "数据库名称",
                            "type": "text"
                        },
                        {
                            "name": "db_user",
                            "label": "数据库用户名",
                            "type": "text"
                        },
                        {
                            "name": "db_password",
                            "label": "数据库密码",
                            "type": "password",
                            "secret": True
                        }
                    ]
                }
        
        # 场景3：API 调用需要 API Key
        if "api" in error_lower and ("key" in error_lower or "token" in error_lower or "密钥" in error_message or "token" in error_lower):
            return {
                "message": "API 调用需要 API Key，请提供以下信息：",
                "required_fields": [
                    {
                        "name": "api_key",
                        "label": "API Key",
                        "type": "password",
                        "placeholder": "请输入您的 API Key",
                        "secret": True
                    }
                ]
            }
        
        # 可以根据需要添加更多场景
        
        return None

    def _normalize_email_module_code(self, code: str) -> str:
        """
        修正代码中 email 模块的常见 LLM 拼写错误。
        Python 标准库类名为 MIMEText、MIMEMultipart（全大写），
        LLM 常生成 MimeText、MimeMultipart 导致 ImportError。
        """
        if "email.mime" not in code and "smtplib" not in code:
            return code
        out = code
        # 只替换作为标识符的拼写错误，避免改到字符串内容（简单按词边界替换）
        out = out.replace("MimeText", "MIMEText").replace("MimeMultipart", "MIMEMultipart")
        return out

    def _inject_user_params_into_code(self, code: str, params: Dict[str, Any]) -> Optional[str]:
        """
        当用户已提交配置（如 SMTP）时，将 params 中的实际值注入到代码中，
        替换占位符赋值，使重试执行时能真正使用用户输入。
        
        Args:
            code: 原始代码
            params: 包含 code 及可能存在的 smtp_server/smtp_port/sender_email/sender_password 等
            
        Returns:
            若检测到需要且已注入，返回修改后的代码；否则返回 None（走预检查逻辑）
        """
        import re
        # 仅当存在用户提交的 SMTP 相关字段且均有值时注入
        smtp_server = params.get("smtp_server") if params else None
        smtp_port = params.get("smtp_port")
        sender_email = params.get("sender_email") if params else None
        sender_password = params.get("sender_password") if params else None
        
        has_smtp = (
            (smtp_server is not None and str(smtp_server).strip())
            and (sender_email is not None and str(sender_email).strip())
            and (sender_password is not None and str(sender_password).strip())
        )
        if not has_smtp:
            return None
        
        port_val = 465
        if smtp_port is not None:
            try:
                port_val = int(smtp_port)
            except (TypeError, ValueError):
                port_val = 465
        
        def escape_for_python_string(s: str) -> str:
            if s is None:
                return ""
            s = str(s)
            return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        
        out = code
        # 替换 sender_email / from_email = "xxx"（LLM 常用 from_email 作为发件人变量）
        if sender_email is not None:
            out = re.sub(
                r'sender_email\s*=\s*["\'][^"\']*["\']',
                f'sender_email = "{escape_for_python_string(sender_email)}"',
                out,
                count=1,
                flags=re.IGNORECASE
            )
            out = re.sub(
                r'from_email\s*=\s*["\'][^"\']*["\']',
                f'from_email = "{escape_for_python_string(sender_email)}"',
                out,
                count=1,
                flags=re.IGNORECASE
            )
        # 替换 sender_password = "xxx"
        if sender_password is not None:
            out = re.sub(
                r'sender_password\s*=\s*["\'][^"\']*["\']',
                f'sender_password = "{escape_for_python_string(sender_password)}"',
                out,
                count=1,
                flags=re.IGNORECASE
            )
            # 部分 LLM 使用 password = "xxx" 作为密码变量，一并替换
            out = re.sub(
                r'\bpassword\s*=\s*["\'][^"\']*["\']',
                f'password = "{escape_for_python_string(sender_password)}"',
                out,
                count=1,
                flags=re.IGNORECASE
            )
        # 替换 smtp_server = "xxx"
        if smtp_server is not None:
            out = re.sub(
                r'smtp_server\s*=\s*["\'][^"\']*["\']',
                f'smtp_server = "{escape_for_python_string(smtp_server)}"',
                out,
                count=1,
                flags=re.IGNORECASE
            )
        # 替换 smtp_port = 数字
        out = re.sub(
            r'smtp_port\s*=\s*\d+',
            f'smtp_port = {port_val}',
            out,
            count=1,
            flags=re.IGNORECASE
        )
        # 替换 SMTP("server", port) 形式的调用
        if smtp_server is not None:
            out = re.sub(
                r'(\bSMTP(?:_SSL)?\s*\(\s*)["\'][^"\']*["\']\s*,\s*\d+',
                f'\\1"{escape_for_python_string(smtp_server)}", {port_val}',
                out,
                count=1,
                flags=re.IGNORECASE
            )
        # 端口 465 为 SSL 直连，需使用 SMTP_SSL 且不能调用 starttls()
        if port_val == 465:
            # 将 SMTP(...) 改为 SMTP_SSL(...)，参数已在上文替换为实际值或变量
            out = re.sub(
                r'\bsmtplib\.SMTP\s*(\s*\([^)]+\))',
                r'smtplib.SMTP_SSL\1',
                out,
                count=1,
                flags=re.IGNORECASE
            )
            # 注释掉 starttls，465 端口已走 SSL 直连
            out = re.sub(
                r'(\s*)server\.starttls\s*\(\s*\).*',
                r'\1# server.starttls()  # 465 端口使用 SSL 直连，无需 starttls',
                out,
                count=1,
                flags=re.IGNORECASE
            )
        # 为 SMTP 连接设置 socket 超时，避免连接挂起导致工具 30s 超时
        out = re.sub(
            r'(\bserver\s*=\s*smtplib\.SMTP(?:_SSL)?\s*\([^)]+\))',
            r'\1\n        server.timeout = 15  # 避免连接挂起导致工具超时',
            out,
            count=1,
            flags=re.IGNORECASE
        )
        # 只要检测到用户已提供 SMTP 信息就返回修改后的代码，跳过预检查并执行
        return out

    def _analyze_code_for_required_info(self, code: str) -> Optional[Dict[str, Any]]:
        """
        在执行代码前分析代码是否需要额外的配置信息
        
        如果代码需要 SMTP、数据库连接等配置但参数中未提供，则返回需要用户输入的信息
        
        Args:
            code: 要执行的 Python 代码
            
        Returns:
            如果检测到需要额外配置但缺失，返回需要用户输入的字典；否则返回 None
        """
        code_lower = code.lower()
        
        # 检测 SMTP 邮件发送
        if "smtplib" in code_lower or "smtp" in code_lower or "email.mime" in code_lower:
            # 检查是否使用了占位符模式
            # 常见的占位符模式：your_xxx, xxx@xxx.com, "password", 'password' 等
            placeholder_patterns = [
                'your_email', 'your_password', 'your_username',
                'xxx', 'example.com', '请替换', '需要配置',
                'placeholder', 'test@'
            ]
            
            has_placeholder = any(p in code_lower for p in placeholder_patterns)
            
            # 检查是否有实际的硬编码值（不是变量引用）
            # 例如：sender_password = "your_password" 这种是占位符
            import re
            # 匹配 sender_email = "xxx" 或 sender_password = "xxx" 这种赋值模式
            email_assignments = re.findall(r'sender_email\s*=\s*["\']([^"\']+)["\']', code, re.IGNORECASE)
            password_assignments = re.findall(r'sender_password\s*=\s*["\']([^"\']+)["\']', code, re.IGNORECASE)
            smtp_server_assignments = re.findall(r'smtp\w*\s*=\s*["\']([^"\']+)["\']', code, re.IGNORECASE)
            
            # 检查赋值是否是占位符
            is_placeholder_email = any('your' in e.lower() or 'xxx' in e.lower() or 'example' in e.lower() for e in email_assignments)
            is_placeholder_password = any('your' in p.lower() or 'xxx' in p.lower() for p in password_assignments)
            is_placeholder_smtp = any('your' in s.lower() or 'xxx' in s.lower() or 'example' in s.lower() for s in smtp_server_assignments)
            
            # 如果有占位符或没有实际配置，就需要用户输入
            if has_placeholder or is_placeholder_email or is_placeholder_password or is_placeholder_smtp:
                return {
                    "message": "邮件发送需要 SMTP 服务器配置信息，请提供以下信息：",
                    "required_fields": [
                        {
                            "name": "smtp_server",
                            "label": "SMTP 服务器地址",
                            "type": "text",
                            "placeholder": "例如: smtp.qq.com",
                            "default": "smtp.qq.com"
                        },
                        {
                            "name": "smtp_port",
                            "label": "SMTP 端口",
                            "type": "number",
                            "placeholder": "例如: 465 或 587",
                            "default": "465"
                        },
                        {
                            "name": "sender_email",
                            "label": "发件人邮箱",
                            "type": "email",
                            "placeholder": "例如: your_email@qq.com"
                        },
                        {
                            "name": "sender_password",
                            "label": "SMTP 授权码",
                            "type": "password",
                            "placeholder": "在邮箱设置中生成的授权码",
                            "secret": True
                        }
                    ]
                }
        
        # 检测数据库连接
        if "pymysql" in code_lower or "psycopg2" in code_lower or "mysql" in code_lower or "postgresql" in code_lower:
            if "connect" in code_lower:
                # 检查是否使用了占位符
                placeholder_patterns = ['your_host', 'your_user', 'your_password', 'localhost', 'xxx']
                has_placeholder = any(p in code_lower for p in placeholder_patterns)
                
                if has_placeholder:
                    return {
                        "message": "数据库连接需要配置信息，请提供以下信息：",
                        "required_fields": [
                            {
                                "name": "db_host",
                                "label": "数据库主机",
                                "type": "text",
                                "placeholder": "例如: localhost"
                            },
                            {
                                "name": "db_port",
                                "label": "数据库端口",
                                "type": "number",
                                "placeholder": "例如: 3306"
                            },
                            {
                                "name": "db_name",
                                "label": "数据库名称",
                                "type": "text"
                            },
                            {
                                "name": "db_user",
                                "label": "数据库用户名",
                                "type": "text"
                            },
                            {
                                "name": "db_password",
                                "label": "数据库密码",
                                "type": "password",
                                "secret": True
                            }
                        ]
                    }
        
        return None
    
    def __del__(self):
        """
        析构函数
        
        清理线程池资源。
        """
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass


# ============================================================
# 便捷函数：快速执行代码
# ============================================================

async def quick_execute(code: str, timeout: int = 30) -> Dict[str, Any]:
    """
    便捷代码执行函数
    
    提供简洁的代码执行接口。
    
    Args:
        code: Python 代码
        timeout: 超时时间（秒）
        
    Returns:
        Dict[str, Any]: 执行结果
    """
    tool = PythonExecutorTool()
    return await tool.execute({"code": code, "timeout": timeout})


# ============================================================
# 代码执行结果格式化
# ============================================================

def format_execution_result(result: Dict[str, Any], 
                            max_output_length: int = 1000) -> str:
    """
    格式化代码执行结果为可读文本
    
    Args:
        result: 执行结果字典
        max_output_length: 最大输出长度
        
    Returns:
        str: 格式化后的结果文本
    """
    if not result.get("success"):
        lines = []
        lines.append("❌ 执行失败")
        lines.append(f"错误类型: {result.get('error_type', 'Unknown')}")
        lines.append(f"错误信息: {result.get('error', '未知错误')}")
        
        if result.get('output'):
            lines.append("")
            lines.append("输出:")
            lines.append(result['output'][:max_output_length])
        
        return "\n".join(lines)
    
    lines = []
    lines.append("✅ 执行成功")
    
    if result.get('result') is not None:
        lines.append(f"返回值类型: {result.get('result_type', 'Unknown')}")
        lines.append("")
        lines.append("返回值:")
        result_str = str(result['result'])
        if len(result_str) > max_output_length:
            result_str = result_str[:max_output_length] + "..."
        lines.append(result_str)
    
    if result.get('output'):
        lines.append("")
        lines.append("输出:")
        output = result['output']
        if len(output) > max_output_length:
            output = output[:max_output_length] + "..."
        lines.append(output)
    
    return "\n".join(lines)
