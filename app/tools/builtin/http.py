"""
HTTP 请求工具模块

本模块实现了 HTTPRequestTool 类，提供灵活的 HTTP 请求功能。

功能特点：
1. 支持多种 HTTP 方法：GET、POST、PUT、DELETE、PATCH、HEAD、OPTIONS
2. 支持自定义请求头
3. 支持请求体（JSON、表单、纯文本）
4. 自动处理 JSON / HTML / 纯文本响应
5. URL 合法性预校验（拦截非 http/https 协议，防止 SSRF）
6. 最大重定向次数限制（防止无限重定向 DoS）
7. HTML 内容智能提取：自动剥离 script/style 噪声，规范化空白
8. 响应体超长截断保护（可配置 max_content_chars）
9. 超时控制和细粒度错误处理
10. 完整的中文日志记录

参考吸取：
- web.py 中的 _validate_url / MAX_REDIRECTS / _strip_tags / _normalize 设计思路

使用示例：
    tool = HTTPRequestTool()
    result = await tool.execute({
        "method": "GET",
        "url": "https://api.example.com/data",
        "headers": {"Authorization": "Bearer token"},
        "timeout": 10
    })
"""

import html
import json
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from colorama import Fore, Style
from loguru import logger

from app.tools.base import Tool, ToolSchema


# ──────────────────────────────────────────────────────────────
# 模块级常量
# ──────────────────────────────────────────────────────────────

# 统一使用真实浏览器 UA，提高抓取兼容性（参考 web.py）
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# 最大跟随重定向次数（防止无限重定向 DoS 攻击，参考 web.py MAX_REDIRECTS）
MAX_REDIRECTS = 5

# 响应内容默认截断长度（防止超大响应阻塞 Agent 上下文）
DEFAULT_MAX_CONTENT_CHARS = 50_000


# ──────────────────────────────────────────────────────────────
# 工具函数：URL 校验 / HTML 清洗（借鉴 web.py）
# ──────────────────────────────────────────────────────────────

def _validate_url(url: str) -> tuple[bool, str]:
    """
    验证 URL 合法性

    检查规则：
    - scheme 必须为 http 或 https（拦截 file:// ftp:// 等危险协议）
    - 必须有域名部分（netloc 不能为空）

    Args:
        url: 待验证的 URL 字符串

    Returns:
        tuple[bool, str]: (是否合法, 错误描述)
    """
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"只允许 http/https 协议，当前为 '{p.scheme or '无协议'}'"
        if not p.netloc:
            return False, "缺少域名部分"
        return True, ""
    except Exception as e:
        return False, str(e)


def _strip_html_tags(text: str) -> str:
    """
    剥离 HTML 标签，还原纯文本

    处理顺序：
    1. 移除 <script> 块（避免 JS 代码干扰正文）
    2. 移除 <style> 块（避免 CSS 干扰）
    3. 移除所有剩余 HTML 标签
    4. 解码 HTML 实体（&amp; &lt; 等）

    Args:
        text: 含 HTML 标签的原始内容

    Returns:
        str: 纯文本版本
    """
    # 移除 script 和 style 块全部内容（包括内部代码）
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>",  "", text, flags=re.I)
    # 移除所有 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    # 解码 HTML 实体为 Unicode 字符
    return html.unescape(text).strip()


def _normalize_whitespace(text: str) -> str:
    """
    规范化空白字符

    - 合并同行多个空格/制表符为单个空格
    - 合并超过 2 个的连续换行为双换行

    Args:
        text: 原始文本

    Returns:
        str: 空白规范化后的文本
    """
    text = re.sub(r"[ \t]+",  " ",    text)
    text = re.sub(r"\n{3,}",  "\n\n", text)
    return text.strip()


