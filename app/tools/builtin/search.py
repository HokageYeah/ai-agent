"""
网络搜索工具模块

本模块实现了 SearchTool 类，提供基于 DuckDuckGo 的网络搜索功能。

功能特点：
1. 支持多关键词搜索，自动编码中文关键词
2. 返回结构化的搜索结果（title / url / snippet）
3. 从 http.py 复用 URL 安全校验和 HTML 清洗函数，保持模块一致性
4. 搜索结果摘要自动剥离 HTML 标签 + 规范化空白（借鉴 web.py）
5. 主方案：DuckDuckGo HTML 解析（支持中文）
6. 备用方案：DuckDuckGo Instant Answer API
7. 多层错误处理 + colorama 彩色分层日志

参考吸取：
- web.py 的 _strip_tags / _normalize 用于清洗搜索结果摘要
- web.py 的 URL 校验逻辑（在 http.py 中已封装，此处复用）

使用示例：
    tool = SearchTool()
    results = await tool.execute({
        "query": "Python 机器学习",
        "max_results": 5
    })
"""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from colorama import Fore, Style
from loguru import logger

from app.tools.base import Tool, ToolSchema


# ──────────────────────────────────────────────────────────────
# 模块级常量
# ──────────────────────────────────────────────────────────────

# 与 http.py 保持一致，使用真实浏览器 UA 规避反爬
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# DuckDuckGo HTML 搜索端点（支持中文搜索，主要方案）
_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
# _DDG_HTML_URL = "https://api.search.brave.com/res/v1/web/search"

# DuckDuckGo Instant Answer API 端点（备用方案）
_DDG_API_URL = "https://api.duckduckgo.com/"

# 搜索请求超时（秒）
_SEARCH_TIMEOUT = 30.0

# 摘要最大保留字符数（截断过长内容，防止 LLM token 超限）
_MAX_SNIPPET_CHARS = 500

# 标题最大保留字符数
_MAX_TITLE_CHARS = 200


# ──────────────────────────────────────────────────────────────
# 工具函数：HTML 标签清洗（复用 web.py 核心逻辑，统一代码风格）
# ──────────────────────────────────────────────────────────────

def _strip_tags(text: str) -> str:
    """
    剥离 HTML 标签，还原纯文本

    针对搜索结果摘要常见的 HTML 噪声：
    1. 优先移除 <b>/<em> 等高亮标签渲染的内容（DuckDuckGo 会在摘要里加 <b>）
    2. 移除所有剩余 HTML 标签
    3. 解码 HTML 实体（&amp; → &，&lt; → < 等）

    Args:
        text: 含 HTML 标签的原始文本

    Returns:
        str: 纯文本版本
    """
    import html as html_mod
    # 移除完整的 script / style 块
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>",   "", text, flags=re.I)
    # 移除所有剩余 HTML 标签（保留标签内文本内容）
    text = re.sub(r"<[^>]+>", "", text)
    # 解码 HTML 转义实体
    return html_mod.unescape(text).strip()


def _normalize(text: str) -> str:
    """
    规范化空白字符

    - 合并同行多余空格 / 制表符为单个空格
    - 合并连续 3+ 个换行为双换行

    Args:
        text: 原始文本

    Returns:
        str: 规范化后的文本
    """
    text = re.sub(r"[ \t]+",  " ",    text)
    text = re.sub(r"\n{3,}",  "\n\n", text)
    return text.strip()


def _clean_snippet(raw: str) -> str:
    """
    清洗搜索结果摘要

    组合 _strip_tags + _normalize，生成干净的单行摘要文字。

    Args:
        raw: DuckDuckGo 返回的原始摘要（可能含 HTML 标签和多余空白）

    Returns:
        str: 清洗后、长度截断的纯文本摘要
    """
    if not raw:
        return ""
    cleaned = _normalize(_strip_tags(raw))
    # 超出限制时截断并加省略号
    if len(cleaned) > _MAX_SNIPPET_CHARS:
        cleaned = cleaned[:_MAX_SNIPPET_CHARS] + "..."
    return cleaned


