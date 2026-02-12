"""
HTTP 请求工具模块

本模块实现了 HTTPRequestTool 类，提供灵活的 HTTP 请求功能。

功能特点：
1. 支持多种 HTTP 方法：GET、POST、PUT、DELETE、PATCH
2. 支持自定义请求头
3. 支持请求体（JSON、表单、纯文本）
4. 自动处理 JSON 响应
5. 超时控制和错误处理
6. 完整的日志记录

使用示例：
    tool = HTTPRequestTool()
    result = await tool.execute({
        "method": "GET",
        "url": "https://api.example.com/data",
        "headers": {"Authorization": "Bearer token"},
        "timeout": 10
    })
"""

from typing import Any, Dict, List, Optional, Union
from enum import Enum
import httpx
import json
from app.tools.base import Tool, ToolSchema
from loguru import logger


class HTTPMethod(Enum):
    """
    HTTP 请求方法枚举
    
    定义支持的 HTTP 请求方法。
    """
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class HTTPRequestTool(Tool):
    """
    HTTP 请求工具
    
    继承自 Tool 抽象基类，提供完整的 HTTP 请求功能。
    基于 httpx 库实现，支持同步和异步请求。
    
    功能特性：
    - 支持所有常用 HTTP 方法
    - 灵活的头部和请求体配置
    - 自动 JSON 序列化/反序列化
    - 可配置超时时间
    - 详细的响应信息返回
    
    属性：
        name: 工具名称，固定为 "http_request"
        description: 工具描述
    """
    
    def __init__(self):
        """
        初始化 HTTPRequestTool 实例
        
        初始化默认超时时间和 User-Agent 头。
        """
        self._name = "http_request"
        self._description = "发送 HTTP 请求，支持 GET、POST、PUT、DELETE 等方法。可自定义请求头、请求体，并返回响应状态码、头部和内容。"
        self._default_timeout = 30.0  # 默认超时 30 秒
        self._default_headers = {
            "User-Agent": "AI-Agent-HTTP-Tool/1.0"
        }
        logger.info("[HTTPRequestTool] HTTP 请求工具初始化完成")
    
    @property
    def name(self) -> str:
        """
        获取工具名称
        
        Returns:
            str: 工具名称，固定为 "http_request"
        """
        return self._name
    
    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema
        
        定义 HTTP 请求工具的参数规范：
        - method: HTTP 方法（必需）
        - url: 请求 URL（必需）
        - headers: 请求头（可选）
        - body: 请求体（可选）
        - params: URL 查询参数（可选）
        - timeout: 超时时间（可选）
        - follow_redirects: 是否跟随重定向（可选）
        
        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                        "description": "HTTP 请求方法",
                        "default": "GET"
                    },
                    "url": {
                        "type": "string",
                        "description": "请求的完整 URL 地址"
                    },
                    "headers": {
                        "type": "object",
                        "description": "自定义请求头，键值对形式",
                        "additionalProperties": {"type": "string"}
                    },
                    "params": {
                        "type": "object",
                        "description": "URL 查询参数，键值对形式",
                        "additionalProperties": {"type": "string"}
                    },
                    "body": {
                        "type": "object",
                        "description": "请求体内容，支持 JSON 和表单数据"
                    },
                    "body_type": {
                        "type": "string",
                        "enum": ["json", "form", "text"],
                        "description": "请求体类型，默认为 json",
                        "default": "json"
                    },
                    "timeout": {
                        "type": "number",
                        "description": "请求超时时间（秒），默认为 30",
                        "default": 30,
                        "minimum": 1,
                        "maximum": 300
                    },
                    "follow_redirects": {
                        "type": "boolean",
                        "description": "是否自动跟随重定向，默认为 true",
                        "default": True
                    }
                },
                "required": ["url"],
                "additionalProperties": False
            }
        )
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 HTTP 请求
        
        根据传入的参数构建并发送 HTTP 请求，返回完整的响应信息。
        
        参数处理逻辑：
        1. 提取并验证 method 和 url
        2. 合并请求头
        3. 处理请求体（JSON/表单/文本）
        4. 构建并发送请求
        5. 解析响应内容
        6. 返回结构化结果
        
        Args:
            params: 参数字典，必须包含 "url" 键
            
        Returns:
            Dict[str, Any]: HTTP 响应结果，包含：
                - success: 是否成功
                - status_code: HTTP 状态码
                - status_text: 状态码描述
                - headers: 响应头字典
                - content: 响应内容（自动解析 JSON 或返回文本）
                - content_type: 响应内容类型
                - response_time_ms: 响应时间（毫秒）
                - error: 错误信息（失败时）
        """
        import time
        start_time = time.time()
        
        # ========== 参数提取阶段 ==========
        method = params.get("method", "GET").upper()
        url = params.get("url", "")
        custom_headers = params.get("headers", {})
        params_dict = params.get("params", {})
        body = params.get("body", None)
        body_type = params.get("body_type", "json")
        timeout = params.get("timeout", self._default_timeout)
        follow_redirects = params.get("follow_redirects", True)
        
        # 参数验证
        if not url:
            logger.warning("[HTTPRequestTool] URL 为空")
            return {
                "success": False,
                "error": "URL 不能为空"
            }
        
        # 验证 HTTP 方法
        try:
            http_method = HTTPMethod(method)
        except ValueError:
            logger.warning(f"[HTTPRequestTool] 不支持的 HTTP 方法: {method}")
            return {
                "success": False,
                "error": f"不支持的 HTTP 方法: {method}"
            }
        
        logger.info(f"[HTTPRequestTool] 准备发送 {method} 请求: {url}")
        
        try:
            # ========== 请求构建阶段 ==========
            # 合并请求头
            headers = {**self._default_headers, **custom_headers}
            
            # 确定 Content-Type
            content_type = None
            if body is not None:
                if body_type == "json":
                    content_type = "application/json"
                    body = json.dumps(body)
                elif body_type == "form":
                    content_type = "application/x-www-form-urlencoded"
                    body = self._encode_form_data(body)
                elif body_type == "text":
                    content_type = "text/plain"
                    body = str(body)
                
                if content_type:
                    headers["Content-Type"] = content_type
            
            # ========== 请求发送阶段 ==========
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=follow_redirects
            ) as client:
                
                # 根据 HTTP 方法选择调用方式
                request_params = {
                    "url": url,
                    "headers": headers,
                    "params": params_dict if params_dict else None
                }
                
                # 只有 Body 方法才添加请求体
                if http_method in [HTTPMethod.POST, HTTPMethod.PUT, HTTPMethod.PATCH]:
                    if body is not None:
                        request_params["content"] = body
                
                # 发送请求
                response = await client.request(
                    method=http_method.value,
                    **request_params
                )
            
            # ========== 结果解析阶段 ==========
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # 解析响应内容
            content = response.text
            
            # 尝试解析 JSON
            parsed_content = None
            content_type = response.headers.get("Content-Type", "")
            
            if "application/json" in content_type:
                try:
                    parsed_content = response.json()
                except json.JSONDecodeError:
                    logger.warning("[HTTPRequestTool] JSON 解析失败，使用原始文本")
            
            # 构建响应头字典
            response_headers = dict(response.headers)
            
            logger.info(
                f"[HTTPRequestTool] 请求完成，状态码: {response.status_code}，"
                f"响应时间: {response_time_ms}ms"
            )
            
            # ========== 返回结果 ==========
            return {
                "success": True,
                "status_code": response.status_code,
                "status_text": response.reason_phrase,
                "headers": response_headers,
                "content": parsed_content if parsed_content is not None else content,
                "raw_content": content,  # 保留原始内容
                "content_type": content_type,
                "response_time_ms": response_time_ms,
                "url": str(response.url),  # 可能的重定向后 URL
                "metadata": {
                    "method": method,
                    "original_url": url,
                    "redirected": response.is_redirect
                }
            }
            
        except httpx.TimeoutException:
            logger.error(f"[HTTPRequestTool] 请求超时: {url}")
            return {
                "success": False,
                "error": f"请求超时（{timeout}秒）",
                "method": method,
                "url": url
            }
            
        except httpx.ConnectError as e:
            logger.error(f"[HTTPRequestTool] 连接失败: {url} - {str(e)}")
            return {
                "success": False,
                "error": f"无法连接到服务器: {str(e)}",
                "method": method,
                "url": url
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"[HTTPRequestTool] HTTP 错误: {e.response.status_code} - {url}")
            return {
                "success": False,
                "error": f"HTTP 请求失败，状态码: {e.response.status_code}",
                "status_code": e.response.status_code,
                "method": method,
                "url": url
            }
            
        except Exception as e:
            logger.exception(f"[HTTPRequestTool] 请求发生未知错误: {str(e)}")
            return {
                "success": False,
                "error": f"请求失败: {str(e)}",
                "method": method,
                "url": url
            }
    
    def _encode_form_data(self, data: Dict[str, Any]) -> str:
        """
        编码表单数据
        
        将字典格式的数据编码为 application/x-www-form-urlencoded 格式。
        
        Args:
            data: 表单数据字典
            
        Returns:
            str: 编码后的表单字符串
        """
        from urllib.parse import urlencode
        # 将所有值转换为字符串
        string_data = {k: str(v) for k, v in data.items()}
        return urlencode(string_data)


# ============================================================
# 便捷函数：常用 HTTP 请求方法
# ============================================================

async def http_get(url: str, headers: Dict[str, str] = None, 
                   params: Dict[str, str] = None) -> Dict[str, Any]:
    """
    便捷 GET 请求函数
    
    Args:
        url: 请求 URL
        headers: 请求头
        params: 查询参数
        
    Returns:
        Dict[str, Any]: HTTP 响应结果
    """
    tool = HTTPRequestTool()
    return await tool.execute({
        "method": "GET",
        "url": url,
        "headers": headers,
        "params": params
    })


async def http_post(url: str, body: Dict[str, Any] = None,
                    headers: Dict[str, str] = None) -> Dict[str, Any]:
    """
    便捷 POST 请求函数
    
    Args:
        url: 请求 URL
        body: 请求体
        headers: 请求头
        
    Returns:
        Dict[str, Any]: HTTP 响应结果
    """
    tool = HTTPRequestTool()
    return await tool.execute({
        "method": "POST",
        "url": url,
        "body": body,
        "headers": headers
    })


async def http_put(url: str, body: Dict[str, Any] = None,
                   headers: Dict[str, str] = None) -> Dict[str, Any]:
    """
    便捷 PUT 请求函数
    
    Args:
        url: 请求 URL
        body: 请求体
        headers: 请求头
        
    Returns:
        Dict[str, Any]: HTTP 响应结果
    """
    tool = HTTPRequestTool()
    return await tool.execute({
        "method": "PUT",
        "url": url,
        "body": body,
        "headers": headers
    })


async def http_delete(url: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    """
    便捷 DELETE 请求函数
    
    Args:
        url: 请求 URL
        headers: 请求头
        
    Returns:
        Dict[str, Any]: HTTP 响应结果
    """
    tool = HTTPRequestTool()
    return await tool.execute({
        "method": "DELETE",
        "url": url,
        "headers": headers
    })


# ============================================================
# HTTP 响应格式化工具
# ============================================================

def format_http_response(response: Dict[str, Any], 
                         max_content_length: int = 500) -> str:
    """
    格式化 HTTP 响应为可读文本
    
    Args:
        response: HTTP 响应结果
        max_content_length: 最大内容长度
        
    Returns:
        str: 格式化后的响应信息
    """
    if not response.get("success"):
        return f"请求失败: {response.get('error', '未知错误')}"
    
    lines = []
    lines.append(f"状态码: {response.get('status_code', 'N/A')} {response.get('status_text', '')}")
    lines.append(f"响应时间: {response.get('response_time_ms', 'N/A')}ms")
    lines.append(f"内容类型: {response.get('content_type', 'unknown')}")
    lines.append(f"URL: {response.get('url', 'N/A')}")
    lines.append("")
    
    content = response.get("content", "")
    if isinstance(content, (dict, list)):
        content_str = json.dumps(content, ensure_ascii=False, indent=2)
    else:
        content_str = str(content)
    
    if len(content_str) > max_content_length:
        content_str = content_str[:max_content_length] + "..."
    
    lines.append("响应内容:")
    lines.append(content_str)
    
    return "\n".join(lines)
