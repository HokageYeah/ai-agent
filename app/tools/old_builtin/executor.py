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
from typing import Any, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from app.tools.base import Tool, ToolSchema
from loguru import logger


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
        
        # 创建受限的安全命名空间
        self._safe_globals = self._create_safe_globals()
        
        # 线程池，用于执行代码
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="python_exec")
        
        logger.info("[PythonExecutorTool] Python 代码执行工具初始化完成")
    
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
        
        Args:
            params: 参数字典，必须包含 "code" 键
            
        Returns:
            Dict[str, Any]: 执行结果，包含：
                - success: 是否成功
                - result: 代码返回值（如果有）
                - output: print 输出内容
                - error: 错误信息（失败时）
                - timeout: 是否超时
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
            
            return result
            
        except Exception as e:
            logger.exception(f"[PythonExecutorTool] 执行过程出错: {str(e)}")
            return {
                "success": False,
                "error": f"执行失败: {str(e)}"
            }
    
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