# ──────────────────────────────────────────────────────────────
# 主工具类
# ──────────────────────────────────────────────────────────────

class SearchTool(Tool):
    """
    网络搜索工具

    继承自 Tool 抽象基类，提供基于 DuckDuckGo 的网络搜索功能。

    搜索策略（双层容错）：
    1. 主方案：DuckDuckGo HTML 页面解析（支持中文，结果更丰富）
    2. 备用方案：DuckDuckGo Instant Answer API（结构化 JSON，稳定但结果少）

    搜索结果摘要清洗：
    - 借鉴 web.py 的 _strip_tags + _normalize，自动剥离 <b> 等 HTML 标签

    属性：
        name:        工具名称，固定为 "search"
        description: 工具描述
    """

    def __init__(self):
        """
        初始化 SearchTool 实例

        初始化时输出彩色日志，便于追踪工具加载状态。
        """
        self._name        = "search"
        self._description = "执行网络搜索，查找相关信息。支持多关键词查询，返回结构化的搜索结果。"
        logger.info(
            f"{Fore.CYAN}[SearchTool] 网络搜索工具初始化完成 "
            f"| 主方案: DuckDuckGo HTML 解析（支持中文）"
            f"| 备用: Instant Answer API{Style.RESET_ALL}"
        )

    @property
    def name(self) -> str:
        """获取工具名称（固定为 "search"）"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema

        参数规范：
        - query:       搜索关键词（必需）
        - max_results: 最大结果数（可选，默认 5，范围 1~10）

        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type":        "string",
                        "description": "搜索关键词，支持多个关键词用空格分隔"
                    },
                    "max_results": {
                        "type":        "integer",
                        "description": "最大返回结果数量，默认为 5",
                        "default":     5,
                        "minimum":     1,
                        "maximum":     10
                    }
                },
                "required":             ["query"],
                "additionalProperties": False
            }
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行网络搜索

        完整执行流程：
        1. 提取并校验 query（不能为空）
        2. 约束 max_results 在 [1, 10] 范围内
        3. 尝试主方案：DuckDuckGo HTML 页面解析
        4. 若主方案无结果，切换备用方案：Instant Answer API
        5. 返回结构化结果（含搜索引擎元信息）

        搜索结果的摘要字段均经过 HTML 标签清洗和空白规范化处理，
        确保 LLM 收到的是干净的纯文本内容。

        Args:
            params: 参数字典，必须包含 "query" 键，可选 "max_results" 键

        Returns:
            Dict[str, Any]: 搜索结果字典，包含：
                - success:     是否成功
                - query:       搜索关键词
                - results:     结果列表，每项包含 title / url / snippet / source
                - total_count: 实际返回结果数
                - metadata:    元信息（搜索引擎、请求参数等）
                - error:       错误信息（失败时存在）
        """
        # ═══════════════ 参数提取与校验 ═══════════════
        query       = params.get("query", "").strip()
        max_results = params.get("max_results", 5)

        if not query:
            logger.warning(
                f"{Fore.YELLOW}[SearchTool] 搜索关键词为空，拒绝执行{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   "搜索关键词不能为空",
                "query":   query
            }

        # 约束 max_results 在合法范围内，防止越界
        max_results = max(1, min(10, int(max_results)))
        logger.info(
            f"{Fore.CYAN}[SearchTool] 开始搜索 "
            f"| 关键词='{query}' "
            f"| 最大结果数={max_results}{Style.RESET_ALL}"
        )

        try:
            # ═══════════════ 主方案：DuckDuckGo HTML 解析 ═══════════════
            logger.debug(
                f"{Fore.BLUE}[SearchTool] 尝试主方案: DuckDuckGo HTML 解析{Style.RESET_ALL}"
            )
            html_results = await self._search_via_html(query, max_results)

            if html_results:
                logger.info(
                    f"{Fore.GREEN}[SearchTool] 主方案成功 "
                    f"| 找到 {len(html_results)} 条结果{Style.RESET_ALL}"
                )
                return {
                    "success":     True,
                    "query":       query,
                    "results":     html_results,
                    "total_count": len(html_results),
                    "metadata": {
                        "engine":               "duckduckgo_html",
                        "max_results_requested": max_results
                    }
                }

            # ═══════════════ 备用方案：Instant Answer API ═══════════════
            logger.warning(
                f"{Fore.YELLOW}[SearchTool] 主方案无结果，切换至备用 API 方案{Style.RESET_ALL}"
            )
            api_results = await self._search_via_api(query, max_results)

            if api_results:
                logger.info(
                    f"{Fore.GREEN}[SearchTool] 备用 API 方案成功 "
                    f"| 找到 {len(api_results)} 条结果{Style.RESET_ALL}"
                )
                return {
                    "success":     True,
                    "query":       query,
                    "results":     api_results,
                    "total_count": len(api_results),
                    "metadata": {
                        "engine":               "duckduckgo_api",
                        "max_results_requested": max_results
                    }
                }

            # ═══════════════ 两种方案均无结果 ═══════════════
            logger.warning(
                f"{Fore.YELLOW}[SearchTool] 主备方案均无结果，关键词: '{query}'{Style.RESET_ALL}"
            )
            return {
                "success":     True,   # 仍为 True，表示工具本身执行成功，只是无匹配内容
                "query":       query,
                "results":     [],
                "total_count": 0,
                "metadata": {
                    "engine":               "duckduckgo",
                    "max_results_requested": max_results,
                    "note":                 "未找到相关搜索结果，建议尝试其他关键词"
                }
            }

        except Exception as e:
            logger.exception(
                f"{Fore.RED}[SearchTool] 搜索发生未知错误: {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   f"搜索失败: {e}",
                "query":   query
            }

    # ──────────────────────────────────────────────────────────
    # 私有方法：主方案 — DuckDuckGo HTML 解析
    # ──────────────────────────────────────────────────────────

    async def _search_via_html(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """
        通过解析 DuckDuckGo HTML 搜索页面获取结果

        使用 html.duckduckgo.com 轻量 HTML 接口，比 JS 渲染版更稳定，
        且对中文关键词友好。

        Args:
            query:       搜索关键词（已 strip）
            max_results: 最大结果条数

        Returns:
            List[Dict[str, Any]]: 格式化并清洗后的搜索结果列表
        """
        try:
            # 构建搜索 URL（b=1 表示从第一页开始）
            search_url = f"{_DDG_HTML_URL}?q={quote_plus(query)}&b=1"
            logger.debug(
                f"{Fore.BLUE}[SearchTool] HTML 搜索请求: {search_url}{Style.RESET_ALL}"
            )

            async with httpx.AsyncClient(
                timeout=_SEARCH_TIMEOUT,
                follow_redirects=True,
                max_redirects=5  # 与 http.py 保持一致，防止无限跳转
            ) as client:
                response = await client.get(
                    search_url,
                    headers={
                        "User-Agent":      _USER_AGENT,
                        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                        # 关闭 gzip 要求，避免部分环境解码失败
                        "Accept-Encoding": "identity"
                    }
                )
            response.raise_for_status()

            html_content = response.text
            logger.debug(
                f"{Fore.BLUE}[SearchTool] HTML 响应长度: {len(html_content)} 字符{Style.RESET_ALL}"
            )

            results = self._parse_html_results(html_content, max_results)

            if results:
                logger.info(
                    f"{Fore.GREEN}[SearchTool] HTML 解析成功，获得 {len(results)} 条结果{Style.RESET_ALL}"
                )
            else:
                logger.warning(
                    f"{Fore.YELLOW}[SearchTool] HTML 解析未提取到有效结果{Style.RESET_ALL}"
                )

            return results

        except httpx.TimeoutException:
            logger.error(
                f"{Fore.RED}[SearchTool] HTML 搜索超时（>{_SEARCH_TIMEOUT}s），关键词: '{query}'{Style.RESET_ALL}"
            )
            return []
        except httpx.TooManyRedirects:
            logger.error(
                f"{Fore.RED}[SearchTool] HTML 搜索重定向次数过多，可能遭遇反爬{Style.RESET_ALL}"
            )
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                f"{Fore.RED}[SearchTool] HTML 搜索 HTTP 错误: {e.response.status_code}{Style.RESET_ALL}"
            )
            return []
        except Exception as e:
            logger.error(
                f"{Fore.RED}[SearchTool] HTML 解析异常: {e}{Style.RESET_ALL}"
            )
            return []

    def _parse_html_results(self, html_content: str, max_results: int) -> List[Dict[str, Any]]:
        """
        解析 DuckDuckGo HTML 页面中的搜索结果

        解析策略（双层容错）：
        1. 主模式：精确匹配 class="result__a"（标题链接）+ class="result__snippet"（摘要）
        2. 备用模式：宽泛匹配所有 https:// 开头的 <a> 标签

        摘要字段用 _clean_snippet 清洗：去 HTML 标签 + 规范化空白（借鉴 web.py）

        Args:
            html_content: DuckDuckGo HTML 响应内容
            max_results:  最大结果条数

        Returns:
            List[Dict[str, Any]]: 格式化搜索结果列表
        """
        results = []

        # ── 主解析模式：精确匹配 DuckDuckGo 结果结构 ──
        # 匹配格式：<a class="result__a" href="URL">标题</a>
        #   可选紧随：<a class="result__snippet" ...>摘要</a>
        primary_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>.*?'
            r'(?:<a[^>]*class="result__snippet"[^>]*href="[^"]*"[^>]*>([^<]*)</a>)?',
            re.DOTALL | re.IGNORECASE
        )
        matches = primary_pattern.findall(html_content)
        logger.debug(
            f"{Fore.BLUE}[SearchTool] 主模式正则匹配到 {len(matches)} 个候选结果{Style.RESET_ALL}"
        )

        for url_raw, title_raw, snippet_raw in matches[:max_results]:
            url     = url_raw.strip()
            title   = _clean_snippet(title_raw)        # 用通用清洗函数处理标题
            snippet = _clean_snippet(snippet_raw or "") # 摘要同样清洗

            if not url or not title:
                continue

            # 清理 DuckDuckGo 重定向包装 URL（提取 uddg= 参数中的真实 URL）
            if "uddg=" in url:
                import urllib.parse as _up
                parsed_qs = _up.parse_qs(_up.urlparse(url).query)
                url = parsed_qs.get("uddg", [url])[0]

            results.append({
                "title":   title[:_MAX_TITLE_CHARS],
                "url":     url,
                "snippet": snippet,
                "source":  "duckduckgo"
            })

        # ── 备用解析模式：宽泛匹配 https:// 开头的链接 ──
        # 仅当主模式无结果时启用，防止漏掉结果
        if not results:
            logger.debug(
                f"{Fore.YELLOW}[SearchTool] 主模式无结果，启用备用宽泛解析模式{Style.RESET_ALL}"
            )
            fallback_pattern = re.compile(
                r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)</a>',
                re.IGNORECASE
            )
            seen_urls: set = set()
            for url, title_raw in fallback_pattern.findall(html_content):
                title = _clean_snippet(title_raw)
                # 去重，并过滤 DuckDuckGo 自身的导航链接
                if url and title and url not in seen_urls and "duckduckgo" not in url:
                    seen_urls.add(url)
                    results.append({
                        "title":   title[:_MAX_TITLE_CHARS],
                        "url":     url,
                        "snippet": "",
                        "source":  "duckduckgo"
                    })
                    if len(results) >= max_results:
                        break

        return results

    # ──────────────────────────────────────────────────────────
    # 私有方法：备用方案 — DuckDuckGo Instant Answer API
    # ──────────────────────────────────────────────────────────

    async def _search_via_api(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """
        通过 DuckDuckGo Instant Answer API 搜索（备用方案）

        API 返回结构化 JSON，包含 Answer / Abstract / RelatedTopics 三个层次。
        优先级：Answer > RelatedTopics > Abstract

        API 摘要同样经过 _clean_snippet 清洗，保持格式统一。

        Args:
            query:       搜索关键词
            max_results: 最大结果条数

        Returns:
            List[Dict[str, Any]]: 格式化搜索结果列表
        """
        try:
            logger.debug(
                f"{Fore.BLUE}[SearchTool] 发送 API 请求到 {_DDG_API_URL}{Style.RESET_ALL}"
            )

            async with httpx.AsyncClient(
                timeout=_SEARCH_TIMEOUT,
                follow_redirects=True
            ) as client:
                response = await client.get(
                    _DDG_API_URL,
                    params={
                        "q":              query,
                        "format":         "json",
                        "no_html":        "1",   # 要求 API 返回时去除 HTML
                        "skip_disambig":  "1"    # 跳过消歧义页
                    }
                )
            response.raise_for_status()

            data = response.json()
            formatted: List[Dict[str, Any]] = []

            # 层次一：直接答案（最精准，如单位换算、天气等）
            if data.get("Answer"):
                formatted.append({
                    "title":   _clean_snippet(data.get("Heading", query)),
                    "url":     data.get("AnswerURL", ""),
                    "snippet": _clean_snippet(data.get("Answer", "")),
                    "source":  "duckduckgo_api"
                })

            # 层次二：相关主题列表（最常见的结果来源）
            for item in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(item, dict) and item.get("URL"):
                    formatted.append({
                        "title":   _clean_snippet(item.get("Text", ""))[:_MAX_TITLE_CHARS],
                        "url":     item.get("URL", ""),
                        "snippet": _clean_snippet(item.get("Text", "")),
                        "source":  "duckduckgo_api"
                    })

            # 层次三：Abstract 摘要（知识面板，兜底）
            if not formatted and data.get("Abstract"):
                formatted.append({
                    "title":   _clean_snippet(data.get("Heading", query)),
                    "url":     data.get("AbstractURL", ""),
                    "snippet": _clean_snippet(data.get("Abstract", "")),
                    "source":  "duckduckgo_api"
                })

            logger.info(
                f"{Fore.GREEN}[SearchTool] API 方案完成 "
                f"| 结果数={len(formatted)}{Style.RESET_ALL}"
            )
            return formatted[:max_results]

        except Exception as e:
            logger.error(
                f"{Fore.RED}[SearchTool] API 搜索失败: {e}{Style.RESET_ALL}"
            )
            return []


# ──────────────────────────────────────────────────────────────
# 便捷函数：快速执行搜索
# ──────────────────────────────────────────────────────────────

async def quick_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    快速搜索函数

    提供简洁的搜索接口，适合在工具外部快速调用。

    Args:
        query:       搜索关键词
        max_results: 最大结果数量

    Returns:
        Dict[str, Any]: 搜索结果
    """
    tool = SearchTool()
    return await tool.execute({"query": query, "max_results": max_results})


# ──────────────────────────────────────────────────────────────
# 搜索结果格式化工具
# ──────────────────────────────────────────────────────────────

def format_search_results(
    results: List[Dict[str, str]],
    include_numbering: bool = True
) -> str:
    """
    将结构化搜索结果格式化为可读文本

    适合在日志、终端输出或 LLM prompt 注入场景使用。

    Args:
        results:           搜索结果列表（每项含 title / url / snippet）
        include_numbering: 是否显示编号前缀

    Returns:
        str: 格式化后的可读文本
    """
    if not results:
        return "未找到相关结果。"

    lines: List[str] = []
    for i, result in enumerate(results, 1):
        title   = result.get("title",   "无标题")
        url     = result.get("url",     "")
        snippet = result.get("snippet", "")[:150]   # 格式化时进一步截短

        prefix = f"{i}." if include_numbering else "-"
        lines.append(f"{prefix} {title}")
        if url:
            lines.append(f"   链接: {url}")
        if snippet:
            lines.append(f"   摘要: {snippet}")
        lines.append("")  # 空行分隔每条结果

    return "\n".join(lines)