def _to_markdown(html_content: str) -> str:
    """
    将 HTML 内容转换为 Markdown 格式文本

    移植自 web.py 的 WebFetchTool._to_markdown，在剥离标签前先把有语义的
    HTML 元素转换为对应的 Markdown 语法，使输出保留可读结构：
    - <a href="...">文字</a>  →  [文字](url)
    - <h1>~<h6>            →  # ~ ######
    - <li>                 →  - 列表项
    - </p></div>等块级闭合  →  空行（段落分隔）
    - <br><hr>             →  换行

    相比直接 _strip_html_tags，此方法保留了链接、标题层级和列表结构，
    更适合作为 LLM 的知识输入或摘要素材。

    Args:
        html_content: 原始 HTML 字符串

    Returns:
        str: 经过语义化转换后的 Markdown 文本
    """
    # 步骤一：将 <a> 超链接转换为 Markdown 链接格式 [文字](URL)
    # NOTE: 用 lambda 确保标签内嵌套 HTML 的文字部分也能被 strip_tags 处理
    text = re.sub(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
        lambda m: f'[{_strip_html_tags(m[2])}]({m[1]})',
        html_content,
        flags=re.I
    )
    # 步骤二：将 <h1>~<h6> 标题标签转换为对应层级的 # 前缀
    text = re.sub(
        r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
        lambda m: f'\n{"#" * int(m[1])} {_strip_html_tags(m[2])}\n',
        text,
        flags=re.I
    )
    # 步骤三：将 <li> 列表项转换为 Markdown 无序列表格式
    text = re.sub(
        r'<li[^>]*>([\s\S]*?)</li>',
        lambda m: f'\n- {_strip_html_tags(m[1])}',
        text,
        flags=re.I
    )
    # 步骤四：块级元素闭合标签（</p></div>等）转换为段落空行
    text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
    # 步骤五：<br> 和 <hr> 换行标签转换为换行符
    text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
    # 最后：剥离剩余 HTML 标签，规范化多余空白
    return _normalize_whitespace(_strip_html_tags(text))


def _extract_html_text(
    html_content: str,
    max_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    as_markdown: bool = True
) -> str:
    """
    从 HTML 页面提取可读正文文本

    提取策略：
    - as_markdown=True（默认）：先语义化转换为 Markdown（保留链接/标题/列表），再截断
    - as_markdown=False：直接剥离标签转为纯文本，再截断

    Args:
        html_content: 完整 HTML 字符串
        max_chars:    最大保留字符数（超出截断）
        as_markdown:  是否转换为 Markdown 格式（默认 True）

    Returns:
        str: 提取并截断后的文本（Markdown 或纯文本）
    """
    if as_markdown:
        text = _to_markdown(html_content)
    else:
        text = _normalize_whitespace(_strip_html_tags(html_content))
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...（内容已截断）"
    return text


# ──────────────────────────────────────────────────────────────
# HTTP 方法枚举
# ──────────────────────────────────────────────────────────────

class HTTPMethod(Enum):
    """
    HTTP 请求方法枚举

    定义本工具支持的全部 HTTP 方法。
    """
    GET     = "GET"
    POST    = "POST"
    PUT     = "PUT"
    DELETE  = "DELETE"
    PATCH   = "PATCH"
    HEAD    = "HEAD"
    OPTIONS = "OPTIONS"


# ──────────────────────────────────────────────────────────────
# 主工具类
# ──────────────────────────────────────────────────────────────

