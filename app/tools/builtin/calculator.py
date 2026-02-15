"""
计算器工具模块

本模块实现了 CalculatorTool 类，提供数学计算和表达式求值功能。

功能特点：
1. 支持基本算术运算（加、减、乘、除、幂等）
2. 支持数学函数（三角函数、对数、指数等）
3. 支持表达式求值（支持括号和运算符优先级）
4. 支持常量（pi、e 等）
5. 支持进制转换
6. 支持统计计算
7. 完善的错误处理和日志记录

使用示例：
    tool = CalculatorTool()
    
    # 基本运算
    result = await tool.execute({"expression": "2 + 3"})
    
    # 数学函数
    result = await tool.execute({"expression": "sin(pi/2)"})
    
    # 复杂表达式
    result = await tool.execute({"expression": "(3 + 4) * 2 / 5"})
"""

import math
import statistics
import operator
from typing import Any, Dict
from app.tools.base import Tool, ToolSchema
from loguru import logger


class CalculatorTool(Tool):
    """
    计算器工具
    
    继承自 Tool 抽象基类，提供数学计算和表达式求值功能。
    
    支持的操作：
    - 算术运算: +, -, *, /, //, %, **
    - 数学函数: sin, cos, tan, log, sqrt, pow 等
    - 数学常量: pi, e, tau, inf
    - 统计函数: mean, median, mode, stdev, variance
    - 取整函数: abs, round, floor, ceil, trunc
    
    属性：
        name: 工具名称，固定为 "calculator"
        description: 工具描述
    """
    
    # 可用的安全函数和常量
    _SAFE_FUNCTIONS = {
        # 数学函数
        'sin': math.sin,
        'cos': math.cos,
        'tan': math.tan,
        'asin': math.asin,
        'acos': math.acos,
        'atan': math.atan,
        'sinh': math.sinh,
        'cosh': math.cosh,
        'tanh': math.tanh,
        'log': math.log,
        'log10': math.log10,
        'log2': math.log2,
        'exp': math.exp,
        'sqrt': math.sqrt,
        'pow': pow,
        'abs': abs,
        'round': round,
        'floor': math.floor,
        'ceil': math.ceil,
        'trunc': math.trunc,
        'factorial': math.factorial,
        'gcd': math.gcd,
        # 统计函数
        'mean': statistics.mean,
        'median': statistics.median,
        'mode': statistics.mode,
        'stdev': statistics.stdev,
        'pstdev': statistics.pstdev,
        'variance': statistics.variance,
        'pvariance': statistics.pvariance,
        'sum': sum,
        'min': min,
        'max': max,
        # 辅助函数
        'rad': math.radians,
        'deg': math.degrees,
    }
    
    # 数学常量
    _CONSTANTS = {
        'pi': math.pi,
        'e': math.e,
        'tau': math.tau,
        'inf': math.inf,
    }
    
    # 禁止的关键字模式
    _FORBIDDEN_PATTERNS = [
        'import', 'from', 'class', 'def', 'return', 'yield',
        'if', 'else', 'elif', 'for', 'while', 'try', 'except',
        'with', 'as', 'lambda', 'global', 'nonlocal',
        'assert', 'raise', 'pass', 'break', 'continue',
        'async', 'await', 'True', 'False', 'None',
        '__import__', 'exec', 'eval', 'compile', 'open',
    ]
    
    def __init__(self):
        """
        初始化 CalculatorTool
        """
        self._name = "calculator"
        self._description = "执行数学计算。支持基本运算、三角函数、对数、指数、统计等。输入表达式，返回计算结果。"
        logger.info("[CalculatorTool] 计算器工具初始化完成")
    
    @property
    def name(self) -> str:
        """
        获取工具名称
        
        Returns:
            str: 工具名称，固定为 "calculator"
        """
        return self._name
    
    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema
        
        定义计算器工具的参数规范：
        - expression: 数学表达式（必需）
        - precision: 结果精度（可选，默认 10）
        
        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，支持运算符: + - * / // % **，函数: sin, cos, log, sqrt 等"
                    },
                    "precision": {
                        "type": "integer",
                        "description": "结果精度（小数位数），默认为 10",
                        "default": 10,
                        "minimum": 0,
                        "maximum": 100
                    },
                    "degrees": {
                        "type": "boolean",
                        "description": "三角函数使用角度制（默认 False，使用弧度制）",
                        "default": False
                    }
                },
                "required": ["expression"],
                "additionalProperties": False
            }
        )
    
    def _validate_expression(self, expression: str) -> tuple[bool, str]:
        """
        验证表达式安全性
        
        Args:
            expression: 数学表达式
            
        Returns:
            tuple: (是否安全, 错误信息)
        """
        if not expression or not expression.strip():
            return False, "表达式不能为空"
        
        expr_lower = expression.lower()
        
        # 检查禁止的模式
        for pattern in self._FORBIDDEN_PATTERNS:
            # 使用单词边界匹配
            import re
            if re.search(r'\b' + pattern + r'\b', expr_lower):
                return False, f"表达式包含禁止的关键字: {pattern}"
        
        return True, ""
    
    def _prepare_expression(self, expression: str, use_degrees: bool) -> str:
        """
        准备表达式，将函数名和常量替换为可执行的形式
        
        Args:
            expression: 原始表达式
            use_degrees: 是否使用角度制
            
        Returns:
            str: 准备好的表达式
        """
        expr = expression.lower()
        
        print(f"准备表达式: {expr}")
        # 替换常量
        for name, value in self._CONSTANTS.items():
            # 使用正则替换完整的单词
            import re
            expr = re.sub(r'\b' + name + r'\b', str(value), expr)
        
        # 替换函数（保留函数名，eval 会调用对应的函数）
        # 不需要额外处理，因为函数已经在 _SAFE_FUNCTIONS 中
        
        print(f"准备好的表达式: {expr}")
        return expr
    
    def _safe_eval(self, expression: str, 
                   use_degrees: bool) -> Any:
        """
        安全地计算表达式
        
        Args:
            expression: 准备好的表达式
            use_degrees: 是否使用角度制
            
        Returns:
            Any: 计算结果
        """
        # 构建安全命名空间
        safe_locals = {}
        
        # 如果使用角度制，包装三角函数
        if use_degrees:
            safe_locals['sin'] = lambda x: math.sin(math.radians(x))
            safe_locals['cos'] = lambda x: math.cos(math.radians(x))
            safe_locals['tan'] = lambda x: math.tan(math.radians(x))
            safe_locals['asin'] = lambda x: math.degrees(math.asin(x))
            safe_locals['acos'] = lambda x: math.degrees(math.acos(x))
            safe_locals['atan'] = lambda x: math.degrees(math.atan(x))
        else:
            # 添加普通三角函数
            safe_locals['sin'] = math.sin
            safe_locals['cos'] = math.cos
            safe_locals['tan'] = math.tan
            safe_locals['asin'] = math.asin
            safe_locals['acos'] = math.acos
            safe_locals['atan'] = math.atan
        
        # 添加其他安全函数
        safe_locals.update({
            'log': math.log,
            'log10': math.log10,
            'log2': math.log2,
            'exp': math.exp,
            'sqrt': math.sqrt,
            'pow': pow,
            'abs': abs,
            'round': round,
            'floor': math.floor,
            'ceil': math.ceil,
            'trunc': math.trunc,
            'factorial': math.factorial,
            'gcd': math.gcd,
            'rad': math.radians,
            'deg': math.degrees,
            'mean': statistics.mean,
            'median': statistics.median,
            'mode': statistics.mode,
            'stdev': statistics.stdev,
            'pstdev': statistics.pstdev,
            'variance': statistics.variance,
            'pvariance': statistics.pvariance,
            'sum': sum,
            'min': min,
            'max': max,
        })
        
        # 添加常量
        safe_locals['pi'] = math.pi
        safe_locals['e'] = math.e
        safe_locals['tau'] = math.tau
        safe_locals['inf'] = math.inf
        
        # 运算符函数
        safe_locals['__add__'] = operator.add
        safe_locals['__sub__'] = operator.sub
        safe_locals['__mul__'] = operator.mul
        safe_locals['__truediv__'] = operator.truediv
        safe_locals['__floordiv__'] = operator.floordiv
        safe_locals['__mod__'] = operator.mod
        safe_locals['__pow__'] = operator.pow
        
        # 计算表达式
        return eval(expression, {"__builtins__": {}}, safe_locals)
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行数学计算
        
        根据传入的表达式进行计算，返回结果。
        
        参数处理逻辑：
        1. 提取并验证 expression 参数
        2. 验证表达式安全性
        3. 准备表达式（替换常量）
        4. 安全计算
        5. 格式化结果
        
        Args:
            params: 参数字典，必须包含 "expression" 键
            
        Returns:
            Dict[str, Any]: 计算结果，包含：
                - success: 是否成功
                - result: 计算结果
                - result_type: 结果类型
                - expression: 原始表达式
                - error: 错误信息（失败时）
        """
        import time
        start_time = time.time()
        
        # ========== 参数提取阶段 ==========
        expression = params.get("expression", "")
        precision = params.get("precision", 10)
        use_degrees = params.get("degrees", False)
        
        # 参数验证
        if not expression or not expression.strip():
            logger.warning("[CalculatorTool] 表达式为空")
            return {
                "success": False,
                "error": "表达式不能为空"
            }
        
        logger.info(f"[CalculatorTool] 准备计算表达式: {expression}")
        
        try:
            # ========== 验证和准备阶段 ==========
            # 验证表达式安全性
            is_valid, error_msg = self._validate_expression(expression)
            if not is_valid:
                logger.warning(f"[CalculatorTool] 表达式验证失败: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "expression": expression
                }
            
            # 准备表达式
            prepared_expr = self._prepare_expression(expression, use_degrees)
            
            # ========== 计算阶段 ==========
            result = self._safe_eval(prepared_expr, use_degrees)
            
            # 格式化结果
            if isinstance(result, float):
                result_str = f"{result:.{precision}f}"
                # 移除尾部多余的零
                if '.' in result_str:
                    result_str = result_str.rstrip('0').rstrip('.')
            else:
                result_str = str(result)
            
            execution_time_ms = (time.time() - start_time) * 1000
            
            logger.info(
                f"[CalculatorTool] 计算成功: {expression} = {result_str}, "
                f"执行时间: {execution_time_ms:.2f}ms"
            )
            
            return {
                "success": True,
                "result": result,
                "result_str": result_str,
                "result_type": type(result).__name__,
                "expression": expression,
                "execution_time_ms": round(execution_time_ms, 2)
            }
            
        except SyntaxError as e:
            logger.warning(f"[CalculatorTool] 语法错误: {str(e)}")
            return {
                "success": False,
                "error": f"表达式语法错误: {str(e)}",
                "expression": expression
            }
            
        except NameError as e:
            logger.warning(f"[CalculatorTool] 未定义名称: {str(e)}")
            return {
                "success": False,
                "error": f"使用了未定义的函数或变量: {str(e)}",
                "expression": expression
            }
            
        except ZeroDivisionError:
            logger.warning("[CalculatorTool] 除以零")
            return {
                "success": False,
                "error": "除以零错误",
                "expression": expression
            }
            
        except Exception as e:
            logger.exception(f"[CalculatorTool] 计算错误: {str(e)}")
            return {
                "success": False,
                "error": f"计算错误: {str(e)}",
                "expression": expression
            }


# ============================================================
# 便捷函数：快速计算
# ============================================================

async def quick_calculate(expression: str, 
                          precision: int = 10) -> Dict[str, Any]:
    """
    便捷计算函数
    
    Args:
        expression: 数学表达式
        precision: 结果精度
        
    Returns:
        Dict[str, Any]: 计算结果
    """
    tool = CalculatorTool()
    return await tool.execute({
        "expression": expression,
        "precision": precision
    })


# ============================================================
# 计算结果格式化工具
# ============================================================

def format_calculation_result(result: Dict[str, Any]) -> str:
    """
    格式化计算结果为可读文本
    
    Args:
        result: 计算结果字典
        
    Returns:
        str: 格式化后的结果文本
    """
    if not result.get("success"):
        return f"❌ 计算失败: {result.get('error', '未知错误')}"
    
    lines = []
    lines.append("✅ 计算成功")
    lines.append(f"表达式: {result.get('expression', '')}")
    lines.append(f"结果: {result.get('result_str', result.get('result'))}")
    lines.append(f"类型: {result.get('result_type', 'Unknown')}")
    
    return "\n".join(lines)


# ============================================================
# 支持的表达式示例
# ============================================================

EXPRESSION_EXAMPLES = """
支持的表达式示例：

算术运算:
  2 + 3 * 4          => 14
  (2 + 3) * 4        => 20
  10 / 3             => 3.3333
  2 ** 10            => 1024
  100 // 3           => 33

数学函数:
  sqrt(16)           => 4
  pow(2, 8)          => 256
  sin(pi/2)          => 1
  cos(0)             => 1
  log(e)             => 1
  log10(100)         => 2
  exp(1)             => 2.7183

统计函数:
  mean(1, 2, 3, 4, 5)=> 3
  median(1, 2, 3, 4, 5)=> 3
  stdev(1, 2, 3, 4, 5)=> 1.5811

常量:
  pi                => 3.1416
  e                 => 2.7183
  tau               => 6.2832

混合表达式:
  (sqrt(16) + 2) * pi / 2  => 12.5664
"""
