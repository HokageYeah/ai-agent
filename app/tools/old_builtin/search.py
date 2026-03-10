"""
网络搜索工具模块

本模块实现了 SearchTool 类，提供基于 DuckDuckGo 的网络搜索功能。

功能特点：
1. 支持多关键词搜索
2. 返回结构化的搜索结果
3. 包含结果来源链接和摘要
4. 支持限制返回结果数量
5. 完善的错误处理和日志记录
6. 支持中文搜索（使用 HTML 解析方式）

使用示例：
    tool = SearchTool()
    results = await tool.execute({
        "query": "Python 机器学习",
        "max_results": 5
    })
"""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin
import httpx
from app.tools.base import Tool, ToolSchema
from loguru import logger


class SearchTool(Tool):
    """
    网络搜索工具
    
    继承自 Tool 抽象基类，提供基于 DuckDuckGo 的网络搜索功能。
    使用 DuckDuckGo HTML 搜索页面进行解析，能够更好地支持中文搜索。
    
    属性：
        name: 工具名称，固定为 "search"
        description: 工具描述
        
    方法：
        schema: 返回工具的 Schema 定义
        execute: 执行搜索查询
    """
    
    def __init__(self):
        """
        初始化 SearchTool 实例
        
        初始化时会记录日志，便于追踪工具加载状态。
        """
        self._name = "search"
        self._description = "执行网络搜索，查找相关信息。支持多关键词查询，返回结构化的搜索结果。"
        # DuckDuckGo HTML 搜索端点（支持中文搜索）
        self._html_search_url = "https://html.duckduckgo.com/html/"
        # DuckDuckGo Instant Answer API 端点（作为备用）
        self._api_url = "https://api.duckduckgo.com/"
        logger.info("[SearchTool] 网络搜索工具初始化完成")
        logger.info("[SearchTool] 搜索模式: DuckDuckGo HTML 解析（支持中文）")
    
    @property
    def name(self) -> str:
        """
        获取工具名称
        
        Returns:
            str: 工具名称，固定为 "search"
        """
        return self._name
    
    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema
        
        定义工具的参数规范，包括：
        - query: 搜索关键词（必需）
        - max_results: 最大结果数量（可选，默认5）
        
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
                        "type": "string",
                        "description": "搜索关键词，支持多个关键词用空格分隔"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数量，默认为 5",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            }
        )
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行网络搜索
        
        根据传入的参数执行搜索查询，返回结构化的搜索结果。
        使用 DuckDuckGo HTML 页面解析方式，能够更好地支持中文搜索。
        
        参数处理逻辑：
        1. 提取搜索关键词 query
        2. 提取并验证 max_results 参数
        3. 调用 DuckDuckGo HTML 搜索页面
        4. 解析 HTML 获取搜索结果
        
        Args:
            params: 参数字典，必须包含 "query" 键，可选包含 "max_results" 键
            
        Returns:
            Dict[str, Any]: 搜索结果字典，包含：
                - success: 是否成功
                - query: 搜索关键词
                - results: 结果列表，每项包含 title, url, snippet
                - total_count: 结果总数
                - error: 错误信息（失败时）
        """
        # ========== 参数提取阶段 ==========
        query = params.get("query", "")
        max_results = params.get("max_results", 5)
        
        # 参数验证
        if not query or not query.strip():
            logger.warning("[SearchTool] 搜索关键词为空")
            return {
                "success": False,
                "error": "搜索关键词不能为空",
                "query": query
            }
        
        # 清理并限制 max_results 范围
        max_results = max(1, min(10, max_results))
        logger.info(f"[SearchTool] 开始搜索，关键词: '{query}'，最大结果数: {max_results}")
        
        try:
            # ========== 方案一：HTML 解析搜索（主要方式，支持中文）==========
            logger.debug(f"[SearchTool] 尝试使用 DuckDuckGo HTML 搜索，关键词: '{query}'")
            html_results = await self._search_via_html(query, max_results)
            
            if html_results:
                logger.info(f"[SearchTool] HTML 搜索成功，找到 {len(html_results)} 条结果")
                return {
                    "success": True,
                    "query": query,
                    "results": html_results,
                    "total_count": len(html_results),
                    "metadata": {
                        "engine": "duckduckgo_html",
                        "max_results_requested": max_results
                    }
                }
            
            # ========== 方案二：备用 API 搜索 ==========
            logger.warning(f"[SearchTool] HTML 搜索未找到结果，尝试备用 API 搜索")
            api_results = await self._search_via_api(query, max_results)
            
            if api_results:
                logger.info(f"[SearchTool] API 搜索成功，找到 {len(api_results)} 条结果")
                return {
                    "success": True,
                    "query": query,
                    "results": api_results,
                    "total_count": len(api_results),
                    "metadata": {
                        "engine": "duckduckgo_api",
                        "max_results_requested": max_results
                    }
                }
            
            # ========== 两种方式都失败 ==========
            logger.warning(f"[SearchTool] 搜索未找到任何结果，关键词: '{query}'")
            return {
                "success": True,  # 仍然返回成功，只是结果为空
                "query": query,
                "results": [],
                "total_count": 0,
                "metadata": {
                    "engine": "duckduckgo",
                    "max_results_requested": max_results,
                    "note": "未找到相关搜索结果，建议尝试其他关键词"
                }
            }
            
        except Exception as e:
            logger.exception(f"[SearchTool] 搜索发生未知错误: {str(e)}")
            return {
                "success": False,
                "error": f"搜索失败: {str(e)}",
                "query": query
            }

    async def _search_via_html(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """
        通过 DuckDuckGo HTML 页面搜索
        
        解析 DuckDuckGo HTML 搜索结果页面，能够更好地支持中文搜索。
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数
            
        Returns:
            List[Dict[str, Any]]: 格式化后的搜索结果列表
        """
        try:
            # 构建 HTML 搜索 URL
            # 使用 html.duckduckgo.com 页面进行搜索
            encoded_query = quote_plus(query)
            search_url = f"{self._html_search_url}?q={encoded_query}&b=1"
            
            logger.debug(f"[SearchTool] 发送 HTML 搜索请求: {search_url}")
            
            # 发送 HTTP 请求
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(
                    search_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
                    }
                )
            
            # 检查响应状态
            response.raise_for_status()
            html_content = response.text
            
            logger.debug(f"[SearchTool] HTML 搜索响应长度: {len(html_content)} 字符")
            
            # 解析 HTML 结果
            results = self._parse_html_results(html_content, max_results)
            
            if results:
                logger.info(f"[SearchTool] HTML 解析成功，找到 {len(results)} 条结果")
            else:
                logger.warning(f"[SearchTool] HTML 解析未找到结果")
            
            return results
            
        except httpx.TimeoutException:
            logger.error(f"[SearchTool] HTML 搜索超时: '{query}'")
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"[SearchTool] HTML 搜索 HTTP 错误: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"[SearchTool] HTML 搜索解析错误: {str(e)}")
            return []

    def _parse_html_results(self, html_content: str, max_results: int) -> List[Dict[str, Any]]:
        """
        解析 DuckDuckGo HTML 搜索结果
        
        使用正则表达式解析 HTML 内容，提取搜索结果。
        
        Args:
            html_content: HTML 内容
            max_results: 最大结果数
            
        Returns:
            List[Dict[str, Any]]: 格式化后的搜索结果列表
        """
        results = []
        
        # 正则表达式匹配搜索结果
        # 匹配模式: <a class="result__a" href="URL">标题</a>
        # 和相邻的 <a class="result__snippet" href="...">摘要</a>
        
        # 匹配结果行（包括标题和摘要）
        result_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>.*?'
            r'(?:<a[^>]*class="result__snippet"[^>]*href="[^"]*"[^>]*>([^<]*)</a>)?',
            re.DOTALL | re.IGNORECASE
        )
        
        matches = result_pattern.findall(html_content)
        logger.debug(f"[SearchTool] 正则匹配到 {len(matches)} 个潜在结果")
        
        for match in matches[:max_results]:
            url = match[0].strip()
            title = match[1].strip()
            snippet = match[2].strip() if match[2] else ""
            
            # 清理 HTML 实体
            title = self._clean_html_entities(title)
            snippet = self._clean_html_entities(snippet)
            
            # 跳过无效结果
            if not url or not title:
                continue
            
            # 清理 URL（移除重定向参数）
            if "uddg=" in url:
                import urllib.parse
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                url = parsed.get("uddg", [url])[0]
            
            results.append({
                "title": title[:200],  # 限制标题长度
                "url": url,
                "snippet": snippet[:500] if snippet else "",  # 限制摘要长度
                "source": "duckduckgo"
            })
        
        # 如果正则匹配失败，尝试备用匹配模式
        if not results:
            logger.debug(f"[SearchTool] 尝试备用解析模式")
            # 备用模式：匹配更多变体
            alt_pattern = re.compile(
                r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)</a>',
                re.IGNORECASE
            )
            alt_matches = alt_pattern.findall(html_content)
            
            seen_urls = set()
            for match in alt_matches[:max_results]:
                url = match[0]
                title = match[1].strip()
                title = self._clean_html_entities(title)
                
                # 去重并过滤无效结果
                if url and title and url not in seen_urls and "duckduckgo" not in url:
                    seen_urls.add(url)
                    results.append({
                        "title": title[:200],
                        "url": url,
                        "snippet": "",
                        "source": "duckduckgo"
                    })
        
        return results

    def _clean_html_entities(self, text: str) -> str:
        """
        清理 HTML 实体
        
        将 HTML 实体转换为正常字符。
        
        Args:
            text: 包含 HTML 实体的文本
            
        Returns:
            str: 清理后的文本
        """
        if not text:
            return ""
        
        # 替换常见的 HTML 实体
        replacements = {
            "&amp;": "&",
            "&lt;": "<",
            "&gt;": ">",
            "&quot;": '"',
            "&#39;": "'",
            "&nbsp;": " ",
            "&#x27;": "'",
            "&#x2F;": "/",
            "&ldquo;": """,
            "&rdquo;": """,
            "&lsquo;": "'",
            "&rsquo;": "'",
            "&mdash;": "—",
            "&ndash;": "–",
            "&hellip;": "...",
        }
        
        for entity, char in replacements.items():
            text = text.replace(entity, char)
        
        # 移除剩余的 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        
        # 清理多余的空白
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text

    async def _search_via_api(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """
        通过 DuckDuckGo API 搜索（备用方案）
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数
            
        Returns:
            List[Dict[str, Any]]: 格式化后的搜索结果列表
        """
        try:
            # 构建 API 请求 URL
            encoded_query = quote_plus(query)
            api_params = {
                "q": encoded_query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1"
            }
            
            logger.debug(f"[SearchTool] 发送 API 请求到 {self._api_url}")
            
            # 使用 httpx 发送异步 HTTP 请求
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url,
                    params=api_params,
                    follow_redirects=True
                )
            
            # 检查 HTTP 响应状态
            response.raise_for_status()
            
            # 解析 JSON 数据
            data = response.json()
            
            # 解析搜索结果
            formatted_results = []
            
            # 优先尝试从 Answer 字段获取结果
            if data.get("Answer"):
                formatted_results.append({
                    "title": data.get("Heading", query),
                    "url": data.get("AnswerURL", ""),
                    "snippet": data.get("Answer", ""),
                    "source": "duckduckgo"
                })
            
            # 从 RelatedTopics 获取结果
            raw_results = data.get("RelatedTopics", [])
            for item in raw_results[:max_results]:
                if isinstance(item, dict) and item.get("URL"):
                    formatted_results.append({
                        "title": item.get("Text", "")[:200],
                        "url": item.get("URL", ""),
                        "snippet": item.get("Text", "")[:500],
                        "source": "duckduckgo"
                    })
            
            # 如果 RelatedTopics 为空，尝试从 Abstract 获取结果
            if not formatted_results and data.get("Abstract"):
                formatted_results.append({
                    "title": data.get("Heading", query),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data.get("Abstract", ""),
                    "source": "duckduckgo"
                })
            
            return formatted_results[:max_results]
            
        except Exception as e:
            logger.error(f"[SearchTool] API 搜索失败: {str(e)}")
            return []


# ============================================================
# 便捷函数：快速执行搜索
# ============================================================

async def quick_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    快速搜索函数
    
    提供简洁的搜索接口，适合快速获取搜索结果。
    
    Args:
        query: 搜索关键词
        max_results: 最大结果数量
        
    Returns:
        Dict[str, Any]: 搜索结果
    """
    tool = SearchTool()
    return await tool.execute({"query": query, "max_results": max_results})


# ============================================================
# 搜索结果格式化工具
# ============================================================

def format_search_results(results: List[Dict[str, str]], 
                          include_numbering: bool = True) -> str:
    """
    格式化搜索结果为可读文本
    
    将结构化的搜索结果转换为易于阅读的格式。
    
    Args:
        results: 搜索结果列表
        include_numbering: 是否包含编号
        
    Returns:
        str: 格式化后的结果文本
    """
    if not results:
        return "未找到相关结果。"
    
    lines = []
    for i, result in enumerate(results, 1):
        title = result.get("title", "无标题")
        url = result.get("url", "")
        snippet = result.get("snippet", "")[:150]
        
        if include_numbering:
            lines.append(f"{i}. {title}")
        else:
            lines.append(f"- {title}")
        
        lines.append(f"  链接: {url}")
        if snippet:
            lines.append(f"  摘要: {snippet}...")
        lines.append("")  # 空行分隔
    
    return "\n".join(lines)