class HTTPRequestTool(Tool):
    """
    HTTP 请求工具

    继承自 Tool 抽象基类，提供完整的 HTTP 请求功能。
    基于 httpx 库实现异步请求。

    功能特性：
    - 支持所有常用 HTTP 方法
    - URL 安全校验（仅允许 http/https，防 SSRF）
    - 可配置最大重定向次数（防 DoS）
    - 智能响应解析：JSON / HTML → 纯文本 / 原始文本
    - 响应超长截断保护
    - 可自定义超时时间
    - 细粒度异常捕获与中文日志

    属性：
        name:        工具名称，固定为 "http_request"
        description: 工具描述
    """

    def __init__(self):
        """
        初始化 HTTPRequestTool 实例

        初始化默认超时、User-Agent 和响应截断长度等配置。
        """
        self._name        = "http_request"
        self._description = (
            "发送 HTTP 请求，支持 GET、POST、PUT、DELETE 等方法。"
            "可自定义请求头、请求体，并返回响应状态码、头部和内容。"
        )
        self._default_timeout   = 30.0                 # 默认超时 30 秒
        self._max_redirects     = MAX_REDIRECTS        # 最大重定向次数，防止无限跳转
        self._max_content_chars = DEFAULT_MAX_CONTENT_CHARS  # 响应体截断阈值
        self._default_headers   = {
            "User-Agent": USER_AGENT  # 模拟真实浏览器，提高兼容性
        }
        logger.info(
            f"{Fore.CYAN}[HTTPRequestTool] HTTP 请求工具初始化完成，"
            f"默认超时={self._default_timeout}s，"
            f"最大重定向={self._max_redirects}次，"
            f"响应截断={self._max_content_chars}字符{Style.RESET_ALL}"
        )

    @property
    def name(self) -> str:
        """获取工具名称（固定为 "http_request"）"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema

        定义 HTTP 请求工具的参数规范：
        - method:           HTTP 方法（可选，默认 GET）
        - url:              请求 URL（必需）
        - headers:          自定义请求头（可选）
        - params:           URL 查询参数（可选）
        - body:             请求体（可选）
        - body_type:        请求体类型 json/form/text（可选）
        - timeout:          超时秒数（可选，默认 30）
        - follow_redirects: 是否跟随重定向（可选，默认 true）
        - extract_text:     HTML 响应是否提取正文（可选，默认 false）

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
                        "type":        "string",
                        "enum":        ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                        "description": "HTTP 请求方法",
                        "default":     "GET"
                    },
                    "url": {
                        "type":        "string",
                        "description": "请求的完整 URL 地址"
                    },
                    "headers": {
                        "type":                 "object",
                        "description":          "自定义请求头，键值对形式",
                        "additionalProperties": {"type": "string"}
                    },
                    "params": {
                        "type":                 "object",
                        "description":          "URL 查询参数，键值对形式",
                        "additionalProperties": {"type": "string"}
                    },
                    "body": {
                        "type":        "object",
                        "description": "请求体内容，支持 JSON 和表单数据"
                    },
                    "body_type": {
                        "type":        "string",
                        "enum":        ["json", "form", "text"],
                        "description": "请求体类型，默认为 json",
                        "default":     "json"
                    },
                    "timeout": {
                        "type":        "number",
                        "description": "请求超时时间（秒），默认为 30",
                        "default":     30,
                        "minimum":     1,
                        "maximum":     300
                    },
                    "follow_redirects": {
                        "type":        "boolean",
                        "description": "是否自动跟随重定向，默认为 true",
                        "default":     True
                    },
                    "extract_text": {
                        "type":        "boolean",
                        "description": "HTML 响应是否自动提取正文纯文本，默认为 false",
                        "default":     False
                    }
                },
                "required":             ["url"],
                "additionalProperties": False
            }
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 HTTP 请求

        完整执行流程：
        1. 参数提取与基础验证（URL 不能为空，method 合法）
        2. URL 安全校验（仅允许 http/https，防止 SSRF）
        3. 合并请求头，处理请求体编码
        4. 构建并发送异步 HTTP 请求（限制重定向次数）
        5. 按 ContentType 智能解析响应（JSON / HTML正文 / 纯文本）
        6. 超长响应截断保护
        7. 返回结构化结果，含响应时间、最终 URL、是否截断等元信息

        Args:
            params: 参数字典，必须包含 "url" 键

        Returns:
            Dict[str, Any]: HTTP 响应结果，包含：
                - success:          是否成功
                - status_code:      HTTP 状态码
                - status_text:      状态码描述
                - headers:          响应头字典
                - content:          响应内容（自动解析 JSON 或返回文本）
                - raw_content:      原始文本响应（供调试）
                - content_type:     响应 Content-Type
                - response_time_ms: 响应时间（毫秒）
                - url:              最终响应 URL（含重定向后的地址）
                - truncated:        响应体是否被截断
                - metadata:         附加元信息（method/original_url/redirected）
                - error:            错误信息（失败时存在）
        """
        start_time = time.time()

        # ═══════════════ 参数提取阶段 ═══════════════
        method           = params.get("method",           "GET").upper()
        url              = params.get("url",              "")
        custom_headers   = params.get("headers",          {}) or {}
        params_dict      = params.get("params",           {}) or {}
        body             = params.get("body",             None)
        body_type        = params.get("body_type",        "json")
        timeout          = params.get("timeout",          self._default_timeout)
        follow_redirects = params.get("follow_redirects", True)
        extract_text     = params.get("extract_text",     False)  # 是否自动提取 HTML 正文

        # ── 基础校验：URL 不能为空 ──
        if not url:
            logger.warning(f"{Fore.YELLOW}[HTTPRequestTool] URL 参数为空，拒绝执行{Style.RESET_ALL}")
            return {"success": False, "error": "URL 不能为空"}

        # ── URL 安全校验：只允许 http / https（防止 SSRF 攻击）──
        is_valid, url_error = _validate_url(url)
        if not is_valid:
            logger.warning(
                f"{Fore.YELLOW}[HTTPRequestTool] URL 校验失败: {url_error}，"
                f"URL={url}{Style.RESET_ALL}"
            )
            return {"success": False, "error": f"URL 校验失败: {url_error}", "url": url}

        # ── HTTP 方法合法性校验 ──
        try:
            http_method = HTTPMethod(method)
        except ValueError:
            logger.warning(
                f"{Fore.YELLOW}[HTTPRequestTool] 不支持的 HTTP 方法: {method}{Style.RESET_ALL}"
            )
            return {"success": False, "error": f"不支持的 HTTP 方法: {method}"}

        logger.info(
            f"{Fore.CYAN}[HTTPRequestTool] 准备发送 {method} 请求 → {url}{Style.RESET_ALL}"
        )

        try:
            # ═══════════════ 请求构建阶段 ═══════════════

            # 合并默认请求头与用户自定义头（用户头优先）
            headers = {**self._default_headers, **custom_headers}

            # 处理请求体编码，并自动设置 Content-Type
            if body is not None:
                if body_type == "json":
                    headers["Content-Type"] = "application/json"
                    body = json.dumps(body, ensure_ascii=False)
                elif body_type == "form":
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    body = self._encode_form_data(body)
                elif body_type == "text":
                    headers["Content-Type"] = "text/plain; charset=utf-8"
                    body = str(body)

            # ═══════════════ 请求发送阶段 ═══════════════
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=follow_redirects,
                max_redirects=self._max_redirects  # 限制重定向次数，防止无限跳转 DoS
            ) as client:
                request_kwargs: Dict[str, Any] = {
                    "url":     url,
                    "headers": headers,
                    "params":  params_dict or None,
                }
                # 只有带 Body 的方法才传递请求体
                if http_method in (HTTPMethod.POST, HTTPMethod.PUT, HTTPMethod.PATCH):
                    if body is not None:
                        request_kwargs["content"] = body

                response = await client.request(
                    method=http_method.value,
                    **request_kwargs
                )

            # ═══════════════ 响应解析阶段 ═══════════════
            response_time_ms = int((time.time() - start_time) * 1000)
            resp_content_type = response.headers.get("Content-Type", "")
            raw_text = response.text
            truncated = False

            # 根据 Content-Type 分支解析响应内容
            if "application/json" in resp_content_type:
                # JSON 响应：直接反序列化
                try:
                    parsed_content = response.json()
                    content = parsed_content
                    logger.debug(
                        f"{Fore.CYAN}[HTTPRequestTool] JSON 响应解析成功{Style.RESET_ALL}"
                    )
                except json.JSONDecodeError:
                    # JSON 解析失败时降级为原始文本
                    logger.warning(
                        f"{Fore.YELLOW}[HTTPRequestTool] JSON 解析失败，降级为原始文本{Style.RESET_ALL}"
                    )
                    content = raw_text

            elif "text/html" in resp_content_type or raw_text[:256].lower().startswith(
                ("<!doctype", "<html")
            ):
                # HTML 响应：根据 extract_text 决定是否提取正文
                if extract_text:
                    # 优先转换为 Markdown 格式（保留链接/标题/列表语义，更适合 LLM 消费）
                    # NOTE: 使用 _to_markdown 移植自 web.py，相比纯 strip_tags 保留更多文档结构
                    content = _extract_html_text(raw_text, self._max_content_chars, as_markdown=True)
                    truncated = len(raw_text) > self._max_content_chars
                    logger.info(
                        f"{Fore.BLUE}[HTTPRequestTool] HTML → Markdown 正文提取完成，"
                        f"原始={len(raw_text)}字符，提取后={len(content)}字符，"
                        f"是否截断={truncated}{Style.RESET_ALL}"
                    )
                else:
                    # 不提取时仍然截断超长内容，防止淹没上下文
                    content = raw_text
                    if len(content) > self._max_content_chars:
                        content = content[:self._max_content_chars] + "\n...（响应内容已截断）"
                        truncated = True
            else:
                # 其他类型（纯文本、XML 等）：截断保护
                content = raw_text
                if len(content) > self._max_content_chars:
                    content = content[:self._max_content_chars] + "\n...（响应内容已截断）"
                    truncated = True

            logger.info(
                f"{Fore.GREEN}[HTTPRequestTool] 请求完成 "
                f"| 状态码={response.status_code} "
                f"| 耗时={response_time_ms}ms "
                f"| ContentType={resp_content_type[:50]} "
                f"| 是否截断={truncated}{Style.RESET_ALL}"
            )

            # ═══════════════ 返回结果 ═══════════════
            return {
                "success":          True,
                "status_code":      response.status_code,
                "status_text":      response.reason_phrase,
                "headers":          dict(response.headers),
                "content":          content,
                "raw_content":      raw_text[:2000] if truncated else raw_text,  # 截断时仅保存前 2000 字符供调试
                "content_type":     resp_content_type,
                "response_time_ms": response_time_ms,
                "url":              str(response.url),   # 重定向后的最终 URL
                "truncated":        truncated,
                "metadata": {
                    "method":       method,
                    "original_url": url,
                    "redirected":   str(response.url) != url  # 是否发生了重定向
                }
            }

        # ═══════════════ 细粒度异常处理 ═══════════════

        except httpx.TimeoutException:
            logger.error(
                f"{Fore.RED}[HTTPRequestTool] 请求超时（>{timeout}s）: {url}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   f"请求超时（超过 {timeout} 秒）",
                "method":  method,
                "url":     url
            }

        except httpx.TooManyRedirects:
            # NOTE: 超过 MAX_REDIRECTS 次跳转，可能是恶意重定向或循环跳转
            logger.error(
                f"{Fore.RED}[HTTPRequestTool] 重定向次数超过上限（>{self._max_redirects}次）: "
                f"{url}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   f"重定向次数超过上限（>{self._max_redirects}次），已拒绝继续跟随",
                "method":  method,
                "url":     url
            }

        except httpx.ConnectError as e:
            logger.error(
                f"{Fore.RED}[HTTPRequestTool] 连接失败: {url} — {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   f"无法连接到服务器: {e}",
                "method":  method,
                "url":     url
            }

        except httpx.HTTPStatusError as e:
            logger.error(
                f"{Fore.RED}[HTTPRequestTool] HTTP 错误 {e.response.status_code}: "
                f"{url}{Style.RESET_ALL}"
            )
            return {
                "success":     False,
                "error":       f"HTTP 请求失败，状态码: {e.response.status_code}",
                "status_code": e.response.status_code,
                "method":      method,
                "url":         url
            }

        except Exception as e:
            logger.exception(
                f"{Fore.RED}[HTTPRequestTool] 请求发生未知错误: {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   f"请求失败: {e}",
                "method":  method,
                "url":     url
            }

    def _encode_form_data(self, data: Dict[str, Any]) -> str:
        """
        将字典编码为 application/x-www-form-urlencoded 格式

        Args:
            data: 表单数据字典（值会被统一转换为字符串）

        Returns:
            str: 编码后的 URL 查询字符串，如 "key1=val1&key2=val2"
        """
        from urllib.parse import urlencode
        return urlencode({k: str(v) for k, v in data.items()})


