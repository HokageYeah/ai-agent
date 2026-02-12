"""
网络搜索工具模块

本模块实现了 SearchTool 类，提供基于 DuckDuckGo 的网络搜索功能。

功能特点：
1. 支持多关键词搜索
2. 返回结构化的搜索结果
3. 包含结果来源链接和摘要
4. 支持限制返回结果数量
5. 完善的错误处理和日志记录

使用示例：
    tool = SearchTool()
    results = await tool.execute({
        "query": "Python 机器学习",
        "max_results": 5
    })
"""

from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
import httpx
from app.tools.base import Tool, ToolSchema
from loguru import logger


class SearchTool(Tool):
    """
    网络搜索工具
    
    继承自 Tool 抽象基类，提供基于 DuckDuckGo 的网络搜索功能。
    使用 DuckDuckGo 的 JSON API 获取搜索结果，无需 API Key。
    
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
        # DuckDuckGo Instant Answer API 端点
        self._api_url = "https://api.duckduckgo.com/"
        logger.info("[SearchTool] 网络搜索工具初始化完成")
    
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
        
        参数处理逻辑：
        1. 提取搜索关键词 query
        2. 提取并验证 max_results 参数
        3. 调用 DuckDuckGo API
        4. 解析并格式化返回结果
        
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
            # ========== API 调用阶段 ==========
            # 构建 API 请求 URL
            # 编码搜索关键词
            encoded_query = quote_plus(query)
            api_params = {
                "q": encoded_query,
                "format": "json",
                "no_html": "1",      # 不返回 HTML 格式
                "skip_disambig": "1"  # 跳过消歧义页面
            }
            
            logger.debug(f"[SearchTool] 发送请求到 DuckDuckGo API，URL: {self._api_url}")
            
            # 使用 httpx 发送异步 HTTP 请求
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url,
                    params=api_params,
                    follow_redirects=True
                )
            
            # 检查 HTTP 响应状态
            response.raise_for_status()
            
            # ========== 结果解析阶段 ==========
            data = response.json()
            
            # 解析搜索结果
            # DuckDuckGo API 返回的 RelatedTopics 包含搜索结果
            raw_results = data.get("RelatedTopics", [])
            
            # 格式化结果
            formatted_results = []
            for item in raw_results[:max_results]:
                # 跳过不包含 URL 的结果（如消歧义信息）
                if not item.get("URL"):
                    continue
                
                formatted_results.append({
                    "title": item.get("Text", "")[:200],  # 限制标题长度
                    "url": item.get("URL", ""),
                    "snippet": item.get("Text", "")[:500],  # 限制摘要长度
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
            
            logger.info(f"[SearchTool] 搜索完成，找到 {len(formatted_results)} 条结果")
            
            # ========== 返回结果 ==========
            return {
                "success": True,
                "query": query,
                "results": formatted_results,
                "total_count": len(formatted_results),
                "metadata": {
                    "engine": "duckduckgo",
                    "max_results_requested": max_results
                }
            }
            
        except httpx.TimeoutException:
            logger.error(f"[SearchTool] 搜索超时: '{query}'")
            return {
                "success": False,
                "error": "搜索请求超时，请稍后重试",
                "query": query
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"[SearchTool] HTTP 错误: {e.response.status_code} - '{query}'")
            return {
                "success": False,
                "error": f"搜索请求失败，HTTP 状态码: {e.response.status_code}",
                "query": query
            }
            
        except Exception as e:
            logger.exception(f"[SearchTool] 搜索发生未知错误: {str(e)}")
            return {
                "success": False,
                "error": f"搜索失败: {str(e)}",
                "query": query
            }


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