# ──────────────────────────────────────────────────────────────
# 便捷函数：常用 HTTP 方法快速调用
# ──────────────────────────────────────────────────────────────

async def http_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    extract_text: bool = False
) -> Dict[str, Any]:
    """
    便捷 GET 请求函数

    Args:
        url:          请求 URL
        headers:      自定义请求头
        params:       URL 查询参数
        extract_text: 是否自动提取 HTML 正文

    Returns:
        Dict[str, Any]: HTTP 响应结果
    """
    tool = HTTPRequestTool()
    return await tool.execute({
        "method":       "GET",
        "url":          url,
        "headers":      headers,
        "params":       params,
        "extract_text": extract_text
    })


async def http_post(
    url: str,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    便捷 POST 请求函数

    Args:
        url:     请求 URL
        body:    请求体（JSON 格式）
        headers: 自定义请求头

    Returns:
        Dict[str, Any]: HTTP 响应结果
    """
    tool = HTTPRequestTool()
    return await tool.execute({
        "method":  "POST",
        "url":     url,
        "body":    body,
        "headers": headers
    })


async def http_put(
    url: str,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    便捷 PUT 请求函数

    Args:
        url:     请求 URL
        body:    请求体（JSON 格式）
        headers: 自定义请求头

    Returns:
        Dict[str, Any]: HTTP 响应结果
    """
    tool = HTTPRequestTool()
    return await tool.execute({
        "method":  "PUT",
        "url":     url,
        "body":    body,
        "headers": headers
    })


async def http_delete(
    url: str,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    便捷 DELETE 请求函数

    Args:
        url:     请求 URL
        headers: 自定义请求头

    Returns:
        Dict[str, Any]: HTTP 响应结果
    """
    tool = HTTPRequestTool()
    return await tool.execute({
        "method":  "DELETE",
        "url":     url,
        "headers": headers
    })


# ──────────────────────────────────────────────────────────────
# 响应格式化工具
# ──────────────────────────────────────────────────────────────

def format_http_response(
    response: Dict[str, Any],
    max_content_length: int = 500
) -> str:
    """
    将 HTTP 响应结果格式化为可读文本

    适合在日志、终端输出或调试场景下快速浏览响应摘要。

    Args:
        response:           HTTP 响应结果字典
        max_content_length: 内容最大显示字符数

    Returns:
        str: 格式化后的响应摘要文本
    """
    if not response.get("success"):
        return f"请求失败: {response.get('error', '未知错误')}"

    lines = [
        f"状态码:   {response.get('status_code', 'N/A')} {response.get('status_text', '')}",
        f"响应时间: {response.get('response_time_ms', 'N/A')} ms",
        f"内容类型: {response.get('content_type', 'unknown')}",
        f"URL:      {response.get('url', 'N/A')}",
        f"截断:     {'是' if response.get('truncated') else '否'}",
        "",
    ]

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
